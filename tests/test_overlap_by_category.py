"""Overlap by category.

Clause: data/procurement_policy.md section 3 -- "Before recommending a new product, check the
approved software catalog for: the same product or vendor, the same category, an existing
product that could reasonably satisfy the stated use case." and "Suggested risk flag:
`existing_tool_overlap`."

REQ-1002 (BrandBoard, category "Design & Creative") overlaps PixelCraft Pro and CreativeSuite
only through the category. The catalog tool already matches category; what was missing was a
search that actually supplied it (the replay stand-in omitted it, and the prompt did not ask).
"""

from __future__ import annotations

from evaluation.replay_client import ReplayGeminiClient
from src import data_access
from src.agent import prompts, staged_prompts
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace


def _first_catalog_call(raw):
    turn = ReplayGeminiClient(raw).generate_turn([], [], "")
    return next(c for c in turn.function_calls if c.name == "search_catalog")


def test_replay_model_supplies_the_requests_category_to_the_catalog_search():
    raw = data_access.get_request("REQ-1002")
    assert _first_catalog_call(raw).arguments["category"] == "Design & Creative"


def test_replay_omits_category_only_when_the_request_has_none():
    raw = {**data_access.get_request("REQ-1002"), "category": None}
    assert "category" not in _first_catalog_call(raw).arguments


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


def test_both_prompts_tell_the_model_to_pass_the_category():
    assert "category" in prompts.SYSTEM_PROMPT and "section 3" in prompts.SYSTEM_PROMPT
    assert "category" in staged_prompts.ANALYST_SYSTEM_PROMPT and "section 3" in staged_prompts.ANALYST_SYSTEM_PROMPT
