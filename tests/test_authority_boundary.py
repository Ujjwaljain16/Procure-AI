"""The authority boundary, for both architectures.

Architecture A and Architecture B must see the same authoritative evidence for
the same validated request, and no model behavior may change the deterministic
policy fields. Every test here runs the same request through A and B and asserts
the property for each.
"""

from __future__ import annotations

import pytest

from src.agent import single_agent, staged_agent
from src.agent.gemini_adapter import ModelOutputError
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.agent.tools_registry import ToolRegistry
from src.evidence import gather_mandatory_evidence
from tests.agent_fakes import ScriptedGeminiClient, stop_turn, tool_call, tool_turn
from tests.staged_agent_fakes import ScriptedStagedGeminiClient
from tests.test_agent_single import _synthesis
from tests.test_staged_agent import _analyst_report

ARCHITECTURES = ("single", "staged")
POLICY_FIELDS = ("required_approvals", "risk_flags", "missing_information", "human_review_required")


def _run(architecture, request_id, *, turns=(), structured=None, analyst=None, client_cls=None):
    if architecture == "single":
        client = (client_cls or ScriptedGeminiClient)(turns=list(turns), structured_result=structured or _synthesis(evidence_refs=[]))
        return run_single_agent_with_trace(request_id, client=client)
    client = (client_cls or ScriptedStagedGeminiClient)(
        turns=list(turns),
        analyst_report=analyst if analyst is not None else _analyst_report(),
        structured_result=structured or _synthesis(evidence_refs=[]),
    )
    return run_staged_agent_with_trace(request_id, client=client)


def _policy_fields(decision) -> dict:
    return {field: getattr(decision, field) for field in POLICY_FIELDS}


def _normal(architecture, request_id):
    return _run(architecture, request_id, turns=[stop_turn()])


def _down_class(base):
    class _Down(base):
        def generate_turn(self, contents, tool_specs, system_instruction):
            raise ConnectionError("model unreachable")

    return _Down


@pytest.mark.parametrize("arch", ARCHITECTURES)
class TestHostileModelCannotChangePolicyInputs:
    def test_substituting_the_vendor_does_not_change_the_policy_result(self, arch):
        normal = _normal(arch, "REQ-1007")
        hostile = _run(arch, "REQ-1007", turns=[tool_turn(tool_call("get_vendor_evidence", vendor_name="SignFlow")), stop_turn()])
        assert _policy_fields(hostile.decision) == _policy_fields(normal.decision)

    def test_substituting_the_employee_does_not_change_budget_or_department(self, arch):
        normal = _normal(arch, "REQ-1001")
        hostile = _run(arch, "REQ-1001", turns=[tool_turn(tool_call("get_employee_budget", employee_id="E001")), stop_turn()])
        assert _policy_fields(hostile.decision) == _policy_fields(normal.decision)
        assert hostile.registry.employee_department() == normal.registry.employee_department()

    def test_a_refused_substitution_is_recorded_as_a_failed_call(self, arch):
        hostile = _run(arch, "REQ-1001", turns=[tool_turn(tool_call("get_employee_budget", employee_id="E001")), stop_turn()])
        refused = [r for r in hostile.registry.execution_log if r.arguments.get("employee_id") == "E001"]
        assert refused and all(r.success is False for r in refused)

    def test_a_model_that_skips_the_catalog_cannot_make_overlap_disappear(self, arch):
        # REQ-1008 (TaskFlow Pro) overlaps the catalog. The model calls nothing at all.
        silent = _run(arch, "REQ-1008", turns=[stop_turn()])
        assert "existing_tool_overlap" in silent.decision.risk_flags
        assert silent.registry.catalog_matches()


