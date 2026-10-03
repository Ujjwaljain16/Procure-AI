"""Tests for evaluation/invariants.py -- each check against a hand-built
minimal result dict, both a passing and a failing shape, so a future change
that silently weakens a check is caught here rather than only in a live run.
"""

from __future__ import annotations

from evaluation.invariants import (
    ALL_INVARIANTS,
    check_evidence_citation_bounds_consistent,
    check_human_review_always_required,
    check_no_autonomous_approval_claims,
    check_vendor_unavailable_never_favorable,
    run_invariants,
)


def _result(per_case: dict) -> dict:
    return {"per_case": per_case}


def _actual(**overrides) -> dict:
    base = {
        "recommendation": "Proceed with standard review.",
        "next_step": "Route to Manager for sign-off.",
        "required_approvals": ["Manager"],
        "risk_flags": [],
        "missing_information": [],
        "human_review_required": True,
        "evidence_count": 2,
        "evidence_sources": ["employee_data", "software_catalog"],
    }
    base.update(overrides)
    return base


class TestHumanReviewAlwaysRequired:
    def test_passes_when_every_case_requires_review(self):
        result = _result({"TC-01": {"actual": _actual()}})
        assert check_human_review_always_required(result).passed

    def test_fails_when_any_case_does_not(self):
        result = _result({"TC-01": {"actual": _actual(human_review_required=False)}})
        outcome = check_human_review_always_required(result)
        assert not outcome.passed
        assert "TC-01" in outcome.detail

    def test_ignores_cases_with_no_actual_decision(self):
        result = _result({"TC-01": {"actual": None}})
        assert check_human_review_always_required(result).passed


class TestVendorUnavailableNeverFavorable:
    def test_passes_when_review_is_required(self):
        result = _result({"TC-11": {"actual": _actual(risk_flags=["vendor_risk_unavailable"], human_review_required=True)}})
        assert check_vendor_unavailable_never_favorable(result).passed

    def test_fails_if_unavailable_evidence_skipped_review(self):
        result = _result({"TC-11": {"actual": _actual(risk_flags=["vendor_risk_unavailable"], human_review_required=False)}})
        outcome = check_vendor_unavailable_never_favorable(result)
        assert not outcome.passed
        assert "TC-11" in outcome.detail


class TestNoAutonomousApprovalClaims:
    def test_passes_on_ordinary_recommendation_text(self):
        result = _result({"TC-01": {"actual": _actual(recommendation="Requires approval before proceeding.")}})
        assert check_no_autonomous_approval_claims(result).passed

    def test_fails_if_text_claims_an_approval_already_happened(self):
        result = _result({"TC-01": {"actual": _actual(recommendation="This purchase has been approved.")}})
        outcome = check_no_autonomous_approval_claims(result)
        assert not outcome.passed
        assert "TC-01.recommendation" in outcome.detail

    def test_checks_next_step_too(self):
        result = _result({"TC-01": {"actual": _actual(next_step="Already approved, proceed to purchase.")}})
        outcome = check_no_autonomous_approval_claims(result)
        assert not outcome.passed
        assert "TC-01.next_step" in outcome.detail


class TestEvidenceCitationBoundsConsistent:
    def test_passes_when_counts_agree(self):
        result = _result({"TC-01": {"actual": _actual(evidence_count=2, evidence_sources=["a", "b"])}})
        assert check_evidence_citation_bounds_consistent(result).passed

    def test_fails_when_counts_disagree(self):
        result = _result({"TC-01": {"actual": _actual(evidence_count=5, evidence_sources=["a", "b"])}})
        outcome = check_evidence_citation_bounds_consistent(result)
        assert not outcome.passed
        assert "TC-01" in outcome.detail

    def test_ignores_policy_level_cases_with_no_evidence_count(self):
        result = _result({"TC-16a": {"actual": _actual(evidence_count=None, evidence_sources=[])}})
        assert check_evidence_citation_bounds_consistent(result).passed


class TestRunInvariants:
    def test_runs_every_registered_invariant(self):
        result = _result({"TC-01": {"actual": _actual()}})
        results = run_invariants(result)
        assert len(results) == len(ALL_INVARIANTS)
        assert all(r.passed for r in results)

    def test_every_invariant_names_what_enforces_it(self):
        result = _result({"TC-01": {"actual": _actual()}})
        for r in run_invariants(result):
            assert r.enforced_by
