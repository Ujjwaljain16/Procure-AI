"""Negative cost -> clarification; NaN/Infinity -> hard error; cost 0 valid.

Clause: data/procurement_policy.md section 1 -- "A request is not ready for approval if any of the
following are missing ... annual cost or a reasonable annual estimate" and "If material information
is missing, request clarification instead of inventing values." A negative cost is not a usable
amount, so it is reported as missing information ("annual cost (invalid value)") and is never
priced; it would otherwise land in the section 4 "Up to $1,000" tier. NaN and +/-Infinity are
corrupt data rather than a typo and stop the request. Section 4 tiers are unchanged.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from evaluation.replay_client import ReplayGeminiClient
from src import data_access
from src.agent.single_agent import run_single_agent_with_trace
from src.data_access import MalformedRequestError, get_request_validated
from src.policy_engine import PolicyContext, RequestFields, evaluate_policy, to_decimal

_BASE = {"request_id": "REQ-T1", "requester_id": "E001", "product_name": "Tool", "vendor_name": "TaskFlow", "annual_cost_usd": 500}


def _validated(monkeypatch, cost):
    raw = copy.deepcopy(_BASE)
    raw["annual_cost_usd"] = cost
    monkeypatch.setattr(data_access, "get_request", lambda rid: raw)
    return get_request_validated("REQ-T1")


@pytest.mark.parametrize("cost", ["NaN", float("nan"), "Infinity", float("inf"), "-Infinity", "$5,000", "abc"])
def test_non_finite_and_non_numeric_costs_are_hard_errors(monkeypatch, cost):
    with pytest.raises(MalformedRequestError):
        _validated(monkeypatch, cost)


@pytest.mark.parametrize("cost", [-5000, -0.01, "-1", 0, "0", 0.01, 1000, 10**9, None])
def test_negative_zero_positive_and_missing_costs_pass_the_gate(monkeypatch, cost):
    assert _validated(monkeypatch, cost)["request_id"] == "REQ-T1"


@pytest.mark.parametrize("cost", [-5000, "-0.01", -1])
def test_a_negative_cost_is_missing_information_and_is_never_priced(cost):
    request = RequestFields.from_raw({"request_id": "x", "annual_cost_usd": cost, "user_count": 1})
    assert request.annual_cost_usd is None and request.annual_cost_invalid is True
    evaluation = evaluate_policy(PolicyContext(request=request))
    assert "annual cost (invalid value)" in evaluation.missing_information
    assert "missing_information" in evaluation.risk_flags
    assert "Manager" not in evaluation.required_approvals  # no tier is priced from a negative number
    assert not any(c.rule_id.startswith("POL-4") and c.status.value == "flagged" for c in evaluation.checks)


def test_a_missing_cost_keeps_its_original_label():
    request = RequestFields.from_raw({"request_id": "x", "annual_cost_usd": None})
    assert "annual cost" in evaluate_policy(PolicyContext(request=request)).missing_information


def test_zero_cost_is_priced_in_the_lowest_tier():
    request = RequestFields.from_raw({"request_id": "x", "annual_cost_usd": 0, "user_count": 1})
    assert request.annual_cost_usd == Decimal("0") and request.annual_cost_invalid is False
    assert evaluate_policy(PolicyContext(request=request)).required_approvals[0] == "Manager"


@pytest.mark.parametrize("value", ["NaN", "Infinity", float("inf")])
def test_policy_money_normalizer_refuses_non_finite_values(value):
    with pytest.raises(ValueError):
        to_decimal(value)


def test_end_to_end_a_negative_cost_request_returns_a_decision_with_a_clarification_request(monkeypatch, live_vendor_records):
    # live_vendor_records: the vendor-driven Privacy approval only exists when the vendor record is reachable.
    raw = {**data_access.get_request("REQ-1001"), "annual_cost_usd": -5000}
    monkeypatch.setattr(data_access, "get_request", lambda rid: raw)
    result = run_single_agent_with_trace("REQ-1001", client=ReplayGeminiClient(raw))
    decision = result.decision
    assert "annual cost (invalid value)" in decision.missing_information
    assert decision.human_review_required is True
    assert "Manager" not in decision.required_approvals  # no tier priced from a negative cost
    assert decision.required_approvals == ["Privacy"]  # only the vendor-driven approval remains


def test_the_ui_still_marks_the_cost_field_as_missing(monkeypatch):
    from src.ui.view_model import build_procurement_view

    raw = {**data_access.get_request("REQ-1001"), "annual_cost_usd": -5000}
    monkeypatch.setattr(data_access, "get_request", lambda rid: raw)
    view = build_procurement_view(run_single_agent_with_trace("REQ-1001", client=ReplayGeminiClient(raw)))
    cost_field = next(f for f in view.request_details if f.label == "Annual cost")
    assert cost_field.is_missing
    assert "annual cost (invalid value)" in view.missing_information
