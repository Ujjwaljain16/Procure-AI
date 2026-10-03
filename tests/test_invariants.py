"""Gate-level invariants over stored results: the recorded per-run checks must
gate the verdict, and the stored text must not carry an approval claim."""

from __future__ import annotations

from evaluation.invariants import (
    check_recorded_run_invariants,
    check_stored_text_has_no_approval_claim,
    run_invariants,
)


def _result(per_case: dict) -> dict:
    return {"per_case": per_case}


def _actual(**overrides) -> dict:
    base = {
        "recommendation": "Route to the Manager for sign-off.",
        "next_step": "Requires approval before proceeding.",
        "invariants": {"approvals_follow_policy": True, "human_review_required": True},
    }
    base.update(overrides)
    return base


class TestRecordedRunInvariants:
    def test_passes_when_every_recorded_check_held(self):
        assert check_recorded_run_invariants(_result({"TC-01": {"actual": _actual()}})).passed

    def test_fails_when_any_recorded_check_failed(self):
        bad = _actual(invariants={"approvals_follow_policy": False, "human_review_required": True})
        outcome = check_recorded_run_invariants(_result({"TC-01": {"actual": bad}}))
        assert not outcome.passed
        assert "TC-01" in outcome.detail and "approvals_follow_policy" in outcome.detail

    def test_fails_loudly_when_no_run_records_exist(self):
        outcome = check_recorded_run_invariants(_result({"TC-16a": {"actual": {"recommendation": None}}}))
        assert not outcome.passed


class TestStoredTextHasNoApprovalClaim:
    def test_passes_on_ordinary_text(self):
        assert check_stored_text_has_no_approval_claim(_result({"TC-01": {"actual": _actual()}})).passed

    def test_fails_on_a_stored_approval_claim(self):
        bad = _actual(recommendation="This purchase has been approved.")
        outcome = check_stored_text_has_no_approval_claim(_result({"TC-01": {"actual": bad}}))
        assert not outcome.passed
        assert "TC-01.recommendation" in outcome.detail


class TestRunInvariants:
    def test_runs_every_gate_invariant_and_names_its_enforcer(self):
        results = run_invariants(_result({"TC-01": {"actual": _actual()}}))
        assert len(results) == 2
        assert all(r.enforced_by for r in results)
