"""Tests for src/tools/catalog.py, against the real starter-pack data."""

from __future__ import annotations

from src.tools.catalog import search_catalog


class TestExactMatch:
    def test_exact_product_name_match(self):
        result = search_catalog(product_name="TaskFlow")
        assert [c.match.software_id for c in result.candidates] == ["SW003"]

    def test_vendor_match(self):
        result = search_catalog(vendor_name="PixelCraft")
        assert [c.match.software_id for c in result.candidates] == ["SW001"]

    def test_category_match_can_return_multiple(self):
        result = search_catalog(category="Design & Creative")
        assert {c.match.software_id for c in result.candidates} == {"SW001", "SW002"}


class TestNormalization:
    def test_case_and_whitespace_insensitive(self):
        result = search_catalog(product_name="  taskflow  ")
        assert [c.match.software_id for c in result.candidates] == ["SW003"]

    def test_original_values_preserved_despite_normalized_matching(self):
        result = search_catalog(product_name="taskflow")
        assert result.candidates[0].match.product_name == "TaskFlow"


class TestNoMatch:
    def test_no_search_criteria_returns_no_candidates(self):
        result = search_catalog()
        assert result.candidates == ()

    def test_unknown_product_returns_no_candidates(self):
        result = search_catalog(product_name="Nonexistent Product XYZ")
        assert result.candidates == ()
        assert "No existing catalog overlap" in result.evidence[0].finding


class TestNeuralDeskLimitedUse:
    def test_status_preserved_verbatim(self):
        result = search_catalog(vendor_name="NeuralDesk")
        assert len(result.candidates) == 1
        assert result.candidates[0].match.status == "Approved - limited use"

    def test_status_is_not_collapsed_to_plain_approved(self):
        result = search_catalog(vendor_name="NeuralDesk")
        assert result.candidates[0].match.status != "Approved"

    def test_notes_are_preserved(self):
        result = search_catalog(vendor_name="NeuralDesk")
        assert "sensitive data restrictions apply" in result.candidates[0].notes.lower()

    def test_notes_surface_in_evidence_text(self):
        result = search_catalog(vendor_name="NeuralDesk")
        assert "sensitive data restrictions" in result.evidence[0].finding.lower()


class TestOrMatchingAcrossCriteria:
    def test_matching_on_any_supplied_criterion(self):
        # vendor doesn't exist, but product name does -- OR semantics should
        # still surface the product match.
        result = search_catalog(product_name="TaskFlow", vendor_name="Nonexistent Vendor")
        assert [c.match.software_id for c in result.candidates] == ["SW003"]


class TestDeterministicOrdering:
    def test_multiple_matches_are_sorted_by_software_id(self):
        result = search_catalog(category="Design & Creative")
        ids = [c.match.software_id for c in result.candidates]
        assert ids == sorted(ids)

    def test_repeated_search_returns_identical_ordering(self):
        first = [c.match.software_id for c in search_catalog(category="Design & Creative").candidates]
        second = [c.match.software_id for c in search_catalog(category="Design & Creative").candidates]
        assert first == second


class TestPolicyEngineCompatibleView:
    def test_matches_property_returns_plain_catalog_match_tuple(self):
        result = search_catalog(product_name="TaskFlow")
        assert len(result.matches) == 1
        assert result.matches[0].software_id == "SW003"
