"""Deterministic procurement evidence-retrieval tools.

Each tool answers "what does the data say", returning structured facts plus
``EvidenceItem`` provenance records. None of them make policy decisions --
that is ``src/policy_engine.py`` -- and none of them call an LLM -- that is
the future agent layer.
"""

from src.tools.catalog import CatalogCandidate, CatalogSearchResult, search_catalog
from src.tools.employee_budget import EmployeeBudgetResult, EmployeeRecord, get_employee_budget
from src.tools.purchase_history import PurchaseHistoryResult, PurchaseRecord, search_purchase_history
from src.tools.vendor_risk import VendorEvidenceResult, get_vendor_evidence

__all__ = [
    "CatalogCandidate",
    "CatalogSearchResult",
    "search_catalog",
    "EmployeeBudgetResult",
    "EmployeeRecord",
    "get_employee_budget",
    "PurchaseHistoryResult",
    "PurchaseRecord",
    "search_purchase_history",
    "VendorEvidenceResult",
    "get_vendor_evidence",
]
