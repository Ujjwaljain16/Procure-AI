"""Tests for evaluation/report.py -- checks the renderer produces valid,
self-contained HTML for both a comparison file and a single-architecture
result file, without needing a browser to verify it.
"""

from __future__ import annotations

from evaluation.report import render, render_comparison_html, render_result_html


def _comparison() -> dict:
    return {
        "timestamp": "20260930T090239Z",
        "test_set_version": "2026.09-tc1",
        "git_revision": "abc1234",
        "policy_version": "2026.09",
        "single_aggregate": {"cases_passed_expected_checks": 25, "total_cases": 25, "cases_errored": 0, "llm_calls": {"median": 3}, "tool_calls": {"median": 3}, "latency_ms": {"median": 0}},
        "staged_aggregate": {"cases_passed_expected_checks": 25, "total_cases": 25, "cases_errored": 0, "llm_calls": {"median": 4}, "tool_calls": {"median": 3}, "latency_ms": {"median": 0}},
        "deterministic_consistency_failures_total": 0,
        "safety_gate": {"passed": True, "detail": "0 deterministic-field mismatches."},
        "rows": [
            {"case_id": "TC-01", "category": "normal_low_cost", "tags": ["normal_path", "privacy_threshold"], "single_passed": True, "staged_passed": True, "deterministic_consistency_diffs": []},
            {"case_id": "TC-10", "category": "expired_and_conflicting_vendor", "tags": ["vendor_conflict"], "single_passed": True, "staged_passed": False, "deterministic_consistency_diffs": ["risk_flags differ"]},
        ],
        "injection_pair_checks": [
            {"case_id": "TC-18a", "pair_with": "TC-18b", "architecture": "single", "passed": True, "diffs": []},
        ],
    }


def _result() -> dict:
    return {
        "timestamp": "20260930T090239Z",
        "architecture": "single",
        "mode": "replay",
        "test_set_version": "2026.09-tc1",
        "git_revision": "abc1234",
        "policy_version": "2026.09",
        "aggregate": {"cases_passed_expected_checks": 25, "total_cases": 25, "cases_errored": 0, "llm_calls": {"median": 3}, "tool_calls": {"median": 3}, "latency_ms": {"median": 0}},
        "safety_gate": {"passed": True, "detail": "All invariants held."},
    }


class TestRenderComparisonHtml:
    def test_contains_the_doctype_and_closing_tags(self):
        out = render_comparison_html(_comparison())
        assert out.startswith("<!doctype html>")
        assert "</html>" in out

    def test_contains_the_safety_gate_verdict(self):
        out = render_comparison_html(_comparison())
        assert "SAFETY GATE: PASS" in out

    def test_shows_fail_gate_when_not_passed(self):
        comparison = _comparison()
        comparison["safety_gate"]["passed"] = False
        out = render_comparison_html(comparison)
        assert "SAFETY GATE: FAIL" in out
        assert 'class="gate fail"' in out

    def test_includes_every_case_row(self):
        out = render_comparison_html(_comparison())
        assert "TC-01" in out
        assert "TC-10" in out

    def test_escapes_html_in_category_text(self):
        comparison = _comparison()
        comparison["rows"][0]["category"] = "<script>alert(1)</script>"
        out = render_comparison_html(comparison)
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_includes_injection_pair_section_when_present(self):
        out = render_comparison_html(_comparison())
        assert "Injection Pair Checks" in out

    def test_omits_injection_pair_section_when_absent(self):
        comparison = _comparison()
        del comparison["injection_pair_checks"]
        out = render_comparison_html(comparison)
        assert "Injection Pair Checks" not in out


class TestRenderResultHtml:
    def test_renders_without_a_rows_key(self):
        out = render_result_html(_result())
        assert out.startswith("<!doctype html>")
        assert "SAFETY GATE: PASS" in out


class TestRenderDispatch:
    def test_dispatches_comparison_files_to_the_comparison_renderer(self):
        assert "Per-Case Results" in render(_comparison())

    def test_dispatches_result_files_to_the_result_renderer(self):
        assert "Per-Case Results" not in render(_result())
