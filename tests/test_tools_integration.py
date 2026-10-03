"""Integration test: tool outputs -> PolicyContext -> evaluate_policy(),
entirely without an LLM. Proves the tool layer built in this phase produces
inputs the policy engine can actually consume end-to-end, using real
requests from data/requests.json.

The vendor-risk API call is monkeypatched at the same boundary as
test_vendor_risk_tool.py (see that file's module docstring for why), using
realistic payload values drawn from data/vendor_risk.json.
"""

from __future__ import annotations

import requests

from src import data_access
from src.policy_engine import PolicyContext, RequestFields, evaluate_policy
from src.tools import vendor_risk as vendor_risk_tool
from src.tools.catalog import search_catalog
from src.tools.employee_budget import get_employee_budget


def _build_context(request_id: str) -> PolicyContext:
    raw = data_access.get_request(request_id)
    employee_result = get_employee_budget(raw["requester_id"])
    catalog_result = search_catalog(vendor_name=raw["vendor_name"])
    vendor_result = vendor_risk_tool.get_vendor_evidence(raw["vendor_name"])

    department = employee_result.employee.department if employee_result.employee else None
    request = RequestFields.from_raw(raw, department=department)

    return PolicyContext(
        request=request,
        budget=employee_result.budget,
        catalog_overlap_matches=catalog_result.matches,
        vendor_registry=vendor_result.registry,
        vendor_risk=vendor_result.vendor_risk,
    )


class TestNormalRequestEndToEnd:
    def test_req_1001_signflow_addon(self, monkeypatch):
        # Real data/vendor_risk.json values for SignFlow.
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "risk_level": "low",
                "security_review_status": "approved",
                "last_review_date": "2026-06-20",
                "processes_personal_data": True,
                "stores_data_outside_region": False,
                "notes": "Current assessment.",
            },
        )
        context = _build_context("REQ-1001")
        evaluation = evaluate_policy(context)

        assert context.request.department == "Finance"
        assert context.budget.available_usd is not None
        assert "Manager" in evaluation.required_approvals  # $800 is within the POL-4a tier
        assert "Privacy" in evaluation.required_approvals  # SignFlow processes personal data
        assert evaluation.missing_information == ()
        assert evaluation.human_review_required is True


class TestSignalWatchEndToEnd:
    def test_req_1007_signalwatch_advanced_surfaces_conflict(self, monkeypatch):
        # Real data/vendor_risk.json values for SignalWatch: expired, while
        # vendors.csv's registry row separately says Approved.
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "risk_level": "medium",
                "security_review_status": "expired",
                "last_review_date": "2025-07-01",
                "processes_personal_data": False,
                "stores_data_outside_region": False,
                "notes": "Reassessment required before expanded production access.",
            },
        )
        context = _build_context("REQ-1007")
        evaluation = evaluate_policy(context)

        assert context.vendor_registry.security_status == "Approved"
        assert context.vendor_risk.security_review_status == "expired"
        assert "conflicting_vendor_evidence" in evaluation.risk_flags
        assert "Security" in evaluation.required_approvals
        assert evaluation.human_review_required is True


class TestNimbusAiEndToEnd:
    def test_req_1009_nimbusai_outage_requires_review_without_favorable_inference(self, monkeypatch):
        def raise_503(name, timeout_seconds=3.0):
            response = requests.Response()
            response.status_code = 503
            raise requests.HTTPError(response=response)

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", raise_503)
        context = _build_context("REQ-1009")
        evaluation = evaluate_policy(context)

        assert context.vendor_risk.security_review_status is None
        assert "vendor_risk_unavailable" in evaluation.risk_flags
        assert "security_review_required" in evaluation.risk_flags
        assert "Security" in evaluation.required_approvals
        assert evaluation.human_review_required is True
        # the live check failing must never be silently read as approval
        assert "conflicting_vendor_evidence" not in evaluation.risk_flags


class TestDeterminismAcrossTheFullPipeline:
    def test_same_request_and_same_mocked_dependencies_yield_identical_evaluation(self, monkeypatch):
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "security_review_status": "approved",
                "last_review_date": "2026-06-20",
                "processes_personal_data": True,
                "stores_data_outside_region": False,
            },
        )
        first = evaluate_policy(_build_context("REQ-1001"))
        second = evaluate_policy(_build_context("REQ-1001"))
        assert first == second
