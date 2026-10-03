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
from src.ui.view_model import MISSING_LABEL, NOT_PROVIDED_LABEL, build_procurement_view, classify_failure_reason
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
        # the view lists every retrieved item: the preflight's (budget, catalog, history, vendor) plus the model's supplemental lookups
        assert len(view.evidence) == len(result.registry.all_evidence())
        assert len(view.evidence) > 0
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


class TestClassifyFailureReason:
    def test_known_reasons_map_to_their_category(self):
        assert classify_failure_reason("GeminiConfigurationError")[0] == "MODEL_UNAVAILABLE"
        assert classify_failure_reason("ANALYSIS_TIMEOUT")[0] == "ANALYSIS_TIMEOUT"

    def test_an_unrecognized_raw_exception_name_defaults_to_model_unavailable(self):
        category, message = classify_failure_reason("SomeBrandNewSdkExceptionType")
        assert category == "MODEL_UNAVAILABLE"
        assert "SomeBrandNewSdkExceptionType" not in message  # the raw name never leaks into the headline

    def test_the_message_never_contains_a_raw_exception_class_name(self):
        for raw in ("ClientError", "ServerError", "GeminiConfigurationError"):
            _, message = classify_failure_reason(raw)
            assert raw not in message


class TestErrorBannerNeverLeaksRawExceptionNames:
    def test_missing_api_key_banner_does_not_say_geminiconfigurationerror(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = run_single_agent_with_trace("REQ-1001")
        view = build_procurement_view(result)

        assert "GeminiConfigurationError" not in view.error_banner
        assert view.failure_category == "MODEL_UNAVAILABLE"


class TestVendorSecurityPanel:
    def test_conflicting_evidence_renders_both_sides_with_a_conflicting_verdict(self, monkeypatch):
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

        assert view.vendor_security is not None
        assert view.vendor_security.overall_status == "conflicting"
        assert view.vendor_security.registry_status is not None
        assert view.vendor_security.live_status is not None
        assert "manual" in view.vendor_security.action_text.lower()

    def test_unavailable_vendor_service_renders_as_unavailable(self, monkeypatch):
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

        assert view.vendor_security is not None
        assert view.vendor_security.overall_status == "unavailable"
        assert view.vendor_security.live_status is None or view.vendor_security.live_status == "Unavailable"

    def test_a_current_approved_vendor_renders_as_verified(self, monkeypatch):
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
            turns=[tool_turn(tool_call("get_vendor_evidence", vendor_name="SignFlow")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1", "E2"]),
        )
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        assert view.vendor_security is not None
        assert view.vendor_security.overall_status == "verified"

    def test_vendor_check_is_always_made_so_an_unanswering_service_renders_unavailable_not_hidden(self):
        # The preflight always consults the vendor service, even if the model never asks. With the
        # service unreachable (the suite's default), the panel must say so, never disappear.
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        assert view.vendor_security is not None
        assert view.vendor_security.overall_status == "unavailable"


class TestConstraintsSummary:
    def test_includes_passing_and_flagged_checks_with_distinct_icons(self):
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        result = run_single_agent_with_trace("REQ-1006", client=client)
        view = build_procurement_view(result)

        assert view.constraints_summary
        icons = {c.icon for c in view.constraints_summary}
        assert icons  # at least one icon present
        for constraint in view.constraints_summary:
            assert constraint.icon in ("✓", "⚠")
            assert constraint.text

    def test_excludes_skipped_checks(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        skipped_rule_ids = {c.rule_id for c in view.policy_checks if c.status_kind == "skipped"}
        if skipped_rule_ids:
            summary_texts = {c.text for c in view.constraints_summary}
            policy_detail_by_rule = {c.rule_id: c.detail for c in view.policy_checks}
            for rule_id in skipped_rule_ids:
                assert policy_detail_by_rule[rule_id] not in summary_texts


class TestDecisionTraceHasOnePolicyRuleStagePerCheck:
    def test_audit_timeline_includes_a_stage_for_every_policy_check(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        for check in view.policy_checks:
            assert any(check.rule_id in stage.label for stage in view.audit_timeline), check.rule_id

    def test_a_flagged_check_gets_a_flagged_stage_not_a_failed_one(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1006", client=client)
        view = build_procurement_view(result)

        flagged_checks = [c for c in view.policy_checks if c.status_kind == "flagged"]
        assert flagged_checks
        for check in flagged_checks:
            stage = next(s for s in view.audit_timeline if check.rule_id in s.label)
            assert stage.status == "flagged"


class TestLifecycleView:
    def test_default_branch_when_nothing_is_missing_or_unavailable(self, monkeypatch):
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
                tool_turn(tool_call("get_employee_budget", employee_id="E004"), tool_call("get_vendor_evidence", vendor_name="SignFlow")),
                stop_turn(),
            ],
            structured_result=_synthesis(evidence_refs=["E1", "E2"]),
        )
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)

        assert view.lifecycle.branch == "default"
        assert view.lifecycle.stages[0].state == "done"  # Received
        current = [s for s in view.lifecycle.stages if s.state == "current"]
        assert len(current) == 1
        assert current[0].label == "Human review"

    def test_missing_information_branch(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1006", client=client)
        view = build_procurement_view(result)

        assert view.lifecycle.branch == "missing_information"
        assert [s.label for s in view.lifecycle.stages] == ["Received", "Missing information", "Requester action required"]
        assert view.lifecycle.stages[1].state == "current"
        assert view.lifecycle.stages[2].state == "pending"

    def test_evidence_unavailable_branch_takes_priority_over_missing_information(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = run_single_agent_with_trace("REQ-1006")  # also has missing fields, but Gemini is unavailable too
        view = build_procurement_view(result)

        assert view.lifecycle.branch == "evidence_unavailable"
        assert view.lifecycle.stages[1].state == "current"
        assert view.lifecycle.stages[1].label == "Evidence unavailable"


class TestMalformedOrEmptyResultDoesNotCrash:
    def test_no_model_calls_and_no_synthesis_still_produces_a_valid_view(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=None)
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)  # must not raise

        # the preflight still ran, so the view lists its evidence and attempts even though the model did nothing
        assert len(view.evidence) == len(result.registry.all_evidence())
        assert view.policy_checks  # policy still ran
        assert len(view.tool_calls) == len(result.registry.execution_log)
        assert view.audit_timeline  # still a full ordered list, just marked skipped

    def test_synthesis_citing_nothing_still_renders(self):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
        result = run_single_agent_with_trace("REQ-1001", client=client)
        view = build_procurement_view(result)
        # no citations, yet the view still shows the evidence that was gathered
        assert len(view.evidence) == len(result.registry.all_evidence())
        assert view.recommendation


class TestFreeTextIsEscapedForMarkdown:
    def test_hostile_request_field_renders_as_literal_text(self):
        from src.ui.view_model import md_escape

        rendered = md_escape("![tracker](http://evil.example/p.png) <script>x</script>")
        assert "![tracker]" not in rendered
        assert "<script>" not in rendered
        assert "\!\[" in rendered
