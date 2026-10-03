"""The authority boundary: no model behavior can change the deterministic policy
inputs. Each test runs the same request with a normal, hostile, or unavailable
model and asserts the policy-derived fields are identical."""

from __future__ import annotations

import pytest

from src.agent import single_agent
from src.agent.gemini_adapter import ModelOutputError
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.tools_registry import ToolRegistry
from src.evidence import gather_mandatory_evidence
from src.tools import vendor_risk as vendor_risk_tool
from tests.agent_fakes import ScriptedGeminiClient, stop_turn, tool_call, tool_turn
from tests.test_agent_single import _synthesis

POLICY_FIELDS = ("required_approvals", "risk_flags", "missing_information", "human_review_required")


@pytest.fixture(autouse=True)
def _no_network_vendor_service(monkeypatch):
    def unavailable(name, timeout_seconds=3.0):
        import requests

        raise requests.ConnectionError("no vendor service in unit tests")

    monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", unavailable)


def _policy_fields(decision) -> dict:
    return {field: getattr(decision, field) for field in POLICY_FIELDS}


def _normal(request_id: str):
    client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
    return run_single_agent_with_trace(request_id, client=client)


def _with_turns(request_id: str, turns, structured=None):
    client = ScriptedGeminiClient(turns=turns, structured_result=structured or _synthesis(evidence_refs=[]))
    return run_single_agent_with_trace(request_id, client=client)


class TestHostileModelCannotChangePolicyInputs:
    def test_substituting_the_vendor_does_not_change_the_policy_result(self):
        normal = _normal("REQ-1007")
        hostile = _with_turns("REQ-1007", [tool_turn(tool_call("get_vendor_evidence", vendor_name="SignFlow")), stop_turn()])
        assert _policy_fields(hostile.decision) == _policy_fields(normal.decision)

    def test_substituting_the_employee_does_not_change_budget_or_department(self):
        normal = _normal("REQ-1001")
        hostile = _with_turns("REQ-1001", [tool_turn(tool_call("get_employee_budget", employee_id="E001")), stop_turn()])
        assert _policy_fields(hostile.decision) == _policy_fields(normal.decision)
        assert hostile.registry.employee_department() == normal.registry.employee_department()

    def test_a_refused_substitution_is_recorded_as_a_failed_call(self):
        hostile = _with_turns("REQ-1001", [tool_turn(tool_call("get_employee_budget", employee_id="E001")), stop_turn()])
        refused = [r for r in hostile.registry.execution_log if r.arguments.get("employee_id") == "E001"]
        assert refused and all(r.success is False for r in refused)

    def test_a_model_that_skips_the_catalog_cannot_make_overlap_disappear(self):
        # REQ-1008 (TaskFlow Pro) overlaps the catalog. The model calls nothing at all.
        silent = _with_turns("REQ-1008", [stop_turn()])
        assert "existing_tool_overlap" in silent.decision.risk_flags
        assert silent.registry.catalog_matches()


class TestModelAvailabilityDoesNotChangePolicy:
    @pytest.mark.parametrize("request_id", ["REQ-1001", "REQ-1005", "REQ-1007", "REQ-1008"])
    def test_outage_on_the_first_call_gives_the_same_policy_fields(self, request_id):
        normal = _normal(request_id)

        class _Down(ScriptedGeminiClient):
            def generate_turn(self, contents, tool_specs, system_instruction):
                raise ConnectionError("model unreachable")

        outage = run_single_agent_with_trace(request_id, client=_Down(turns=[], structured_result=_synthesis()))
        assert outage.gemini_unavailable_reason == "ConnectionError"
        assert _policy_fields(outage.decision) == _policy_fields(normal.decision)

    @pytest.mark.parametrize("request_id", ["REQ-1001", "REQ-1006"])
    def test_malformed_model_output_cannot_change_policy_fields(self, request_id):
        normal = _normal(request_id)
        malformed = ScriptedGeminiClient(turns=[stop_turn()], structured_result=ModelOutputError("PARSE_FAILED"))
        result = run_single_agent_with_trace(request_id, client=malformed)
        assert result.gemini_unavailable_reason == "PARSE_FAILED"
        assert _policy_fields(result.decision) == _policy_fields(normal.decision)


class TestSupplementalCallsCannotMutateEvidence:
    def test_a_supplemental_catalog_lookup_does_not_change_policy_catalog_matches(self):
        before = _normal("REQ-1008").registry.catalog_matches()
        after = _with_turns("REQ-1008", [tool_turn(tool_call("search_catalog", product_name="TaskFlow Pro", vendor_name="TaskFlow", category="Project Management")), stop_turn()])
        assert after.registry.catalog_matches() == before

    def test_supplemental_results_are_evidence_but_not_policy_inputs(self):
        result = _with_turns("REQ-1001", [tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()])
        mandatory = _normal("REQ-1001").registry
        assert result.registry.budget_evidence() == mandatory.budget_evidence()


class TestEvidenceCitationsAreReal:
    def test_an_invalid_citation_is_rejected_and_a_real_one_survives(self):
        probe = _normal("REQ-1001")
        index = dict(probe.registry.evidence_index())
        real_id = next(iter(index))  # an id the registry actually produced in this run
        assert real_id not in ("E999",)

        result = _with_turns("REQ-1001", [stop_turn()], structured=_synthesis(evidence_refs=[real_id, "E999"]))
        key = lambda item: (item.source, item.finding, item.reference)  # noqa: E731 -- EvidenceItem is unhashable
        cited = {key(item) for item in result.decision.evidence}

        # valid half: the real citation is carried through
        assert key(index[real_id]) in cited
        # invalid half: nothing in the decision traces to E999, which was never retrieved
        retrieved = {key(item) for _, item in result.registry.evidence_index()}
        assert cited <= retrieved


class TestPreflightRunsBeforeAnyModelCall:
    def test_mandatory_evidence_is_gathered_even_when_the_client_is_never_called(self, monkeypatch):
        seen = {}

        def probe(raw, registry=None):
            registry = gather_mandatory_evidence(raw, registry)
            seen["calls"] = registry.call_count
            return registry

        monkeypatch.setattr(single_agent, "gather_mandatory_evidence", probe)
        client = ScriptedGeminiClient(turns=[], structured_result=_synthesis(evidence_refs=[]))
        run_single_agent_with_trace("REQ-1001", client=client)
        assert seen["calls"] >= 2

    def test_mandatory_calls_use_only_request_values(self):
        raw = {"request_id": "X", "requester_id": "E004", "product_name": "P", "vendor_name": "V", "category": "C"}
        registry = gather_mandatory_evidence(raw, ToolRegistry())
        for record in registry.execution_log:
            if record.tool_name == "get_employee_budget":
                assert record.arguments == {"employee_id": "E004"}
            if record.tool_name == "get_vendor_evidence":
                assert record.arguments == {"vendor_name": "V"}
