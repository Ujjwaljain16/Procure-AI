"""Overlap by category.

Clause: data/procurement_policy.md section 3 -- "Before recommending a new product, check the
approved software catalog for: the same product or vendor, the same category, an existing
product that could reasonably satisfy the stated use case." and "Suggested risk flag:
`existing_tool_overlap`."

REQ-1002 (BrandBoard, category "Design & Creative") overlaps PixelCraft Pro and CreativeSuite
only through the category. The catalog tool already matches category. The category must reach
the catalog search, and the deterministic preflight now supplies it in code, so no model choice
can drop it.
"""

from __future__ import annotations

from evaluation.replay_client import ReplayGeminiClient
from src import data_access
from src.agent import prompts, staged_prompts
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.evidence import gather_mandatory_evidence


def _preflight_catalog_call(raw):
    return next(r for r in gather_mandatory_evidence(raw).execution_log if r.tool_name == "search_catalog")


def test_preflight_supplies_the_requests_category_to_the_catalog_search():
    raw = data_access.get_request("REQ-1002")
    assert _preflight_catalog_call(raw).arguments["category"] == "Design & Creative"


def test_preflight_applies_no_category_filter_when_the_request_has_none():
    # validated arguments store an absent optional field as None; both mean "no category filter"
    raw = {**data_access.get_request("REQ-1002"), "category": None}
    assert not _preflight_catalog_call(raw).arguments.get("category")


def test_req_1002_flags_existing_tool_overlap_through_the_category_alone_single():
    raw = data_access.get_request("REQ-1002")
    flags = run_single_agent_with_trace("REQ-1002", client=ReplayGeminiClient(raw)).decision.risk_flags
    assert "existing_tool_overlap" in flags


def test_req_1002_flags_existing_tool_overlap_through_the_category_alone_staged():
    raw = data_access.get_request("REQ-1002")
    flags = run_staged_agent_with_trace("REQ-1002", client=ReplayGeminiClient(raw)).decision.risk_flags
    assert "existing_tool_overlap" in flags


def test_the_overlap_comes_from_the_category_not_the_product_or_vendor():
    from src.tools.catalog import search_catalog

    by_name_and_vendor = search_catalog(product_name="BrandBoard Enterprise", vendor_name="BrandBoard")
    assert by_name_and_vendor.matches == ()
    by_category = search_catalog(product_name="BrandBoard Enterprise", vendor_name="BrandBoard", category="Design & Creative")
    assert {m.vendor_name for m in by_category.matches} == {"PixelCraft", "CreativeSuite Labs"}


def test_both_prompts_say_the_evidence_is_already_gathered_so_the_model_cannot_drop_the_category():
    assert "already been gathered" in prompts.SYSTEM_PROMPT
    assert "already been gathered" in staged_prompts.ANALYST_SYSTEM_PROMPT
