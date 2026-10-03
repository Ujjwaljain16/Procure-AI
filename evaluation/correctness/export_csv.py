"""Export a correctness result JSON as one CSV row per case and architecture.

The columns follow the submission template (templates/evaluation_results_template.csv):

    case_id, architecture, correct_next_action, grounded_evidence, policy_followed,
    human_escalation_correct, latency_ms, llm_calls, tool_calls, notes

Mapping from the correctness dimensions (normal mode only):
    correct_next_action      d02_next_action
    grounded_evidence        d03_evidence_grounding
    policy_followed          d04 to d07 (policy rules, approvals, missing information, risk flags)
    human_escalation_correct d08_human_review
    llm_calls                logical LLM calls the orchestrator made (not HTTP attempts)
    tool_calls               tool calls made, including model-requested supplemental lookups
    notes                    dimensions that did not pass for that row

Usage:
    python evaluation/correctness/export_csv.py evaluation/correctness/results/<file>.json
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

COLUMNS = [
    "case_id",
    "architecture",
    "correct_next_action",
    "grounded_evidence",
    "policy_followed",
    "human_escalation_correct",
    "latency_ms",
    "llm_calls",
    "tool_calls",
    "notes",
]
POLICY_DIMENSIONS = ("d04_policy_rules", "d05_approvals", "d06_missing_information", "d07_risk_flags")


def export(result_path: Path) -> Path:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    out_path = result_path.with_suffix(".csv")
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in payload["rows"]:
            if row["mode"] != "normal":
                continue
            dims = row["dimensions"]
            actual = row["actual"]
            failed = sorted(name for name, passed in dims.items() if passed is False)
            writer.writerow(
                {
                    "case_id": row["case_id"],
                    "architecture": row["architecture"],
                    "correct_next_action": str(dims["d02_next_action"]).lower(),
                    "grounded_evidence": str(dims["d03_evidence_grounding"]).lower(),
                    "policy_followed": str(all(dims[d] for d in POLICY_DIMENSIONS)).lower(),
                    "human_escalation_correct": str(dims["d08_human_review"]).lower(),
                    "latency_ms": round(actual["latency_ms"]),
                    "llm_calls": actual["logical_llm_calls"],
                    "tool_calls": actual["tool_calls"],
                    "notes": "; ".join(failed),
                }
            )
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    print(f"wrote {export(Path(argv[1]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
