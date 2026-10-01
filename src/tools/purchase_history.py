"""Purchase-history retrieval tool.

Returns historical purchase records verbatim. ``purchase_history.csv``
currently contains only ``"Approved"`` records -- this module faithfully
reflects that rather than inventing rejected/pending semantics the data does
not contain.

Unlike the catalog tool's broad (OR) matching, filters here are combined with
AND: this tool answers narrow questions like "has this department already
purchased from this vendor", where the caller supplies exactly the criteria
that matter and expects a precise match, not broad discovery.

Not currently consumed by the policy engine (no POL-1..11 rule references
purchase history), so it exists purely as supporting evidence for the future
agent/UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import pandas as pd

from src import data_access
from src.contracts import EvidenceItem
from src.policy_engine import to_decimal


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip().lower()


@dataclass(frozen=True)
class PurchaseRecord:
    purchase_id: str
    purchase_date: date
    department: str
    vendor_name: str
    product_name: str
    annual_amount_usd: Decimal
    status: str
    notes: Optional[str]

    @staticmethod
    def from_row(row: dict) -> "PurchaseRecord":
        notes = row.get("notes")
        return PurchaseRecord(
            purchase_id=row["purchase_id"],
            purchase_date=date.fromisoformat(row["purchase_date"]),
            department=row["department"],
            vendor_name=row["vendor_name"],
            product_name=row["product_name"],
            annual_amount_usd=to_decimal(row["annual_amount_usd"]),
            status=row["status"],
            notes=str(notes).strip() if notes is not None and pd.notna(notes) else None,
        )


@dataclass(frozen=True)
class PurchaseHistoryResult:
    records: tuple[PurchaseRecord, ...]
    evidence: tuple[EvidenceItem, ...]


def search_purchase_history(
    *, department: Optional[str] = None, vendor_name: Optional[str] = None, product_name: Optional[str] = None
) -> PurchaseHistoryResult:
    if not any([department, vendor_name, product_name]):
        return PurchaseHistoryResult(
            records=(),
            evidence=(
                EvidenceItem(
                    source="purchase_history",
                    finding="No search criteria supplied; purchase history not searched.",
                    reference="purchase_history.csv",
                ),
            ),
        )

    history = data_access.load_purchase_history()
    mask = pd.Series(True, index=history.index)
    if department:
        mask &= history["department"].str.strip().str.lower() == _normalize(department)
    if vendor_name:
        mask &= history["vendor_name"].str.strip().str.lower() == _normalize(vendor_name)
    if product_name:
        mask &= history["product_name"].str.strip().str.lower() == _normalize(product_name)

    matched_rows = history[mask].sort_values("purchase_id")
    records = tuple(PurchaseRecord.from_row(row.to_dict()) for _, row in matched_rows.iterrows())

    if not records:
        evidence = (
            EvidenceItem(
                source="purchase_history",
                finding="No matching purchase history found for the given criteria.",
                reference="purchase_history.csv",
            ),
        )
    else:
        summary = "; ".join(f"{r.purchase_id}: {r.product_name} (${r.annual_amount_usd}, {r.status})" for r in records)
        evidence = (
            EvidenceItem(
                source="purchase_history",
                finding=f"Matching purchase history: {summary}.",
                reference="purchase_history.csv",
            ),
        )

    return PurchaseHistoryResult(records=records, evidence=evidence)
