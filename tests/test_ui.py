"""Tests for src/ui/view_model.py -- the ProcurementDecision/AgentRunResult
-> UI view model transformation. Deliberately does not touch Streamlit or a
browser: these are plain Python assertions against the view model, which is
what makes UI behavior fast and reliable to verify.

AgentRunResult objects are built via the real run_single_agent_with_trace
pipeline with a ScriptedGeminiClient (tests/agent_fakes.py), so each test
exercises the real tool registry / policy engine / validator wiring, not a
hand-rolled stand-in.
"""

from __future__ import annotations

import requests

from src.agent.single_agent import run_single_agent_with_trace
from src.ui.view_model import MISSING_LABEL, NOT_PROVIDED_LABEL, build_procurement_view
from tests.agent_fakes import ScriptedGeminiClient, stop_turn, tool_call, tool_turn
from tests.test_agent_single import _synthesis


class TestNormalRecommendationRenders:
    def test_req_1001_renders_a_clean_analyzed_view(self, monkeypatch):
        from src.tools import vendor_risk as vendor_risk_tool

        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "security_review_status": "approved",
                "last_review_date": "2026-06-20",
                "processes_personal_data": True,
                "stores_data_outside_region": False,
            },
        )
        client = ScriptedGeminiClient(
            turns=[
                tool_turn(
                    tool_call("get_employee_budget", employee_id="E004"),
                    tool_call("get_vendor_evidence", vendor_name="SignFlow"),
                ),
                stop_turn(),
            ],
            structured_result=_synthesis(recommendation="Proceed with manager approval.", evidence_refs=["E1", "E2"]),
        )
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        assert view.request_id == "REQ-1001"
        assert view.analysis_status == "Analyzed"
        assert view.error_banner is None
        assert view.recommendation == "Proceed with manager approval."
        assert "Manager" in view.required_approvals
        # employee_budget (2 items) + vendor evidence (2 items: registry + service)
        assert len(view.evidence) == 4
        assert view.rationale == "Based on the evidence provided."


class TestMissingInformationRenders:
    def test_req_1006_missing_fields_are_visually_distinct_not_none_or_null(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1006", client=client)
        view = build_procurement_view(result)

        cost_field = next(f for f in view.request_details if f.label == "Annual cost")
        users_field = next(f for f in view.request_details if f.label == "Users/licenses")
        assert cost_field.is_missing is True
        assert cost_field.value == MISSING_LABEL
        assert "None" not in cost_field.value and "null" not in cost_field.value.lower() and "nan" not in cost_field.value.lower()
        assert users_field.is_missing is True
        assert view.list_status_badge == "MISSING"
        assert "annual cost" in view.missing_information

    def test_a_present_but_blank_optional_field_shows_not_provided_not_missing_label(self):
        # "category"/"urgency" aren't POL-1 required fields, so a blank one
        # should read as neutral "Not provided", not the policy-loaded
        # "Missing" label (which is reserved for fields policy actually flags).
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1001", client=client)
        # REQ-1001 has all fields populated in the real data, so simulate the
        # neutral path directly against the formatter used by the view model.
        from src.ui.view_model import _field

        blank_optional = _field("Category", None, None, ())
        assert blank_optional.value == NOT_PROVIDED_LABEL
        assert blank_optional.is_missing is True


class TestRiskFlagsRender:
    def test_overlap_flag_gets_a_human_readable_label_and_keeps_raw_value(self):
        client = ScriptedGeminiClient(
            turns=[
                tool_turn(
                    tool_call("get_employee_budget", employee_id="E001"),
                    tool_call("search_catalog", vendor_name="TaskFlow"),
                ),
                stop_turn(),
            ],
            structured_result=_synthesis(evidence_refs=["E1", "E2"]),
        )
        result = run_single_agent_with_trace("REQ-1008", client=client)
        view = build_procurement_view(result)

        flag = next(f for f in view.risk_flags if f.raw == "existing_tool_overlap")
        assert flag.label == "Existing tool overlap"
        assert view.list_status_badge == "RISK"


class TestHumanHandoffRenders:
    def test_handoff_reasons_reflect_actual_risk_flags(self):
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        result = run_single_agent_with_trace("REQ-1006", client=client)
        view = build_procurement_view(result)

        assert view.human_handoff.required is True
        assert any("Security" in r for r in view.human_handoff.reason_lines) or "Security" in view.human_handoff.required_reviewers
        assert "no purchase" in view.human_handoff.ai_action_note.lower()

    def test_handoff_summary_text_is_generated_from_structured_data_not_another_llm_call(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        assert "PROCUREMENT REVIEW SUMMARY" in view.handoff_summary_text
        assert "REQ-1001" in view.handoff_summary_text
        assert view.recommendation in view.handoff_summary_text


class TestEvidenceProvenanceRenders:
    def test_evidence_carries_source_and_reference(self):
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        assert len(view.evidence) >= 1
        item = view.evidence[0]
        assert item.evidence_id == "E1"
        assert item.source == "employee_data"
        assert item.reference == "employees.csv:E004"


class TestConflictingVendorStateRendersBothSides:
    def test_signalwatch_conflict_shows_both_registry_and_service(self, monkeypatch):
        from src.tools import vendor_risk as vendor_risk_tool

        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "security_review_status": "expired",
                "last_review_date": "2025-07-01",
                "processes_personal_data": False,
                "stores_data_outside_region": False,
            },
        )
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_vendor_evidence", vendor_name="SignalWatch")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1", "E2", "E3"]),
        )
        result = run_single_agent_with_trace("REQ-1007", client=client)
        view = build_procurement_view(result)

        registry_evidence = [e for e in view.evidence if e.source == "vendor_registry"]
        service_evidence = [e for e in view.evidence if e.source == "vendor_risk_service"]
        assert registry_evidence, "registry-side evidence must be shown"
        assert service_evidence, "service-side evidence must be shown"
        assert any("disagree" in e.finding.lower() for e in service_evidence)
        assert any(f.raw == "conflicting_vendor_evidence" for f in view.risk_flags)