@pytest.mark.parametrize("arch", ARCHITECTURES)
class TestModelAvailabilityDoesNotChangePolicy:
    @pytest.mark.parametrize("request_id", ["REQ-1001", "REQ-1005", "REQ-1007", "REQ-1008"])
    def test_outage_on_the_first_call_gives_the_same_policy_fields(self, arch, request_id):
        normal = _normal(arch, request_id)
        base = ScriptedGeminiClient if arch == "single" else ScriptedStagedGeminiClient
        outage = _run(arch, request_id, client_cls=_down_class(base))
        assert outage.gemini_unavailable_reason == "ConnectionError"
        assert _policy_fields(outage.decision) == _policy_fields(normal.decision)

    @pytest.mark.parametrize("request_id", ["REQ-1001", "REQ-1006"])
    def test_malformed_structured_output_cannot_change_policy_fields(self, arch, request_id):
        normal = _normal(arch, request_id)
        malformed = _run(arch, request_id, turns=[stop_turn()], structured=ModelOutputError("PARSE_FAILED"))
        assert malformed.gemini_unavailable_reason == "PARSE_FAILED"
        assert _policy_fields(malformed.decision) == _policy_fields(normal.decision)


class TestStagedAnalystFailureCannotChangePolicy:
    @pytest.mark.parametrize("request_id", ["REQ-1001", "REQ-1008"])
    def test_analyst_report_failure_gives_the_same_policy_fields(self, request_id):
        normal = _normal("staged", request_id)
        broken = _run("staged", request_id, turns=[stop_turn()], analyst=ModelOutputError("EMPTY_RESPONSE"))
        assert _policy_fields(broken.decision) == _policy_fields(normal.decision)


@pytest.mark.parametrize("arch", ARCHITECTURES)
class TestSupplementalCallsCannotMutateEvidence:
    def test_a_supplemental_catalog_lookup_does_not_change_policy_catalog_matches(self, arch):
        before = _normal(arch, "REQ-1008").registry.catalog_matches()
        after = _run(
            arch,
            "REQ-1008",
            turns=[tool_turn(tool_call("search_catalog", product_name="TaskFlow Pro", vendor_name="TaskFlow", category="Project Management")), stop_turn()],
        )
        assert after.registry.catalog_matches() == before

    def test_supplemental_results_are_evidence_but_not_policy_inputs(self, arch):
        result = _run(arch, "REQ-1001", turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()])
        mandatory = _normal(arch, "REQ-1001").registry
        assert result.registry.budget_evidence() == mandatory.budget_evidence()


@pytest.mark.parametrize("arch", ARCHITECTURES)
class TestEvidenceCitationsAreReal:
    def test_an_invalid_citation_is_rejected_and_a_real_one_survives(self, arch):
        probe = _normal(arch, "REQ-1001")
        index = dict(probe.registry.evidence_index())
        real_id = next(iter(index))  # an id the registry actually produced in this run

        result = _run(arch, "REQ-1001", turns=[stop_turn()], structured=_synthesis(evidence_refs=[real_id, "E999"]))
        key = lambda item: (item.source, item.finding, item.reference)  # noqa: E731 -- EvidenceItem is unhashable
        cited = {key(item) for item in result.decision.evidence}

        # valid half: the real citation is carried through
        assert key(index[real_id]) in cited
        # invalid half: nothing in the decision traces to E999, which was never retrieved
        retrieved = {key(item) for _, item in result.registry.evidence_index()}
        assert cited <= retrieved


@pytest.mark.parametrize("arch", ARCHITECTURES)
class TestPreflightRunsBeforeAnyModelCall:
    def test_mandatory_evidence_is_gathered_before_the_model_is_called(self, arch, monkeypatch):
        module = single_agent if arch == "single" else staged_agent
        seen = {}

        def probe(raw, registry=None):
            registry = gather_mandatory_evidence(raw, registry)
            seen["calls"] = registry.call_count
            return registry

        monkeypatch.setattr(module, "gather_mandatory_evidence", probe)
        _run(arch, "REQ-1001", turns=[])
        assert seen["calls"] >= 2


class TestMandatoryCallsUseOnlyRequestValues:
    def test_mandatory_calls_use_only_request_values(self):
        raw = {"request_id": "X", "requester_id": "E004", "product_name": "P", "vendor_name": "V", "category": "C"}
        registry = gather_mandatory_evidence(raw, ToolRegistry())
        for record in registry.execution_log:
            if record.tool_name == "get_employee_budget":
                assert record.arguments == {"employee_id": "E004"}
            if record.tool_name == "get_vendor_evidence":
                assert record.arguments == {"vendor_name": "V"}
