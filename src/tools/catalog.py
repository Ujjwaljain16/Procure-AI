"""Software catalog / overlap retrieval tool.

Finds existing catalog entries that plausibly overlap a new request. This is
purely a retrieval fact ("these catalog entries match by product, vendor, or
category") -- whether an overlap is an actual credible substitute for the
requested use case is left to the future agent and, for policy purposes, to
POL-3 in the policy engine. This module never makes that judgment call.

Matching is deterministic keyword/field matching, not semantic understanding:
any of product name, vendor name, or category may be supplied, and a catalog
row matches if it agrees (case/whitespace-insensitively) with *any* supplied
criterion -- broad recall on purpose, since missing a real overlap is worse
than surfacing one for the agent/policy layer to dismiss as not a credible
substitute.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pandas as pd

from src import data_access
from src.contracts import EvidenceItem
from src.policy_engine import CatalogMatch, to_decimal


def _squash(value: object) -> str:
    """Retrieval normalization: lower-case and drop every non-alphanumeric character, so
    'E-signature', 'e signature' and 'esignature' compare equal. Equality only -- never
    containment or similarity.

    A blank value (None, or the NaN pandas uses for an empty CSV cell) normalizes to "" -- never to the
    text "nan"/"none", which a query could then match."""
    if value is None or pd.isna(value):
        return ""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip().lower()


@dataclass(frozen=True)
class CatalogCandidate:
    """A matched catalog row, carrying both the minimal ``CatalogMatch`` the
    policy engine consumes and the raw fields (cost, scope, notes) a future
    agent or UI needs but the policy engine does not. ``status`` and
    ``notes`` are preserved verbatim -- e.g. NeuralDesk's
    ``"Approved - limited use"`` is never collapsed to a plain ``"Approved"``.
    """

    match: CatalogMatch
    annual_cost_usd: Optional[Decimal]
    scope: Optional[str]
    notes: Optional[str]


@dataclass(frozen=True)
class CatalogSearchResult:
    candidates: tuple[CatalogCandidate, ...]
    evidence: tuple[EvidenceItem, ...]

    @property
    def matches(self) -> tuple[CatalogMatch, ...]:
        """The policy-engine-ready view of the candidates, e.g. for
        ``PolicyContext.catalog_overlap_matches``.
        """
        return tuple(c.match for c in self.candidates)


def search_catalog(
    *, product_name: Optional[str] = None, vendor_name: Optional[str] = None, category: Optional[str] = None
) -> CatalogSearchResult:
    if not any([product_name, vendor_name, category]):
        return CatalogSearchResult(
            candidates=(),
            evidence=(
                EvidenceItem(
                    source="software_catalog",
                    finding="No search criteria supplied; catalog not searched.",
                    reference="software_catalog.csv",
                ),
            ),
        )

    catalog = data_access.load_software_catalog()
    mask = pd.Series(False, index=catalog.index)
    # An empty normalized query (e.g. "!!!" or whitespace) matches nothing: it must not match blank cells.
    if _squash(product_name):
        mask |= catalog["product_name"].map(_squash) == _squash(product_name)
    if _squash(vendor_name):
        mask |= catalog["vendor_name"].map(_squash) == _squash(vendor_name)
    if _squash(category):
        mask |= catalog["category"].map(_squash) == _squash(category)

    # sort by software_id for a stable, deterministic, repeatable ordering
    matched_rows = catalog[mask].sort_values("software_id")

    candidates = tuple(
        CatalogCandidate(
            match=CatalogMatch.from_row(row.to_dict()),
            annual_cost_usd=to_decimal(row.get("annual_cost_usd")),
            scope=str(row["scope"]).strip() if pd.notna(row.get("scope")) else None,
            notes=str(row["notes"]).strip() if pd.notna(row.get("notes")) else None,
        )
        for _, row in matched_rows.iterrows()
    )

    if not candidates:
        evidence = (
            EvidenceItem(
                source="software_catalog",
                finding="No existing catalog overlap found for the given criteria.",
                reference="software_catalog.csv",
            ),
        )
    else:
        summary = "; ".join(
            f"{c.match.product_name} ({c.match.software_id}, status: {c.match.status})"
            + (f" -- {c.notes}" if c.notes else "")
            for c in candidates
        )
        evidence = (
            EvidenceItem(
                source="software_catalog",
                finding=f"Existing catalog match(es): {summary}.",
                reference="software_catalog.csv",
            ),
        )

    return CatalogSearchResult(candidates=candidates, evidence=evidence)
