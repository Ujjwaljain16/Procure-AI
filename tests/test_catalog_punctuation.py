"""Catalog retrieval normalization: punctuation and spacing are ignored; matching stays EQUALITY.

Clause: data/procurement_policy.md section 3 -- check the catalog for "the same product or
vendor, the same category". Whether a category is "the same" cannot depend on a hyphen or a
space. POL-3 (any match -> existing_tool_overlap, not an automatic rejection) is unchanged.
No containment or similarity matching is added.
"""

from __future__ import annotations

import pytest

from src.tools.catalog import search_catalog


def _ids(result):
    return {m.software_id for m in result.matches}


@pytest.mark.parametrize("category", ["E-signature", "e signature", "E_Signature", "esignature", "  E-SIGNATURE  ", "e.signature"])
def test_category_matches_regardless_of_punctuation_and_case(category):
    assert "SW010" in _ids(search_catalog(category=category))


@pytest.mark.parametrize("vendor", ["Task Flow", "task-flow", "TASKFLOW", "Task_Flow"])
def test_vendor_matches_regardless_of_punctuation_and_case(vendor):
    assert _ids(search_catalog(vendor_name=vendor)) == {"SW003"}


@pytest.mark.parametrize("product", ["Pixel Craft Pro", "pixelcraft-pro", "PIXELCRAFT PRO"])
def test_product_matches_regardless_of_punctuation_and_case(product):
    assert _ids(search_catalog(product_name=product)) == {"SW001"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"product_name": "SignFlow Mobile"},  # a longer name is NOT a match: no containment
        {"product_name": "Sign"},
        {"vendor_name": "TaskFlow Inc"},
        {"vendor_name": "Flow"},
        {"category": "Signature"},
        {"category": "Design"},
        {"product_name": "TaskFlow Pro"},  # exact starter request product: no catalog product of that name
    ],
)
def test_no_containment_or_similarity_matching(kwargs):
    assert _ids(search_catalog(**kwargs)) == set()


def test_exact_matches_still_work_and_results_stay_ordered():
    result = search_catalog(vendor_name="SignFlow", category="Design & Creative")
    assert [m.software_id for m in result.matches] == ["SW001", "SW002", "SW010"]


def test_distinct_names_are_not_merged_by_squashing():
    assert _ids(search_catalog(vendor_name="PixelCraft")) == {"SW001"}
    assert _ids(search_catalog(vendor_name="CreativeSuite Labs")) == {"SW002"}


# --- blank cells and empty queries -------------------------------------------------------------

import numpy as np
import pandas as pd

from src import data_access
from src.tools.catalog import _squash


_ORIGINAL_LOADER = data_access.load_software_catalog


def _catalog_with_blank_cells():
    df = _ORIGINAL_LOADER().copy()
    blank = {c: None for c in df.columns}
    blank.update({"software_id": "SW999", "status": "Approved"})  # product, vendor, category all blank
    return pd.concat([df, pd.DataFrame([blank])], ignore_index=True)


@pytest.fixture
def blank_cell_catalog(monkeypatch):
    monkeypatch.setattr(data_access, "load_software_catalog", _catalog_with_blank_cells)


@pytest.mark.parametrize("value", [None, float("nan"), np.nan, pd.NA, ""])
def test_blank_values_normalize_to_empty(value):
    assert _squash(value) == ""


@pytest.mark.parametrize("query", ["nan", "NaN", "None", "none", "NAN"])
@pytest.mark.parametrize("field", ["product_name", "vendor_name", "category"])
def test_a_blank_cell_does_not_match_nan_or_none_text(blank_cell_catalog, field, query):
    assert "SW999" not in _ids(search_catalog(**{field: query}))


@pytest.mark.parametrize("query", ["", "   ", "!!!", "---", "...", " - "])
@pytest.mark.parametrize("field", ["product_name", "vendor_name", "category"])
def test_an_empty_normalized_query_matches_nothing(blank_cell_catalog, field, query):
    assert _ids(search_catalog(**{field: query})) == set()


def test_an_empty_query_is_ignored_next_to_a_real_one(blank_cell_catalog):
    assert _ids(search_catalog(product_name="!!!", vendor_name="TaskFlow")) == {"SW003"}


def test_blank_cells_do_not_disturb_normal_matches(blank_cell_catalog):
    assert _ids(search_catalog(vendor_name="Task Flow")) == {"SW003"}
    assert "SW999" not in _ids(search_catalog(category="E-signature"))


def test_starter_catalog_has_no_blank_product_vendor_or_category_cells():
    df = data_access.load_software_catalog()
    assert not df[["product_name", "vendor_name", "category"]].isna().any().any()
