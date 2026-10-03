"""Reproducible A-vs-B evaluator over the frozen evaluation/cases.json set.

Usage:
    python evaluation/run_comparison.py                    # both architectures, replay mode
    python evaluation/run_comparison.py --architecture single
    python evaluation/run_comparison.py --architecture staged
    python evaluation/run_comparison.py --real              # use the real Gemini API instead of the replay client

Writes evaluation/results/<architecture>_<timestamp>.json and, when both
architectures are run, evaluation/results/comparison_<timestamp>.json.
Never overwrites a previous run -- each run gets its own timestamped file,
so old runs remain available for reproducibility comparisons.

'policy'-level cases never touch Gemini or the tools; they call
evaluate_policy() directly against a synthetic PolicyContext and are
identical for both architectures by construction (both call the same
function). 'agent'-level cases run the full architecture, using the
deterministic ReplayGeminiClient by default (see evaluation/replay_client.py
for exactly what it does and does not simulate) or the real Gemini API with
--real (spends API quota -- see docs/architecture_comparison.md for the
daily free-tier limit this project has run into).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import data_access
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.agent.gemini_adapter import DEFAULT_MODEL
from src.policy_engine import (
    POLICY_VERSION,
    BudgetEvidence,
    CatalogMatch,
    PolicyContext,
    RequestFields,
    VendorRegistryEvidence,
    VendorRiskAvailability,
    VendorRiskEvidence,
    evaluate_policy,
    to_decimal,
)
from evaluation.replay_client import ReplayGeminiClient
from evaluation.run_invariants import check_run
from evaluation.vendor_source import SOURCE_LABEL, serve_vendor_records_from_data
from evaluation.safety_gate import evaluate_comparison_safety, evaluate_result_safety

CASES_PATH = ROOT / "evaluation" / "cases.json"
RESULTS_DIR = ROOT / "evaluation" / "results"


def _sdk_version() -> Optional[str]:
    try:
        from importlib.metadata import version

        return version("google-genai")
    except Exception:
        return None


def _generation_config(use_real: bool) -> dict:
    from src.agent.gemini_adapter import GENERATION_TEMPERATURE

    return {
        "model": DEFAULT_MODEL,
        "temperature": GENERATION_TEMPERATURE,
        "sdk_version": _sdk_version() if use_real else None,
        "seed": "not supported by this endpoint",
        "vendor_source": SOURCE_LABEL,
    }


def _git_revision() -> Optional[str]:
    """Best-effort short commit hash for the benchmark manifest -- never
    fatal (a shallow clone, a missing git binary, or running outside a repo
    should not stop an evaluation run)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Synthetic PolicyContext construction (for "policy"-level cases)
# ---------------------------------------------------------------------------


def _build_synthetic_context(spec: dict) -> PolicyContext:
    req = spec["request"]
    request_fields = RequestFields.from_raw(req, department=req.get("department"))

    budget = None
    if spec.get("budget_available_usd") is not None:
        budget = BudgetEvidence(department=req.get("department") or "", available_usd=to_decimal(spec["budget_available_usd"]))

    registry = None
    if spec.get("vendor_registry"):
        registry = VendorRegistryEvidence.from_row(spec["vendor_registry"])

    vendor_risk = None
    if spec.get("vendor_risk"):
        vr = spec["vendor_risk"]
        if vr.get("availability") == "unavailable":
            vendor_risk = VendorRiskEvidence.unavailable(vr.get("vendor_name", req.get("vendor_name", "")))
        else:
            vendor_risk = VendorRiskEvidence.from_api_response(req.get("vendor_name", ""), vr)

    overlap = tuple(CatalogMatch.from_row(row) for row in spec.get("catalog_overlap", []))

    return PolicyContext(
        request=request_fields,
        budget=budget,
        catalog_overlap_matches=overlap,
        vendor_registry=registry,
        vendor_risk=vendor_risk,
    )


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------


def _decision_summary(decision, latency_ms: Optional[float] = None) -> dict:
    return {
        "recommendation": decision.recommendation,
        "next_step": decision.next_step,
        "required_approvals": list(decision.required_approvals),
        "risk_flags": list(decision.risk_flags),
        "missing_information": list(decision.missing_information),
        "human_review_required": decision.human_review_required,
        "evidence_count": len(decision.evidence),
        "evidence_sources": [e.source for e in decision.evidence],
        "llm_calls": decision.telemetry.llm_calls if decision.telemetry else None,
        "tool_calls": decision.telemetry.tool_calls if decision.telemetry else None,
        "latency_ms": latency_ms if latency_ms is not None else (decision.telemetry.latency_ms if decision.telemetry else None),
    }


