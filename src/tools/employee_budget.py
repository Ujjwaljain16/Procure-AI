"""Employee / department-budget retrieval tool.

Answers "what does the data say" about a requester and their department's
software budget. Deterministic, local-data-only: no network calls, no LLM,
no policy logic. See ``src/policy_engine.py`` for what the retrieved
``BudgetEvidence`` is used to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src import data_access
from src.contracts import EvidenceItem
from src.policy_engine import BudgetEvidence


def _opt_str(value: object) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class EmployeeRecord:
    employee_id: str
    name: str
    department: str
    manager_id: Optional[str]
    level: Optional[str]
    country: Optional[str]


@dataclass(frozen=True)
class EmployeeBudgetResult:
    employee: Optional[EmployeeRecord]
    budget: Optional[BudgetEvidence]
    evidence: tuple[EvidenceItem, ...]


def get_employee_budget(employee_id: str) -> EmployeeBudgetResult:
    """Look up an employee and their department's available software budget.

    An unknown ``employee_id`` or a department missing from
    ``department_budgets.csv`` is reported as ``None`` — never guessed at or
    defaulted to a favorable value.
    """
    employee_id = (employee_id or "").strip()
    employees = data_access.load_employees()
    match = employees[employees["employee_id"] == employee_id]

    if match.empty:
        return EmployeeBudgetResult(
            employee=None,
            budget=None,
            evidence=(
                EvidenceItem(
                    source="employee_data",
                    finding=f"No employee record found for '{employee_id}'.",
                    reference=f"employees.csv:{employee_id}",
                ),
            ),
        )

    row = match.iloc[0]
    employee = EmployeeRecord(
        employee_id=str(row["employee_id"]),
        name=str(row["name"]),
        department=str(row["department"]),
        manager_id=_opt_str(row.get("manager_id")),
        level=_opt_str(row.get("level")),
        country=_opt_str(row.get("country")),
    )
    evidence = [
        EvidenceItem(
            source="employee_data",
            finding=f"Employee {employee.employee_id} ({employee.name}) belongs to the {employee.department} department.",
            reference=f"employees.csv:{employee.employee_id}",
        )
    ]

    budgets = data_access.load_budgets()
    budget_match = budgets[budgets["department"] == employee.department]
    if budget_match.empty:
        evidence.append(
            EvidenceItem(
                source="budget_data",
                finding=f"No department-budget record found for '{employee.department}'.",
                reference=f"department_budgets.csv:{employee.department}",
            )
        )
        budget = None
    else:
        budget = BudgetEvidence.from_row(budget_match.iloc[0].to_dict())
        evidence.append(
            EvidenceItem(
                source="budget_data",
                finding=f"{employee.department} department has ${budget.available_usd} available software budget.",
                reference=f"department_budgets.csv:{employee.department}",
            )
        )

    return EmployeeBudgetResult(employee=employee, budget=budget, evidence=tuple(evidence))
