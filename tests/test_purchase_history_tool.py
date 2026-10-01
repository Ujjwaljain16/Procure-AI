"""Tests for src/tools/purchase_history.py, against the real starter-pack data."""

from __future__ import annotations

from decimal import Decimal

from src.tools.purchase_history import search_purchase_history


class TestKnownDepartment:
    def test_department_with_multiple_purchases(self):
        result = search_purchase_history(department="Engineering")
        assert {r.purchase_id for r in result.records} == {"PO-2418", "PO-2440"}

    def test_department_with_no_purchases_is_empty_not_fabricated(self):
        result = search_purchase_history(department="Sales")
        assert result.records == ()


class TestKnownVendorOrProduct:
    def test_vendor_match(self):
        result = search_purchase_history(vendor_name="SignalWatch")
        assert len(result.records) == 1
        assert result.records[0].purchase_id == "PO-2418"
        assert result.records[0].annual_amount_usd == Decimal("80000")

    def test_product_match(self):
        result = search_purchase_history(product_name="TaskFlow")
        assert len(result.records) == 1
        assert result.records[0].department == "Operations"


class TestNoMatch:
    def test_no_criteria_returns_nothing(self):
        result = search_purchase_history()
        assert result.records == ()

    def test_unknown_vendor_returns_nothing(self):
        result = search_purchase_history(vendor_name="Nonexistent Vendor XYZ")
        assert result.records == ()
        assert "No matching purchase history" in result.evidence[0].finding


class TestOriginalStatusesPreserved:
    def test_all_starter_records_are_approved_and_reported_as_such(self):
        # The starter data currently contains only "Approved" purchase
        # history -- this must be reflected as-is, never invented into
        # rejected/pending states the data does not contain.
        result = search_purchase_history(department="Engineering")
        assert all(r.status == "Approved" for r in result.records)


class TestCombinedFiltersAreAnd:
    def test_department_and_vendor_together_narrow_the_match(self):
        result = search_purchase_history(department="Engineering", vendor_name="CodeMate")
        assert len(result.records) == 1
        assert result.records[0].purchase_id == "PO-2440"

    def test_department_and_unrelated_vendor_yields_nothing(self):
        result = search_purchase_history(department="Engineering", vendor_name="SignFlow")
        assert result.records == ()


class TestDeterministicOrdering:
    def test_multiple_records_are_sorted_by_purchase_id(self):
        result = search_purchase_history(department="Engineering")
        ids = [r.purchase_id for r in result.records]
        assert ids == sorted(ids)
