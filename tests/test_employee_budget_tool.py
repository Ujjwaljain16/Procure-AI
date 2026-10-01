"""Tests for src/tools/employee_budget.py, against the real starter-pack data."""

from __future__ import annotations

from decimal import Decimal

from src.tools.employee_budget import get_employee_budget


class TestKnownEmployee:
    def test_known_employee_resolves_identity_and_department(self):
        result = get_employee_budget("E004")
        assert result.employee is not None
        assert result.employee.employee_id == "E004"
        assert result.employee.name == "Noah Williams"
        assert result.employee.department == "Finance"

    def test_known_employee_resolves_correct_department_budget(self):
        result = get_employee_budget("E004")
        assert result.budget is not None
        assert result.budget.department == "Finance"
        assert result.budget.available_usd == Decimal("29000")

    def test_evidence_references_the_actual_source_records(self):
        result = get_employee_budget("E004")
        sources = {item.source for item in result.evidence}
        assert sources == {"employee_data", "budget_data"}
        assert any("employees.csv:E004" == item.reference for item in result.evidence)

    def test_manager_and_level_and_country_are_captured(self):
        result = get_employee_budget("E004")
        assert result.employee.manager_id == "E006"
        assert result.employee.level == "IC4"
        assert result.employee.country == "United Kingdom"


class TestUnknownEmployee:
    def test_unknown_employee_returns_no_favorable_data(self):
        result = get_employee_budget("E999")
        assert result.employee is None
        assert result.budget is None

    def test_unknown_employee_is_reported_in_evidence_not_silently_dropped(self):
        result = get_employee_budget("E999")
        assert len(result.evidence) == 1
        assert "E999" in result.evidence[0].finding
        assert result.evidence[0].source == "employee_data"


class TestMissingDepartmentBudget:
    def test_employee_in_department_without_a_budget_record_reports_missing_budget(self):
        # Robert King (E007) is in "Go To Market", which has no row in
        # department_budgets.csv -- a real gap in the starter-pack data.
        result = get_employee_budget("E007")
        assert result.employee is not None
        assert result.employee.department == "Go To Market"
        assert result.budget is None
        assert any("Go To Market" in item.finding and item.source == "budget_data" for item in result.evidence)


class TestMalformedUnderlyingData:
    def test_missing_manager_id_is_reported_as_none_not_nan_or_empty_string(self):
        # Lisa Park (E010) is a VP with no manager_id in employees.csv.
        result = get_employee_budget("E010")
        assert result.employee is not None
        assert result.employee.manager_id is None


class TestDeterminism:
    def test_repeated_lookup_is_stable(self):
        first = get_employee_budget("E004")
        second = get_employee_budget("E004")
        assert first.employee == second.employee
        assert first.budget == second.budget
        assert first.evidence == second.evidence

    def test_input_is_trimmed_but_not_otherwise_altered(self):
        result = get_employee_budget("  E004  ")
        assert result.employee is not None
        assert result.employee.employee_id == "E004"
