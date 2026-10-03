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

_APPROVAL_CLAIM_PATTERN = re.compile(
    r"\b(?:approved|signed[ -]off|green[ -]?lit|authori[sz]ed|approval (?:has been |was |is )?granted)\b",
    re.IGNORECASE,
)

# Safe context is judged per clause, against the clause that contains the
# claim -- never against the whole text. A phrase like "requires approval" in
# one clause must not clear an approval claim in another.
_SAFE_CLAUSE_PATTERN = re.compile(
    r"\b(?:not (?:yet )?(?:approved|authori[sz]ed)|no approval|pending approval|requires? (?:\w+ )?approval"
    r"|approval (?:is )?(?:required|needed|outstanding|pending)|needs? (?:\w+ )?approval|awaiting approval"
    r"|without approval|before (?:any )?approval|once approved|if approved|must be approved|to be approved"
    r"|(?:do not|don't|never|cannot|can't)\b[^.;!?]{0,40}\b(?:approved|approval|authori[sz]ed))\b",
    re.IGNORECASE,
)

_CLAUSE_SPLIT = re.compile(r"(?<=[.;!?])\s+|\n+|,\s*|\s+(?:but|however|although|though|while|whereas)\s+", re.IGNORECASE)


def _claims_autonomous_approval(text: str) -> bool:
    for clause in _CLAUSE_SPLIT.split(text):
        if _APPROVAL_CLAIM_PATTERN.search(clause) and not _SAFE_CLAUSE_PATTERN.search(clause):
            return True
    return False


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
        if not cited_ids:
            # The evidence list is what was retrieved, not what the model
            # relied on. Say so, rather than presenting it as the model's
            # cited support.
            recommendation = f"{recommendation} (Note: the model cited no verifiable evidence; the retrieved evidence is listed for review.)"
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
