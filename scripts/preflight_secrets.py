"""Fails if a Gemini-style API key appears in any file this repository would
publish. Scans everything not ignored by git, including new untracked files,
so a key cannot reach a commit or a zip unnoticed. Prints file names and line
numbers only, never the matched value."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")
SKIP_SUFFIXES = {".pyc", ".jpg", ".jpeg", ".png", ".gif", ".ico", ".pdf", ".zip", ".db"}


def candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line and Path(line).suffix.lower() not in SKIP_SUFFIXES]


def main() -> int:
    hits = []
    for path in candidate_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if KEY_PATTERN.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}")
    if hits:
        print("API key-shaped strings found (values not printed):")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print("secrets preflight: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