def _run_agent_case(case: dict, architecture: str, use_real: bool, pooled_keys: Optional[list[str]] = None) -> dict:
    request_id = case["request_id"]
    raw = data_access.get_request(request_id)

    if use_real and pooled_keys:
        from evaluation.pooled_client import PooledGeminiClient, PooledStagedGeminiClient

        client = (
            PooledGeminiClient(pooled_keys, DEFAULT_MODEL)
            if architecture == "single"
            else PooledStagedGeminiClient(pooled_keys, DEFAULT_MODEL)
        )
    else:
        client = None if use_real else ReplayGeminiClient(raw)

    start = time.perf_counter()
    if architecture == "single":
        result = run_single_agent_with_trace(request_id, client=client)
    else:
        result = run_staged_agent_with_trace(request_id, client=client)
    latency_ms = (time.perf_counter() - start) * 1000

    summary = _decision_summary(result.decision, latency_ms)
    summary["rationale"] = result.agent_rationale
    if hasattr(result, "analyst_report") and result.analyst_report is not None:
        summary["analyst_report"] = result.analyst_report.model_dump()
    summary["gemini_unavailable_reason"] = result.gemini_unavailable_reason
    summary["invariants"] = {check.name: check.passed for check in check_run(result)}
    return summary


def _run_policy_case(case: dict) -> dict:
    context = _build_synthetic_context(case["synthetic_context"])
    start = time.perf_counter()
    evaluation = evaluate_policy(context)
    latency_ms = (time.perf_counter() - start) * 1000
    return {
        "recommendation": None,
        "next_step": None,
        "required_approvals": list(evaluation.required_approvals),
        "risk_flags": list(evaluation.risk_flags),
        "missing_information": list(evaluation.missing_information),
        "human_review_required": evaluation.human_review_required,
        "evidence_count": None,
        "evidence_sources": [],
        "llm_calls": 0,
        "tool_calls": 0,
        "latency_ms": latency_ms,
    }


def run_case(case: dict, architecture: str, use_real: bool, pooled_keys: Optional[list[str]] = None) -> dict:
    if case["level"] == "policy":
        return _run_policy_case(case)
    return _run_agent_case(case, architecture, use_real, pooled_keys)


# ---------------------------------------------------------------------------
# Deterministic per-case checks
# ---------------------------------------------------------------------------


def check_expected(actual: dict, expected: dict) -> list[str]:
    failures = []
    approvals = set(actual["required_approvals"])
    flags = set(actual["risk_flags"])
    missing = set(actual["missing_information"])

    for item in expected.get("required_approvals_include", []):
        if item not in approvals:
            failures.append(f"missing required approval: {item}")
    for item in expected.get("required_approvals_exclude", []):
        if item in approvals:
            failures.append(f"unexpected required approval: {item}")
    for item in expected.get("risk_flags_include", []):
        if item not in flags:
            failures.append(f"missing risk flag: {item}")
    for item in expected.get("risk_flags_exclude", []):
        if item in flags:
            failures.append(f"unexpected risk flag: {item}")
    for item in expected.get("missing_information_include", []):
        if item not in missing:
            failures.append(f"missing missing-information item: {item}")
    if "human_review_required" in expected:
        if actual["human_review_required"] != expected["human_review_required"]:
            failures.append(
                f"human_review_required mismatch: expected {expected['human_review_required']}, got {actual['human_review_required']}"
            )
    return failures


def check_deterministic_fields_match(a: dict, b: dict) -> list[str]:
    """A-vs-B consistency: both architectures call the identical
    evaluate_policy(); if evidence gathering was equivalent, these four
    fields must match exactly regardless of which architecture ran."""
    diffs = []
    if set(a["required_approvals"]) != set(b["required_approvals"]):
        diffs.append(f"required_approvals differ: single={a['required_approvals']} staged={b['required_approvals']}")
    if set(a["risk_flags"]) != set(b["risk_flags"]):
        diffs.append(f"risk_flags differ: single={a['risk_flags']} staged={b['risk_flags']}")
    if set(a["missing_information"]) != set(b["missing_information"]):
        diffs.append(f"missing_information differ: single={a['missing_information']} staged={b['missing_information']}")
    if a["human_review_required"] != b["human_review_required"]:
        diffs.append("human_review_required differs")
    return diffs


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_architecture(cases: list[dict], architecture: str, use_real: bool, pooled_keys: Optional[list[str]] = None) -> dict:
    per_case = {}
    for case in cases:
        try:
            print(f"  {case['case_id']} ({case['category']})...", flush=True)
            actual = run_case(case, architecture, use_real, pooled_keys)
            failures = check_expected(actual, case["expected"]) if case.get("expected") else []
            per_case[case["case_id"]] = {"actual": actual, "expected_check_failures": failures, "error": None}
        except Exception as exc:
            per_case[case["case_id"]] = {
                "actual": None,
                "expected_check_failures": [f"ERROR: {type(exc).__name__}: {exc}"],
                "error": f"{type(exc).__name__}: {exc}",
            }
    return per_case


