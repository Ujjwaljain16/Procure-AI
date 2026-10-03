"""Regression corpus for the approval guard, from the held-out measurement that justified H1b.

The guard is a text-level tripwire on model prose. It is not a safety control: the structural
boundary (no code path purchases, approves, or modifies budget) is what protects the user.
Known misses and false positives are asserted as xfail so the limitation is recorded, not hidden.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.validation import _claims_autonomous_approval

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "approval_guard_heldout.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sentence", CORPUS["ordinary_clean"])
def test_ordinary_procurement_prose_is_not_flagged(sentence):
    assert not _claims_autonomous_approval(sentence), sentence


@pytest.mark.parametrize("sentence", CORPUS["claims_caught"])
def test_autonomous_approval_phrasings_are_flagged(sentence):
    assert _claims_autonomous_approval(sentence), sentence


@pytest.mark.xfail(strict=True, reason="known false positive: past-tense status mentions of 'approved'")
@pytest.mark.parametrize("sentence", CORPUS["ordinary_known_false_positive"])
def test_known_false_positive_is_documented(sentence):
    assert not _claims_autonomous_approval(sentence)


@pytest.mark.xfail(strict=True, reason="known miss: approval phrasings outside the narrow patterns")
@pytest.mark.parametrize("sentence", CORPUS["claims_known_miss"])
def test_known_miss_is_documented(sentence):
    assert _claims_autonomous_approval(sentence)
