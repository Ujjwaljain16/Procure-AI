"""Final deterministic safety validator.

Takes whatever the model produced -- which may be missing, malformed, or
semantically wrong -- plus the trusted, deterministic ``PolicyEvaluation`` and
the evidence actually collected, and produces the ``ProcurementDecision`` that
is actually returned. The model's prose is always subordinate to the policy
engine: this module is the one place that *enforces* that subordination in
code, not merely asks for it in a prompt.

Enforced here:
  1. ``required_approvals`` / ``risk_flags`` / ``missing_information`` /
     ``human_review_required`` always come from ``PolicyEvaluation`` -- the
     model's schema (``AgentSynthesis``) has no field for any of them, so
     there is no code path through which it could set or downgrade one.
  2. Every evidence reference the model cites must be an ID this request's
     tool calls actually produced; anything else is dropped, not trusted.
  3. If the model's output is missing or fails to parse, a conservative
     human-review recommendation is used instead of fabricating certainty.
  4. Text that reads as claiming an approval has already been granted is
     flagged with a corrective note -- POL-11 requires this copilot to never
     represent an approval as already given.
"""

from __future__ import annotations

import re
from typing import Optional

from src.agent.failure_taxonomy import classify_failure_reason
from src.agent.schemas import AgentSynthesis
from src.agent.tools_registry import ToolRegistry
from src.contracts import ProcurementDecision, RunTelemetry
from src.policy_engine import PolicyEvaluation

FALLBACK_RECOMMENDATION = "Unable to produce an automated recommendation; route to human review."
FALLBACK_NEXT_STEP = "A human reviewer should evaluate this request manually using the collected evidence and policy result."

_APPROVED_WORD_PATTERN = re.compile(r"\bapproved\b", re.IGNORECASE)

# Phrases where "approved" legitimately appears without claiming this
# request's approval has already been granted (e.g. describing what approval
# is still needed, or a past, unrelated purchase).
_SAFE_APPROVAL_CONTEXT_PHRASES = (
    "not approved",
    "not yet approved",
    "no approval",
    "pending approval",
    "requires approval",
    "approval required",
    "approval is required",
    "without approval",
    "before approval",
    "needs approval",
    "awaiting approval",
)


def _claims_autonomous_approval(text: str) -> bool:
    lowered = text.lower()
    if not _APPROVED_WORD_PATTERN.search(lowered):
        return False
    if any(phrase in lowered for phrase in _SAFE_APPROVAL_CONTEXT_PHRASES):
        return False
    return True


def _guard_against_autonomous_approval_claims(text: str) -> str:
    if _claims_autonomous_approval(text):
        return f"{text} (Note: no approval has actually been granted -- required approvals remain pending human review.)"
    return text


def build_procurement_decision(
    *,
    request_id: str,
    synthesis: Optional[AgentSynthesis],
    registry: ToolRegistry,
    policy_evaluation: PolicyEvaluation,
    telemetry: RunTelemetry,
    gemini_unavailable_reason: Optional[str] = None,
) -> ProcurementDecision:
    if gemini_unavailable_reason is not None:
        recommendation = f"{classify_failure_reason(gemini_unavailable_reason)[1]} Manual review required."
        next_step = FALLBACK_NEXT_STEP
        cited_evidence = registry.all_evidence()
    elif synthesis is None:
        recommendation = FALLBACK_RECOMMENDATION
        next_step = FALLBACK_NEXT_STEP
        cited_evidence = registry.all_evidence()
    else:
        valid_ids = registry.evidence_ids()
        evidence_by_id = dict(registry.evidence_index())
        # dict.fromkeys de-duplicates while preserving first-seen order, so a
        # model citing the same ID more than once doesn't repeat it in the
        # final evidence list.
        cited_ids = list(dict.fromkeys(eid for eid in synthesis.evidence_refs if eid in valid_ids))
        rejected_ids = list(dict.fromkeys(eid for eid in synthesis.evidence_refs if eid not in valid_ids))
        cited_evidence = tuple(evidence_by_id[eid] for eid in cited_ids) or registry.all_evidence()

        recommendation = (synthesis.recommendation or "").strip() or FALLBACK_RECOMMENDATION
        next_step = (synthesis.next_step or "").strip() or FALLBACK_NEXT_STEP
        if rejected_ids:
            recommendation = (
                f"{recommendation} (Note: {len(rejected_ids)} cited evidence reference(s) "
                "could not be verified and were dropped.)"
            )

    recommendation = _guard_against_autonomous_approval_claims(recommendation)
    next_step = _guard_against_autonomous_approval_claims(next_step)

    # The one narrow, explicitly-sanctioned exception to "risk flags always
    # come from the policy engine": the model may additively signal that it
    # noticed injected text. It cannot remove or alter anything the policy
    # engine produced, and this is the only flag it can add.
    risk_flags = list(policy_evaluation.risk_flags)
    if synthesis is not None and synthesis.prompt_injection_detected and "prompt_injection_detected" not in risk_flags:
        risk_flags.append("prompt_injection_detected")

    return ProcurementDecision(
        request_id=request_id,
        recommendation=recommendation,
        evidence=list(cited_evidence),
        # Always from the deterministic policy evaluation -- never from the
        # model, which has no field through which to set or influence any of
        # these four (risk_flags may additively gain prompt_injection_detected
        # only, per above).
        required_approvals=list(policy_evaluation.required_approvals),
        missing_information=list(policy_evaluation.missing_information),
        risk_flags=risk_flags,
        human_review_required=policy_evaluation.human_review_required,
        next_step=next_step,
        telemetry=telemetry,
    )