def _aggregate(per_case: dict) -> dict:
    latencies = [c["actual"]["latency_ms"] for c in per_case.values() if c["actual"] and c["actual"]["latency_ms"] is not None]
    llm_calls = [c["actual"]["llm_calls"] for c in per_case.values() if c["actual"] and c["actual"]["llm_calls"] is not None]
    tool_calls = [c["actual"]["tool_calls"] for c in per_case.values() if c["actual"] and c["actual"]["tool_calls"] is not None]
    total_cases = len(per_case)
    passed = sum(1 for c in per_case.values() if c["error"] is None and not c["expected_check_failures"])
    errored = sum(1 for c in per_case.values() if c["error"] is not None)

    def _stats(values):
        if not values:
            return {"mean": None, "median": None, "max": None, "p95": None}
        sorted_values = sorted(values)
        p95_index = min(len(sorted_values) - 1, int(round(0.95 * (len(sorted_values) - 1))))
        return {
            "mean": round(statistics.mean(values), 2),
            "median": round(statistics.median(values), 2),
            "max": round(max(values), 2),
            "p95": round(sorted_values[p95_index], 2),
        }

    return {
        "total_cases": total_cases,
        "cases_passed_expected_checks": passed,
        "cases_errored": errored,
        "latency_ms": _stats(latencies),
        "llm_calls": _stats(llm_calls),
        "tool_calls": _stats(tool_calls),
    }


def _check_injection_pairs(cases: list[dict], all_results: dict) -> list[dict]:
    """Cross-case safety check: a case with 'pair_with' must produce
    byte-equivalent deterministic fields to its paired case (a benign vs.
    injected variant of the same otherwise-identical request), for every
    architecture that was run. Compares two cases to each other rather than
    one case to a fixed oracle, so it doesn't fit the per-case expected-check
    mechanism -- returned as its own list (and printed by the caller) so it
    can also be persisted into the comparison JSON and read by the safety
    gate, instead of only ever appearing in stdout.
    """
    by_id = {c["case_id"]: c for c in cases}
    seen = set()
    checks = []
    for case in cases:
        pair_id = case.get("pair_with")
        if not pair_id or case["case_id"] in seen or pair_id in seen:
            continue
        seen.add(case["case_id"])
        seen.add(pair_id)
        if pair_id not in by_id:
            checks.append({"case_id": case["case_id"], "pair_with": pair_id, "architecture": None, "passed": False, "diffs": ["unknown paired case id"]})
            continue
        for architecture, results in all_results.items():
            a = results["per_case"][case["case_id"]]["actual"]
            b = results["per_case"][pair_id]["actual"]
            if a is None or b is None:
                continue
            diffs = check_deterministic_fields_match(a, b)
            checks.append(
                {
                    "case_id": case["case_id"],
                    "pair_with": pair_id,
                    "architecture": architecture,
                    "passed": not diffs,
                    "diffs": diffs,
                }
            )
    return checks


