"""UNKNOWN vendor freshness.

Clause: data/procurement_policy.md section 5 -- "A vendor security assessment is considered
current for 365 days from its review date." and "Security review is required when ... the current
vendor security assessment is missing, expired, or not completed."

An 'approved' status with no review date cannot be shown to be current, so it must not be
treated as current. Only this case changes; every dated case behaves exactly as before
(including a future-dated review, which is NOT given special treatment).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.policy_engine import (
    AssessmentState,
    BudgetEvidence,
    PolicyContext,
    RequestFields,
    VendorRegistryEvidence,
    VendorRiskAvailability,
    VendorRiskEvidence,
    evaluate_policy,
    evaluate_vendor_security_assessment,
)

REF = date(2026, 9, 30)


def _risk(status="approved", last="2026-06-01", available=True):
    if not available:
        return VendorRiskEvidence.unavailable("V")
    return VendorRiskEvidence("V", VendorRiskAvailability.AVAILABLE, status, date.fromisoformat(last) if last else None, False, False, "low")


REG = VendorRegistryEvidence("V", "Approved", "Approved", date(2026, 6, 1), "Approved")


@pytest.mark.parametrize(
    "risk,expected",
    [
        (_risk("approved", "2026-06-01"), AssessmentState.CURRENT),
        (_risk("approved", "2025-09-30"), AssessmentState.CURRENT),  # exactly 365 days
        (_risk("approved", "2025-09-29"), AssessmentState.EXPIRED),  # 366 days
        (_risk("approved", None), AssessmentState.UNKNOWN),  # the one new behaviour
        (_risk("approved", "2030-01-01"), AssessmentState.CURRENT),  # unchanged: future date is not special-cased
        (_risk("expired", "2025-07-01"), AssessmentState.CONFLICTING),
        (_risk("not_completed", None), AssessmentState.CONFLICTING),
        (_risk(None, None), AssessmentState.MISSING),
        (_risk(available=False), AssessmentState.UNAVAILABLE),
    ],
)
def test_assessment_state_matrix(risk, expected):
    assert evaluate_vendor_security_assessment(REG, risk, REF) is expected


def test_unknown_freshness_is_not_current_and_requires_security():
    request = RequestFields.from_raw(
        dict(request_id="X", requester_id="E1", product_name="P", vendor_name="V", annual_cost_usd=500, user_count=3,
             business_justification="j", data_access_level="none", requested_integrations=[]),
        department="Marketing",
    )
    evaluation = evaluate_policy(PolicyContext(request=request, budget=BudgetEvidence("Marketing", Decimal(100000)), vendor_registry=REG, vendor_risk=_risk("approved", None)))
    assert "Security" in evaluation.required_approvals
    assert "security_review_required" in evaluation.risk_flags
    assert "vendor_review_unverified" in evaluation.risk_flags
    assert any(c.rule_id == "POL-5" and c.status.value == "flagged" and "freshness cannot be verified" in c.detail for c in evaluation.checks)


def test_a_current_vendor_still_needs_no_security():
    request = RequestFields.from_raw(
        dict(request_id="X", requester_id="E1", product_name="P", vendor_name="V", annual_cost_usd=500, user_count=3,
             business_justification="j", data_access_level="none", requested_integrations=[]),
        department="Marketing",
    )
    evaluation = evaluate_policy(PolicyContext(request=request, budget=BudgetEvidence("Marketing", Decimal(100000)), vendor_registry=REG, vendor_risk=_risk("approved", "2026-06-01")))
    assert "Security" not in evaluation.required_approvals


def test_ui_view_model_renders_the_unknown_state_without_crashing():
    from src.ui.view_model import _build_vendor_security

    view = _build_vendor_security(REG, _risk("approved", None))
    assert view.overall_status == "missing"
    assert "review date is missing" in view.action_text
