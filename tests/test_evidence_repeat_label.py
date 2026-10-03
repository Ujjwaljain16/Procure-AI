"""A repeated lookup is labelled in the evidence view, and every evidence ID is kept."""

from __future__ import annotations

from dataclasses import dataclass

from src.ui.view_model import _build_evidence


@dataclass(frozen=True)
class _Item:
    source: str
    finding: str
    reference: str | None


def test_a_repeated_fact_points_to_its_first_id_and_keeps_its_own_id():
    budget = _Item("budget_data", "Engineering has $26000 available.", "department_budgets.csv:Engineering")
    registry = _Item("vendor_registry", "CodeMate approved.", "vendors.csv:CodeMate")
    index = (("E1", budget), ("E2", registry), ("E3", budget), ("E4", registry))

    views = _build_evidence(index)

    assert [v.evidence_id for v in views] == ["E1", "E2", "E3", "E4"]
    assert [v.repeat_of for v in views] == [None, None, "E1", "E2"]


def test_the_same_finding_from_a_different_source_is_not_a_repeat():
    first = _Item("vendor_registry", "Approved.", "vendors.csv:CodeMate")
    second = _Item("vendor_risk_service", "Approved.", "vendors.csv:CodeMate")

    views = _build_evidence((("E1", first), ("E2", second)))

    assert [v.repeat_of for v in views] == [None, None]


def test_no_evidence_gives_an_empty_view():
    assert _build_evidence(()) == ()
