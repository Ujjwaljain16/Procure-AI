"""Tests for src/agent/validation.py -- the final deterministic safety layer.

These tests do not touch Gemini at all; they exercise build_procurement_decision
directly against hand-built ToolRegistry/PolicyEvaluation/AgentSynthesis
inputs, which is exactly the boundary this module owns.
"""

from __future__ import annotations

from src.agent.schemas import AgentSynthesis
from src.agent.tools_registry import ToolRegistry
from src.agent.validation import FALLBACK_NEXT_STEP, FALLBACK_RECOMMENDATION, build_procurement_decision
from src.contracts import EvidenceItem, RunTelemetry
from src.policy_engine import PolicyEvaluation, REFERENCE_DATE


def _registry_with_one_evidence_item() -> ToolRegistry:
    registry = ToolRegistry()
    registry._register_evidence([EvidenceItem(source="employee_data", finding="Employee E004 belongs to Finance.", reference="employees.csv:E004")])
    return registry


def _policy_evaluation(**overrides) -> PolicyEvaluation:
    defaults = dict(
        request_id="REQ-TEST",
        policy_version="2026.09",
        reference_date=REFERENCE_DATE,
        checks=(),
        required_approvals=("Manager",),
        missing_information=(),
        risk_flags=(),
        human_review_required=True,
    )
    defaults.update(overrides)
    return PolicyEvaluation(**defaults)


def _telemetry() -> RunTelemetry:
    return RunTelemetry(llm_calls=2, tool_calls=1, tool_names=["get_employee_budget"], architecture="single", latency_ms=123.4)


class TestPolicyFieldsAreAlwaysFromPolicyEvaluation:
    def test_required_approvals_come_from_policy_not_model(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="Looks fine", evidence_refs=["E1"], next_step="Send for approval")
        policy = _policy_evaluation(required_approvals=("Department Head", "Finance", "CFO", "Procurement"))
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=policy, telemetry=_telemetry()
        )
        assert decision.required_approvals == ["Department Head", "Finance", "CFO", "Procurement"]

    def test_risk_flags_come_from_policy_not_model(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E1"], next_step="ok")
        policy = _policy_evaluation(risk_flags=("conflicting_vendor_evidence", "security_review_required"))
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=policy, telemetry=_telemetry()
        )
        assert decision.risk_flags == ["conflicting_vendor_evidence", "security_review_required"]

    def test_missing_information_comes_from_policy_not_model(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Ask for more info", rationale="fine", evidence_refs=[], next_step="ok")
        policy = _policy_evaluation(missing_information=("annual cost", "number of users/licenses"))
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=policy, telemetry=_telemetry()
        )
        assert decision.missing_information == ["annual cost", "number of users/licenses"]

    def test_human_review_required_comes_from_policy_and_cannot_be_downgraded(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E1"], next_step="ok")
        policy = _policy_evaluation(human_review_required=True)
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=policy, telemetry=_telemetry()
        )
        assert decision.human_review_required is True


