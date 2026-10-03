"""Checks that the submission documents agree with the code and the stored
evaluation artifacts. Fails loudly on the first class of drift it finds, so a
contradictory sentence cannot survive a commit unnoticed."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REQUIRED = [
    "README.md",
    "docs/architecture.md",
    "docs/workflow.md",
    "docs/final_evaluation.md",
    "docs/architecture_decision.md",
]
DOCS = [ROOT / p for p in REQUIRED]
STALE_PHRASES = [r"not yet run", r"not run\b", r"not yet available", r"REAL API EVALUATION: not run"]
FORBIDDEN_CLAIMS = [r"\+68%", r"0 safety violations (?:in|for) (?:the )?real"]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def latest(prefix: str) -> dict | None:
    files = sorted((ROOT / "evaluation" / "results").glob(f"{prefix}_*.json"))
    return json.loads(read(files[-1])) if files else None


def collected_test_count() -> int:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True).stdout
    match = re.search(r"(\d+) tests? collected", out)
    return int(match.group(1)) if match else -1


def run() -> list[str]:
    problems: list[str] = []

    for path in DOCS:
        if not path.exists():
            problems.append(f"missing required file: {path.relative_to(ROOT)}")
    if problems:
        return problems

    from src.policy_engine import POLICY_VERSION
    from src.agent.gemini_adapter import DEFAULT_MODEL

    texts = {p.relative_to(ROOT).as_posix(): read(p) for p in DOCS}

    memo_words = len(read(ROOT / "docs/architecture_decision.md").split())
    if memo_words > 500:
        problems.append(f"decision memo is {memo_words} words (limit 500)")

    for name, text in texts.items():
        for phrase in STALE_PHRASES:
            if re.search(phrase, text, re.IGNORECASE):
                problems.append(f"{name}: stale status phrase matches /{phrase}/")
        for claim in FORBIDDEN_CLAIMS:
            if re.search(claim, text):
                problems.append(f"{name}: unsupported claim matches /{claim}/")
        if POLICY_VERSION not in text and name in ("README.md", "docs/final_evaluation.md"):
            problems.append(f"{name}: policy version {POLICY_VERSION} not stated")

    if not re.search(r"Ship Architecture A", texts["docs/architecture_decision.md"]):
        problems.append("architecture_decision.md does not state the shipped decision")
    if DEFAULT_MODEL not in texts["README.md"] and "gemini-2.5-flash" not in texts["README.md"]:
        problems.append("README does not name the model used")

    readme_counts = {int(n) for n in re.findall(r"(\d+) tests\b", texts["README.md"])}
    actual = collected_test_count()
    if actual > 0 and readme_counts and readme_counts - {actual}:
        problems.append(f"README test counts {sorted(readme_counts)} disagree with collected {actual}")

    replay = latest("comparison")
    if replay is None:
        problems.append("no replay comparison artifact exists")
    else:
        single = replay["single_aggregate"]["cases_passed_expected_checks"]
        total = replay["single_aggregate"]["total_cases"]
        if f"{single}/{total}" not in texts["README.md"] and f"{single}/{total}" not in texts["docs/final_evaluation.md"]:
            problems.append(f"docs never state the replay pass count {single}/{total} from the latest artifact")

    return problems


def main() -> int:
    problems = run()
    if problems:
        print("documentation drift found:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("documentation checks: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