class TestUnavailableVendorStateRenders:
    def test_nimbusai_outage_renders_as_unavailable_not_approved(self, monkeypatch):
        from src.tools import vendor_risk as vendor_risk_tool

        def raise_503(name, timeout_seconds=3.0):
            response = requests.Response()
            response.status_code = 503
            raise requests.HTTPError(response=response)

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", raise_503)
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_vendor_evidence", vendor_name="NimbusAI")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        result = run_single_agent_with_trace("REQ-1009", client=client)
        view = build_procurement_view(result)

        assert any(f.raw == "vendor_risk_unavailable" for f in view.risk_flags)
        service_evidence = [e for e in view.evidence if e.source == "vendor_risk_service"]
        assert any("503" in e.finding or "unavailable" in e.finding.lower() or "could not" in e.finding.lower() for e in service_evidence + [])


class TestNoAutonomousApprovalActionExists:
    def test_app_py_contains_no_dangerous_action_labels(self):
        from pathlib import Path

        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8").lower()
        forbidden = ["approve purchase", "buy now", "approve spend", "override security", "accept terms"]
        for phrase in forbidden:
            assert phrase not in app_source, f"app.py must never offer a '{phrase}' action"


class TestLlmUnavailableStateRendersSafely:
    def test_missing_api_key_renders_a_clear_error_banner_not_a_blank_page(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = run_single_agent_with_trace("REQ-1001")  # no client injected -> tries the real (missing) key
        view = build_procurement_view(result)

        assert view.analysis_status == "Automated analysis unavailable"
        assert view.error_banner is not None
        assert "unavailable" in view.error_banner.lower()
        assert view.human_handoff.required is True
        assert view.list_status_badge == "UNAVAILABLE"


class TestMalformedOrEmptyResultDoesNotCrash:
    def test_zero_tool_calls_and_no_synthesis_still_produces_a_valid_view(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=None)
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)  # must not raise

        assert view.evidence == ()
        assert view.policy_checks  # policy still ran even with no evidence
        assert view.tool_calls == ()
        assert view.audit_timeline  # still a full ordered list, just marked skipped

    def test_synthesis_citing_nothing_still_renders(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)
        assert view.evidence == ()
        assert view.recommendation
