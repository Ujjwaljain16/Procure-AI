"""Executable form of the policy 5 interpretation adjudicated for S-1007.

Policy 5 makes two things mandatory when a registry and the vendor-risk service disagree and the
live review is expired:
  - security review is required (an expired assessment is a Security trigger), and
  - the conflict is surfaced and routed to Security/manual review.
The policy lists vendor_review_expired only under "Suggested risk flags". So the engine must not be
required to emit that label. This test asserts the mandatory outcomes, and deliberately asserts
nothing about the suggested label either way.

Adjudicated after the correctness run that first showed the disagreement; see the revision_log
of S-1007 in evaluation/correctness/ground_truth.json.
"""

from __future__ import annotations

from src import data_access
from src.agent.tools_registry import ToolRegistry
from src.evidence import gather_mandatory_evidence
from src.policy_engine import PolicyContext, RequestFields, evaluate_policy


def _context_for(request_id: str) -> PolicyContext:
    """Build the policy input the way the agents do: from the code-owned evidence preflight."""
    raw = data_access.get_request_validated(request_id)
    registry: ToolRegistry = gather_mandatory_evidence(raw)
    return PolicyContext(
        request=RequestFields.from_raw(raw, department=registry.employee_department()),
        budget=registry.budget_evidence(),
        catalog_overlap_matches=registry.catalog_matches(),
        vendor_registry=registry.vendor_registry_evidence(),
        vendor_risk=registry.vendor_risk_evidence(),
    )


def test_conflicting_vendor_evidence_requires_security_but_not_expired_flag(live_vendor_records):
    # REQ-1007: registry says Approved (review 2025-07-01); the live service says expired (same review date).
    evaluation = evaluate_policy(_context_for("REQ-1007"))

    # Mandatory: an expired assessment triggers Security review (policy 5).
    assert "Security" in evaluation.required_approvals
    assert "security_review_required" in evaluation.risk_flags
    # Mandatory: the registry/service disagreement is surfaced and routed to manual review (policy 5).
    assert "conflicting_vendor_evidence" in evaluation.risk_flags
    assert evaluation.human_review_required is True
    # Not asserted either way: vendor_review_expired is a suggested label, not a requirement (policy 5).