def _print_injection_pair_checks(checks: list[dict]) -> None:
    for check in checks:
        if check["architecture"] is None:
            print(f"WARNING: {check['case_id']} pairs with unknown case {check['pair_with']}")
            continue
        status = "OK" if check["passed"] else "FAIL"
        print(f"Injection pair check [{check['architecture']}] {check['case_id']} vs {check['pair_with']}: {status}")
        for diff in check["diffs"]:
            print(f"  - {diff}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", choices=["single", "staged"], default=None)
    parser.add_argument("--real", action="store_true", help="Use the real Gemini API instead of the deterministic replay client.")
    parser.add_argument(
        "--key-pool",
        action="store_true",
        help="With --real, use several API keys from $GEMINI_API_KEY_POOL (comma-separated), rotating on quota errors.",
    )
    parser.add_argument("--case-ids", default=None, help="Comma-separated case IDs to run instead of the full frozen set (for a small real-API sample).")
    parser.add_argument(
        "--cases-file",
        default=None,
        help="Path to an alternate cases JSON (e.g. evaluation/extended_cases.json). Defaults to the frozen evaluation/cases.json.",
    )
    args = parser.parse_args()

    cases_path = Path(args.cases_file) if args.cases_file else CASES_PATH
    cases_data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = cases_data["cases"]
    if args.case_ids:
        wanted = {c.strip() for c in args.case_ids.split(",")}
        cases = [c for c in cases if c["case_id"] in wanted]
        print(f"Running a {len(cases)}-case sample: {sorted(wanted)}")

    pooled_keys = None
    if args.real and args.key_pool:
        from evaluation.pooled_client import load_key_pool

        pooled_keys = load_key_pool()
        print(f"Using a pool of {len(pooled_keys)} API keys.")

    architectures = [args.architecture] if args.architecture else ["single", "staged"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    git_revision = _git_revision()

    all_results = {}
    for architecture in architectures:
        print(f"\nRunning {len(cases)} cases for architecture={architecture} (mode={'real' if args.real else 'replay'})...")
        with serve_vendor_records_from_data():  # the preflight's vendor lookups must not depend on a running server
            per_case = run_architecture(cases, architecture, args.real, pooled_keys)
        aggregate = _aggregate(per_case)
        output = {
            "timestamp": timestamp,
            "architecture": architecture,
            "mode": "real" if args.real else "replay",
            "model": DEFAULT_MODEL if args.real else None,
            "test_set_version": cases_data["version"],
            "git_revision": git_revision,
            "policy_version": POLICY_VERSION,
            "generation_config": _generation_config(args.real),
            "aggregate": aggregate,
            "per_case": per_case,
        }
        safety_gate = evaluate_result_safety(output)
        output["safety_gate"] = safety_gate.to_dict()
        out_path = RESULTS_DIR / f"{architecture}_{timestamp}.json"
        out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
        print(f"  {aggregate['cases_passed_expected_checks']}/{aggregate['total_cases']} passed expected checks, {aggregate['cases_errored']} errored")
        print(f"  SAFETY GATE: {'PASS' if safety_gate.passed else 'FAIL'} -- {safety_gate.detail}")
        print(f"  wrote {out_path.relative_to(ROOT)}")
        all_results[architecture] = output

    injection_pair_checks = _check_injection_pairs(cases, all_results)
    _print_injection_pair_checks(injection_pair_checks)

    if "single" in all_results and "staged" in all_results:
        comparison_rows = []
        consistency_failures_total = 0
        for case in cases:
            case_id = case["case_id"]
            a = all_results["single"]["per_case"][case_id]
            b = all_results["staged"]["per_case"][case_id]
            consistency_diffs = []
            if a["actual"] and b["actual"]:
                consistency_diffs = check_deterministic_fields_match(a["actual"], b["actual"])
            consistency_failures_total += len(consistency_diffs)
            comparison_rows.append(
                {
                    "case_id": case_id,
                    "category": case["category"],
                    "level": case["level"],
                    "tags": case.get("tags", []),
                    "single_passed": a["error"] is None and not a["expected_check_failures"],
                    "staged_passed": b["error"] is None and not b["expected_check_failures"],
                    "single_failures": a["expected_check_failures"],
                    "staged_failures": b["expected_check_failures"],
                    "deterministic_consistency_diffs": consistency_diffs,
                }
            )
        comparison = {
            "timestamp": timestamp,
            "test_set_version": all_results["single"]["test_set_version"],
            "git_revision": git_revision,
            "policy_version": POLICY_VERSION,
            "generation_config": _generation_config(args.real),
            "single_aggregate": all_results["single"]["aggregate"],
            "staged_aggregate": all_results["staged"]["aggregate"],
            "deterministic_consistency_failures_total": consistency_failures_total,
            "injection_pair_checks": injection_pair_checks,
            "rows": comparison_rows,
        }
        comparison_safety_gate = evaluate_comparison_safety(comparison)
        comparison["safety_gate"] = comparison_safety_gate.to_dict()
        out_path = RESULTS_DIR / f"comparison_{timestamp}.json"
        out_path.write_text(json.dumps(comparison, indent=2, default=str), encoding="utf-8")
        print(f"\nComparison written to {out_path.relative_to(ROOT)}")
        print(f"Deterministic A-vs-B consistency failures: {consistency_failures_total}/{len(cases)} cases")
        print(f"SAFETY GATE: {'PASS' if comparison_safety_gate.passed else 'FAIL'} -- {comparison_safety_gate.detail}")


if __name__ == "__main__":
    main()
