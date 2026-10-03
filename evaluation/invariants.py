"""Gate-level invariants over a stored result file.

The live checks run inside each run (evaluation/run_invariants.py) and are
recorded per case as ``actual["invariants"]``. This module turns those records
into the gate verdict, and re-checks the one property that can be read from
the stored summary alone: a recorded approval-claim check must agree with the
guard applied to the stored text.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.validation import _claims_autonomous_approval  # noqa: E402


@dataclass(frozen=True)
class InvariantResult:
    name: str
    passed: bool
    detail: str
    enforced_by: str


def _iter_actuals(result: dict) -> Iterator[tuple[str, dict]]:
    for case_id, record in result.get("per_case", {}).items():
        actual = record.get("actual")
        if actual is not None:
            yield case_id, actual


def check_recorded_run_invariants(result: dict) -> InvariantResult:
    offenders = []
    checked = 0
    for case_id, actual in _iter_actuals(result):
        recorded = actual.get("invariants")
        if recorded is None:
            continue
        checked += 1
        failed = [name for name, passed in recorded.items() if not passed]
        if failed:
            offenders.append(f"{case_id}: {', '.join(failed)}")
    if checked == 0:
        return InvariantResult("recorded_run_invariants_held", False, "no per-run invariant records in this result", "evaluation/run_invariants.py")
    return InvariantResult(
        "recorded_run_invariants_held",
        not offenders,
        f"all per-run invariants held across {checked} cases" if not offenders else "; ".join(offenders),
        "evaluation/run_invariants.py::RUN_CHECKS",
    )


def check_stored_text_has_no_approval_claim(result: dict) -> InvariantResult:
    offenders = []
    for case_id, actual in _iter_actuals(result):
        for field in ("recommendation", "next_step"):
            text = actual.get(field)
            if text and _claims_autonomous_approval(text):
                offenders.append(f"{case_id}.{field}")
    return InvariantResult(
        "stored_text_has_no_approval_claim",
        not offenders,
        "no stored recommendation or next step claims an approval" if not offenders else f"claim in: {', '.join(offenders)}",
        "src/agent/validation.py::_claims_autonomous_approval",
    )


ALL_INVARIANTS: tuple[Callable[[dict], InvariantResult], ...] = (
    check_recorded_run_invariants,
    check_stored_text_has_no_approval_claim,
)


def run_invariants(result: dict) -> list[InvariantResult]:
    return [check(result) for check in ALL_INVARIANTS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run recorded safety/correctness invariants over a stored evaluation result.")
    parser.add_argument("result_file")
    args = parser.parse_args()
    results = run_invariants(json.loads(Path(args.result_file).read_text(encoding="utf-8")))
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.detail}")
    if any(not r.passed for r in results):
        raise SystemExit(1)
    print("\nAll invariants held.")


if __name__ == "__main__":
    main()
