"""Ordinary procurement sentences (statuses, directives to humans, facts) must not be flagged as
approval claims. Guards against the guard growing false positives as phrasings are added."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.validation import _claims_autonomous_approval

ORDINARY = json.loads((Path(__file__).parent / "fixtures" / "ordinary_procurement_sentences.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sentence", ORDINARY)
def test_ordinary_sentence_is_not_flagged(sentence):
    assert not _claims_autonomous_approval(sentence), sentence


@pytest.mark.parametrize(
    "sentence",
    ["I approve.", "I hereby approve this request.", "No approval is needed for this purchase.", "This does not require approval.", "Approval isn't required."],
)
def test_first_person_and_explicit_no_approval_needed_statements_are_flagged(sentence):
    assert _claims_autonomous_approval(sentence)


@pytest.mark.parametrize(
    "sentence",
    ["Do not skip approval; approval is not optional.", "Approval is not needed until Finance confirms the budget.", "Whether approval is needed depends on the cost."],
)
def test_conditional_or_neutral_mentions_are_not_flagged(sentence):
    assert not _claims_autonomous_approval(sentence)
