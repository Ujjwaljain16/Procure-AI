"""Smoke tests for evaluation/run_comparison.py and evaluation/replay_client.py
-- not an exhaustive test of every metric, just confirms the evaluator itself
runs correctly against the real frozen dataset without silently breaking.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.replay_client import ReplayGeminiClient
from evaluation.run_comparison import (
    _build_synthetic_context,
    check_deterministic_fields_match,
    check_expected,
    run_case,
)
from src.policy_engine import evaluate_policy

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))["cases"]
EXTENDED_CASES = json.loads((ROOT / "evaluation" / "extended_cases.json").read_text(encoding="utf-8"))["cases"]


class TestCasesFileIsWellFormed:
    def test_at_least_25_cases(self):
        assert len(CASES) >= 25

    def test_every_case_has_a_unique_id(self):
        ids = [c["case_id"] for c in CASES]
        assert len(ids) == len(set(ids))

    def test_every_agent_case_references_a_real_request(self):
        from src import data_access

        real_ids = {r["request_id"] for r in data_access.load_requests()}
        for case in CASES:
            if case["level"] == "agent":
                assert case["request_id"] in real_ids, case["case_id"]

    def test_every_policy_case_has_a_synthetic_context(self):
        for case in CASES:
            if case["level"] == "policy":
                assert "synthetic_context" in case, case["case_id"]

    def test_pair_with_references_resolve(self):
        ids = {c["case_id"] for c in CASES}
        for case in CASES:
            if case.get("pair_with"):
                assert case["pair_with"] in ids, case["case_id"]

    def test_every_case_has_at_least_one_scenario_tag(self):
        for case in CASES:
            assert case.get("tags"), case["case_id"]


class TestExtendedCasesFileIsWellFormed:
    """evaluation/extended_cases.json -- a separate, additional case set that
    never merges into the frozen evaluation/cases.json (2026.09-tc1)."""

    def test_has_its_own_version_distinct_from_the_frozen_set(self):
        frozen_version = json.loads((ROOT / "evaluation" / "cases.json").read_text(encoding="utf-8"))["version"]
        extended_version = json.loads((ROOT / "evaluation" / "extended_cases.json").read_text(encoding="utf-8"))["version"]
        assert extended_version != frozen_version

    def test_case_ids_do_not_collide_with_the_frozen_set(self):
        frozen_ids = {c["case_id"] for c in CASES}
        extended_ids = {c["case_id"] for c in EXTENDED_CASES}
        assert not (frozen_ids & extended_ids)

    def test_every_case_has_a_unique_id(self):
        ids = [c["case_id"] for c in EXTENDED_CASES]
        assert len(ids) == len(set(ids))

    def test_every_case_is_policy_level_with_a_synthetic_context(self):
        for case in EXTENDED_CASES:
            assert case["level"] == "policy", case["case_id"]
            assert "synthetic_context" in case, case["case_id"]

    def test_every_case_has_tags(self):
        for case in EXTENDED_CASES:
            assert case.get("tags"), case["case_id"]

    def test_every_case_matches_its_own_expected_block(self):
        """The real correctness check: build each case's synthetic context,
        run the actual evaluate_policy(), and confirm it matches what the
        case file claims -- not just that the file is shaped correctly."""
        for case in EXTENDED_CASES:
            context = _build_synthetic_context(case["synthetic_context"])
            evaluation = evaluate_policy(context)
            actual = {
                "required_approvals": list(evaluation.required_approvals),
                "risk_flags": list(evaluation.risk_flags),
                "missing_information": list(evaluation.missing_information),
                "human_review_required": evaluation.human_review_required,
            }
            failures = check_expected(actual, case["expected"])
            assert not failures, f"{case['case_id']}: {failures}"


class TestReplayClientDeterminism:
    def test_same_request_produces_the_same_tool_calls(self):
        raw = {"requester_id": "E004", "vendor_name": "SignFlow", "product_name": "SignFlow Add-on"}
        first = ReplayGeminiClient(raw).generate_turn([], [], "")
        second = ReplayGeminiClient(raw).generate_turn([], [], "")
        assert [c.name for c in first.function_calls] == [c.name for c in second.function_calls]


class TestSyntheticContextConstruction:
    def test_threshold_case_builds_a_valid_context(self):
        case = next(c for c in CASES if c["case_id"] == "TC-16a")
        context = _build_synthetic_context(case["synthetic_context"])
        assert context.request.annual_cost_usd is not None
        assert str(context.request.annual_cost_usd) == "1000.00"


class TestRunCaseForEveryFrozenCase:
    def test_every_case_runs_without_raising_for_both_architectures(self, monkeypatch):
        import mock_api.app as mock_api_module
        from fastapi.testclient import TestClient

        # Route the real vendor-risk HTTP client through the FastAPI app
        # in-process (no real network/server needed) so agent-level cases
        # that call get_vendor_evidence work deterministically in tests.
        test_client = TestClient(mock_api_module.app)

        def fake_get_vendor_risk(vendor_name, timeout_seconds=3.0):
            import requests

            response = test_client.get(f"/vendor-risk/{vendor_name}")
            if response.status_code != 200:
                http_error = requests.HTTPError(response=requests.Response())
                http_error.response.status_code = response.status_code
                raise http_error
            return response.json()

        import src.tools.vendor_risk as vendor_risk_tool

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", fake_get_vendor_risk)

        for case in CASES:
            for architecture in ("single", "staged"):
                actual = run_case(case, architecture, use_real=False)
                assert actual["human_review_required"] is True

    def test_check_expected_and_check_deterministic_fields_match_are_pure_functions(self):
        actual = {
            "required_approvals": ["Manager"],
            "risk_flags": [],
            "missing_information": [],
            "human_review_required": True,
        }
        assert check_expected(actual, {"required_approvals_include": ["Manager"]}) == []
        assert check_expected(actual, {"required_approvals_include": ["CFO"]}) != []
        assert check_deterministic_fields_match(actual, actual) == []
