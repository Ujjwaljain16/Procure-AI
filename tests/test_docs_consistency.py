"""Fails the suite if the submission documents drift from the code or the
stored artifacts (see scripts/check_docs.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _checker():
    spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_submission_documents_agree_with_code_and_artifacts():
    problems = _checker().run()
    assert problems == [], problems
