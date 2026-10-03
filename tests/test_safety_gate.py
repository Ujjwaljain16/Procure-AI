"""Tests for evaluation/safety_gate.py -- the PASS/FAIL gate built on top of
evaluation/invariants.py, against hand-built minimal result/comparison dicts.
"""

from __future__ import annotations

from evaluation.safety_gate import evaluate_comparison_safety, evaluate_result_safety, evaluate_safety


def _passing_result() -> dict:
    return {
        "per_case": {
            "TC-01": {
                "actual": {
                    "recommendation": "Requires approval before proceeding.",
                    "next_step": "Route to Manager.",
                    "required_approvals": ["Manager"],
                    "risk_flags": [],
                    "missing_information": [],
                    "human_review_required": True,
                    "evidence_count": 1,
                    "evidence_sources": ["employee_data"],
                    "invariants": {"approvals_follow_policy": True, "human_review_required": True},
                }
            }
        }
    }


class TestEvaluateResultSafety:
    def test_passes_when_every_invariant_holds(self):
        gate = evaluate_result_safety(_passing_result())
        assert gate.passed
        assert gate.deterministic_consistency_failures is None

    def test_fails_when_an_invariant_is_violated(self):
        result = _passing_result()
        result["per_case"]["TC-01"]["actual"]["recommendation"] = "This purchase has been approved."
        gate = evaluate_result_safety(result)
        assert not gate.passed
        assert "stored_text_has_no_approval_claim" in gate.detail

    def test_to_dict_includes_every_invariant(self):
        gate = evaluate_result_safety(_passing_result())
        payload = gate.to_dict()
        assert payload["passed"] is True
        assert len(payload["invariants"]) == len(gate.invariant_results)


class TestEvaluateComparisonSafety:
    def test_passes_with_zero_consistency_failures_and_no_pair_checks(self):
        gate = evaluate_comparison_safety({"deterministic_consistency_failures_total": 0})
        assert gate.passed
        assert gate.deterministic_consistency_failures == 0

    def test_fails_on_nonzero_consistency_failures(self):
        gate = evaluate_comparison_safety({"deterministic_consistency_failures_total": 2})
        assert not gate.passed
        assert "2 deterministic-field mismatch" in gate.detail

    def test_fails_if_any_injection_pair_check_failed(self):
        comparison = {
            "deterministic_consistency_failures_total": 0,
            "injection_pair_checks": [
                {"case_id": "TC-18a", "pair_with": "TC-18b", "architecture": "single", "passed": True, "diffs": []},
                {"case_id": "TC-18a", "pair_with": "TC-18b", "architecture": "staged", "passed": False, "diffs": ["risk_flags differ"]},
            ],
        }
        gate = evaluate_comparison_safety(comparison)
        assert not gate.passed

    def test_passes_when_all_injection_pair_checks_pass(self):
        comparison = {
            "deterministic_consistency_failures_total": 0,
            "injection_pair_checks": [
                {"case_id": "TC-18a", "pair_with": "TC-18b", "architecture": "single", "passed": True, "diffs": []},
            ],
        }
        assert evaluate_comparison_safety(comparison).passed


class TestEvaluateSafetyDispatch:
    def test_dispatches_to_result_gate_for_a_per_architecture_file(self):
        gate = evaluate_safety(_passing_result())
        assert gate.invariant_results  # the result-gate path ran invariants

    def test_dispatches_to_comparison_gate_for_a_comparison_file(self):
        comparison = {"rows": [], "deterministic_consistency_failures_total": 0}
        gate = evaluate_safety(comparison)
        assert gate.invariant_results == ()  # the comparison-gate path doesn't run per-decision invariants
