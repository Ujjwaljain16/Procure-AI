"""Tests for evaluation/regression.py against hand-built minimal
result/comparison dicts -- both a clean baseline-vs-current match and each
kind of regression it should catch.
"""

from __future__ import annotations

from evaluation.regression import compare, compare_comparisons, compare_results


def _result(passed=25, errored=0, safety_passed=True, latency=100.0, llm=3, tool=3) -> dict:
    return {
        "aggregate": {
            "cases_passed_expected_checks": passed,
            "cases_errored": errored,
            "latency_ms": {"median": latency},
            "llm_calls": {"median": llm},
            "tool_calls": {"median": tool},
        },
        "safety_gate": {"passed": safety_passed},
    }


def _comparison(consistency_failures=0, safety_passed=True) -> dict:
    return {
        "rows": [],
        "deterministic_consistency_failures_total": consistency_failures,
        "safety_gate": {"passed": safety_passed},
        "single_aggregate": {"cases_passed_expected_checks": 25},
        "staged_aggregate": {"cases_passed_expected_checks": 25},
    }


class TestCompareResults:
    def test_identical_runs_pass_with_no_regressions(self):
        report = compare_results(_result(), _result())
        assert report.passed
        assert all(c.status != "REGRESSED" for c in report.comparisons)

    def test_fewer_passing_cases_is_a_regression(self):
        report = compare_results(_result(passed=25), _result(passed=23))
        assert not report.passed
        names = {c.name: c.status for c in report.comparisons}
        assert names["cases_passed_expected_checks"] == "REGRESSED"

    def test_more_errors_is_a_regression(self):
        report = compare_results(_result(errored=0), _result(errored=2))
        assert not report.passed
        names = {c.name: c.status for c in report.comparisons}
        assert names["cases_errored"] == "REGRESSED"

    def test_safety_gate_flipping_to_failed_is_a_regression(self):
        report = compare_results(_result(safety_passed=True), _result(safety_passed=False))
        assert not report.passed
        names = {c.name: c.status for c in report.comparisons}
        assert names["safety_gate_passed"] == "REGRESSED"

    def test_latency_drift_alone_does_not_fail_the_gate(self):
        report = compare_results(_result(latency=100.0), _result(latency=400.0))
        assert report.passed
        names = {c.name: c.status for c in report.comparisons}
        assert names["latency_ms_median"] == "CHANGED"

    def test_more_passing_cases_is_improved_not_regressed(self):
        report = compare_results(_result(passed=23), _result(passed=25))
        names = {c.name: c.status for c in report.comparisons}
        assert names["cases_passed_expected_checks"] == "IMPROVED"
        assert report.passed


class TestCompareComparisons:
    def test_identical_comparisons_pass(self):
        report = compare_comparisons(_comparison(), _comparison())
        assert report.passed

    def test_new_consistency_failures_are_a_regression(self):
        report = compare_comparisons(_comparison(consistency_failures=0), _comparison(consistency_failures=3))
        assert not report.passed
        names = {c.name: c.status for c in report.comparisons}
        assert names["deterministic_consistency_failures_total"] == "REGRESSED"


class TestCompareDispatch:
    def test_dispatches_results_by_default(self):
        report = compare(_result(), _result())
        assert report.kind == "result"

    def test_dispatches_comparisons_when_both_are_comparison_files(self):
        report = compare(_comparison(), _comparison())
        assert report.kind == "comparison"

    def test_raises_on_mismatched_artifact_kinds(self):
        import pytest

        with pytest.raises(ValueError):
            compare(_result(), _comparison())
