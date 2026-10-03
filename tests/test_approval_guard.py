"""The approval-claim guard, measured against a checked-in corpus of
sentences that do and do not claim an approval has already been granted.
Recall on claims must be complete; precision on non-claims must be high.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.validation import _claims_autonomous_approval, _guard_against_autonomous_approval_claims

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "approval_claims.json").read_text(encoding="utf-8"))


def test_every_claim_in_the_corpus_is_flagged():
    missed = [s for s in CORPUS["positive"] if not _claims_autonomous_approval(s)]
    assert not missed, f"missed approval claims: {missed}"


def test_non_claims_are_not_flagged_at_high_precision():
    false_alarms = [s for s in CORPUS["negative"] if _claims_autonomous_approval(s)]
    precision = 1 - len(false_alarms) / len(CORPUS["negative"])
    assert precision >= 0.95, f"false alarms: {false_alarms}"


def test_known_bypass_is_flagged():
    assert _claims_autonomous_approval("Approved by budget owner; requires approval from Finance.")


def test_safe_phrase_in_one_clause_does_not_clear_a_claim_in_another():
    text = "Requires approval from Finance. Procurement has approved the vendor."
    assert _claims_autonomous_approval(text)


def test_guard_appends_a_correction_only_when_needed():
    flagged = _guard_against_autonomous_approval_claims("This purchase has been approved.")
    assert "no approval has actually been granted" in flagged.lower()
    clean = _guard_against_autonomous_approval_claims("Requires approval before purchase.")
    assert clean == "Requires approval before purchase."


@pytest.mark.parametrize("text", ["", "   ", "No claims here."])
def test_empty_or_neutral_text_is_safe(text):
    assert not _claims_autonomous_approval(text)
