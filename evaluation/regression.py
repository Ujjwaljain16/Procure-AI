"""Regression mode: diffs two stored evaluation results (a saved baseline and
a current run of the same kind -- both single-architecture result files, or
both comparison files) and reports PASS/REGRESSED per metric.

This is what makes the harness useful *after* the A-vs-B ship decision, not
just for making it: if Architecture A is ever touched in a future phase (a
bug fix, a prompt tweak), this is what should catch an unintended behavior
change, instead of only a manual re-read of the numbers.

Usage:
    python evaluation/regression.py --baseline evaluation/results/single_<old>.json --current evaluation/results/single_<new>.json
    python evaluation/regression.py --baseline evaluation/results/comparison_<old>.json --current evaluation/results/comparison_<new>.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class MetricComparison:
    name: str
    baseline_value: object
    current_value: object
    status: str  # "SAME" | "IMPROVED" | "REGRESSED" | "CHANGED" (informational, not a regression)


@dataclass(frozen=True)
class RegressionReport:
    passed: bool
    kind: str  # "result" | "comparison"
    comparisons: tuple[MetricComparison, ...]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "kind": self.kind,
            "metrics": [
                {"name": c.name, "baseline": c.baseline_value, "current": c.current_value, "status": c.status} for c in self.comparisons
            ],
        }


def _is_comparison_file(data: dict) -> bool:
    return "rows" in data and "deterministic_consistency_failures_total" in data


def _hard_metric(name: str, baseline, current, higher_is_better: bool) -> MetricComparison:
    if baseline is None or current is None:
        return MetricComparison(name, baseline, current, "CHANGED")
    if current == baseline:
        return MetricComparison(name, baseline, current, "SAME")
    improved = (current > baseline) if higher_is_better else (current < baseline)
    return MetricComparison(name, baseline, current, "IMPROVED" if improved else "REGRESSED")


def _informational_metric(name: str, baseline, current) -> MetricComparison:
    """For metrics like latency/LLM-calls where natural variation (especially
    in --real mode, against a live API) is expected and not itself a
    regression -- reported for visibility, never fails the gate on its own.
    """
    status = "SAME" if baseline == current else "CHANGED"
    return MetricComparison(name, baseline, current, status)


def compare_results(baseline: dict, current: dict) -> RegressionReport:
    """Diffs two single-architecture result files."""
    b_agg = baseline.get("aggregate", {})
    c_agg = current.get("aggregate", {})

    comparisons = [
        _hard_metric("cases_passed_expected_checks", b_agg.get("cases_passed_expected_checks"), c_agg.get("cases_passed_expected_checks"), higher_is_better=True),
        _hard_metric("cases_errored", b_agg.get("cases_errored"), c_agg.get("cases_errored"), higher_is_better=False),
        _hard_metric("safety_gate_passed", baseline.get("safety_gate", {}).get("passed"), current.get("safety_gate", {}).get("passed"), higher_is_better=True),
        _informational_metric("latency_ms_median", b_agg.get("latency_ms", {}).get("median"), c_agg.get("latency_ms", {}).get("median")),
        _informational_metric("llm_calls_median", b_agg.get("llm_calls", {}).get("median"), c_agg.get("llm_calls", {}).get("median")),
        _informational_metric("tool_calls_median", b_agg.get("tool_calls", {}).get("median"), c_agg.get("tool_calls", {}).get("median")),
    ]
    passed = not any(c.status == "REGRESSED" for c in comparisons)
    return RegressionReport(passed=passed, kind="result", comparisons=tuple(comparisons))


def compare_comparisons(baseline: dict, current: dict) -> RegressionReport:
    """Diffs two comparison (A-vs-B) files."""
    comparisons = [
        _hard_metric(
            "deterministic_consistency_failures_total",
            baseline.get("deterministic_consistency_failures_total"),
            current.get("deterministic_consistency_failures_total"),
            higher_is_better=False,
        ),
        _hard_metric("safety_gate_passed", baseline.get("safety_gate", {}).get("passed"), current.get("safety_gate", {}).get("passed"), higher_is_better=True),
        _informational_metric(
            "single_cases_passed_expected_checks",
            baseline.get("single_aggregate", {}).get("cases_passed_expected_checks"),
            current.get("single_aggregate", {}).get("cases_passed_expected_checks"),
        ),
        _informational_metric(
            "staged_cases_passed_expected_checks",
            baseline.get("staged_aggregate", {}).get("cases_passed_expected_checks"),
            current.get("staged_aggregate", {}).get("cases_passed_expected_checks"),
        ),
    ]
    passed = not any(c.status == "REGRESSED" for c in comparisons)
    return RegressionReport(passed=passed, kind="comparison", comparisons=tuple(comparisons))


def compare(baseline: dict, current: dict) -> RegressionReport:
    b_is_comparison = _is_comparison_file(baseline)
    c_is_comparison = _is_comparison_file(current)
    if b_is_comparison != c_is_comparison:
        raise ValueError("baseline and current must be the same kind of artifact (both result files or both comparison files)")
    return compare_comparisons(baseline, current) if b_is_comparison else compare_results(baseline, current)


def main() -> None:
    parser = argparse.ArgumentParser(description="Diff a current evaluation run against a saved baseline and report PASS/REGRESSED per metric.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    report = compare(baseline, current)

    for c in report.comparisons:
        print(f"[{c.status}] {c.name}: baseline={c.baseline_value} current={c.current_value}")

    print(f"\nREGRESSION CHECK: {'PASS' if report.passed else 'FAIL'}")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