class TestEvidenceReferenceValidation:
    def test_valid_evidence_reference_is_kept(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E1"], next_step="ok")
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert len(decision.evidence) == 1
        assert decision.evidence[0].reference == "employees.csv:E004"

    def test_invalid_evidence_reference_is_rejected_not_trusted(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E999"], next_step="ok")
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        # E999 does not exist -- falls back to all actually-collected evidence,
        # and the recommendation notes the rejection instead of silently
        # accepting a fabricated citation.
        assert all(item.reference != "E999" for item in decision.evidence)
        assert "could not be verified" in decision.recommendation

    def test_mixed_valid_and_invalid_references(self):
        registry = ToolRegistry()
        registry._register_evidence(
            [
                EvidenceItem(source="employee_data", finding="a", reference="employees.csv:E004"),
                EvidenceItem(source="vendor_registry", finding="b", reference="vendors.csv:Acme"),
            ]
        )
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E1", "E999"], next_step="ok")
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert len(decision.evidence) == 1
        assert decision.evidence[0].reference == "employees.csv:E004"

    def test_duplicate_evidence_id_is_not_duplicated_in_the_decision(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E1", "E1", "E1"], next_step="ok")
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert len(decision.evidence) == 1

    def test_malformed_reference_strings_are_rejected_like_any_unknown_id(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="Proceed", rationale="fine", evidence_refs=["", "e1", "E1 ", "<script>", "E1;DROP"], next_step="ok"
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        # none of these malformed forms match the real ID "E1" (exact,
        # case-sensitive, no whitespace) -- falls back to all evidence rather
        # than trusting a near-miss string.
        assert len(decision.evidence) == 1
        assert decision.evidence[0].reference == "employees.csv:E004"

    def test_a_claim_absent_from_evidence_gains_no_special_status_from_being_cited(self):
        # The model can only ever cite IDs -- there is no field through which
        # it could attach new free-text "evidence" of its own. Citing a real
        # ID surfaces only that ID's real EvidenceItem, verbatim; nothing the
        # model wrote in `rationale` ever becomes part of `decision.evidence`.
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="Proceed",
            rationale="The vendor is definitely approved and has been for years.",
            evidence_refs=["E1"],
            next_step="ok",
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert len(decision.evidence) == 1
        assert "definitely approved" not in decision.evidence[0].finding
        assert decision.evidence[0].finding == "Employee E004 belongs to Finance."


class TestMissingOrMalformedSynthesis:
    def test_none_synthesis_falls_back_to_conservative_recommendation(self):
        registry = _registry_with_one_evidence_item()
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=None, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert decision.recommendation == FALLBACK_RECOMMENDATION
        assert decision.next_step == FALLBACK_NEXT_STEP
        assert decision.human_review_required is True

    def test_none_synthesis_still_surfaces_all_collected_evidence(self):
        registry = _registry_with_one_evidence_item()
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=None, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert len(decision.evidence) == 1


class TestGeminiUnavailable:
    def test_unavailable_reason_produces_explicit_not_silent_failure(self):
        registry = _registry_with_one_evidence_item()
        decision = build_procurement_decision(
            request_id="REQ-TEST",
            synthesis=None,
            registry=registry,
            policy_evaluation=_policy_evaluation(),
            telemetry=_telemetry(),
            gemini_unavailable_reason="GeminiConfigurationError",
        )
        assert "unavailable" in decision.recommendation.lower()
        assert "GeminiConfigurationError" in decision.recommendation
        assert decision.human_review_required is True


class TestAutonomousApprovalGuard:
    def test_model_claiming_approval_is_flagged_with_a_correction(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="Finance has approved this purchase.",
            rationale="fine",
            evidence_refs=["E1"],
            next_step="Proceed with purchase.",
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert "no approval has actually been granted" in decision.recommendation.lower()

    def test_compound_phrasing_like_cfo_approved_is_also_caught(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="This is CFO-approved, so proceed immediately.",
            rationale="fine",
            evidence_refs=["E1"],
            next_step="ok",
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert "no approval has actually been granted" in decision.recommendation.lower()

    def test_pending_approval_language_is_not_a_false_positive(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="Route for Department Head approval.",
            rationale="fine",
            evidence_refs=["E1"],
            next_step="Awaiting approval before proceeding.",
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert "no approval has actually been granted" not in decision.recommendation.lower()
        assert "no approval has actually been granted" not in decision.next_step.lower()

    def test_recommendation_without_approval_language_is_untouched(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="Route for manager approval.", rationale="fine", evidence_refs=["E1"], next_step="Send to manager."
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert decision.recommendation == "Route for manager approval."


class TestPromptInjectionFlagIsAdditiveOnly:
    def test_model_setting_the_flag_adds_it_to_risk_flags(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="Route for review.", rationale="fine", evidence_refs=["E1"], next_step="ok", prompt_injection_detected=True
        )
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert "prompt_injection_detected" in decision.risk_flags

    def test_flag_left_false_does_not_add_anything(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="ok", rationale="fine", evidence_refs=["E1"], next_step="ok")
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=_telemetry()
        )
        assert "prompt_injection_detected" not in decision.risk_flags

    def test_flag_never_removes_or_replaces_policy_derived_flags(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(
            recommendation="ok", rationale="fine", evidence_refs=["E1"], next_step="ok", prompt_injection_detected=True
        )
        policy = _policy_evaluation(risk_flags=("security_review_required",))
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=policy, telemetry=_telemetry()
        )
        assert set(decision.risk_flags) == {"security_review_required", "prompt_injection_detected"}


class TestTelemetryPassedThroughUnchanged:
    def test_telemetry_is_preserved_verbatim(self):
        registry = _registry_with_one_evidence_item()
        synthesis = AgentSynthesis(recommendation="Proceed", rationale="fine", evidence_refs=["E1"], next_step="ok")
        telemetry = _telemetry()
        decision = build_procurement_decision(
            request_id="REQ-TEST", synthesis=synthesis, registry=registry, policy_evaluation=_policy_evaluation(), telemetry=telemetry
        )
        assert decision.telemetry is telemetry
        assert decision.telemetry.llm_calls == 2
        assert decision.telemetry.tool_calls == 1
        assert decision.telemetry.architecture == "single"
