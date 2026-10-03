"""Tests for the contract-level failure wording and the orchestrator-level
structural gate: both architectures must reject a malformed request before
any model call, and a Gemini failure must never leak a raw exception class
name into ProcurementDecision.recommendation.
"""

from __future__ import annotations

import pytest

import src.data_access as data_access_module
from src.agent.failure_taxonomy import classify_failure_reason
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.data_access import MalformedRequestError
from tests.agent_fakes import ScriptedGeminiClient


class _MustNotBeCalled:
    def generate_turn(self, *args, **kwargs):
        raise AssertionError("model must not be called for a malformed request")

    def generate_structured(self, *args, **kwargs):
        raise AssertionError("model must not be called for a malformed request")

    def build_function_response_content(self, *args, **kwargs):
        raise AssertionError("model must not be called for a malformed request")


@pytest.fixture
def malformed_request(monkeypatch):
    broken = {"request_id": "REQ-BROKEN", "requester_id": "E001", "product_name": "Tool"}  # no vendor_name
    monkeypatch.setattr(data_access_module, "load_requests", lambda: [broken])
    return "REQ-BROKEN"


class TestOrchestratorsRejectMalformedRequestsBeforeAnyModelCall:
    def test_single_architecture(self, malformed_request):
        with pytest.raises(MalformedRequestError):
            run_single_agent_with_trace(malformed_request, client=_MustNotBeCalled())

    def test_staged_architecture(self, malformed_request):
        with pytest.raises(MalformedRequestError):
            run_staged_agent_with_trace(malformed_request, client=_MustNotBeCalled())


class TestGeminiFailureWordingNeverLeaksRawNames:
    def test_recommendation_text_contains_no_raw_exception_class_name(self, monkeypatch):
        import src.agent.single_agent as single_agent_module

        class _Failing:
            def generate_turn(self, *args, **kwargs):
                raise type("ClientError", (Exception,), {})("boom")

            def generate_structured(self, *args, **kwargs):
                raise AssertionError("not reached")

            def build_function_response_content(self, *args, **kwargs):
                raise AssertionError("not reached")

        result = run_single_agent_with_trace("REQ-1001", client=_Failing())
        assert result.gemini_unavailable_reason == "ClientError"  # raw value kept for logs/audit
        assert "ClientError" not in result.decision.recommendation
        assert "temporarily unavailable" in result.decision.recommendation.lower()
        assert result.decision.human_review_required is True

    def test_missing_api_key_recommendation_is_clean(self, monkeypatch):
        # Clear both key variables: with a pool variable set, the runner would build a pooled production
        # client instead of taking the missing-key path this test is about.
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        result = run_single_agent_with_trace("REQ-1001")
        assert "GeminiConfigurationError" not in result.decision.recommendation


class TestFailureTaxonomy:
    def test_category_names_map_to_themselves(self):
        category, message = classify_failure_reason("REQUEST_INVALID")
        assert category == "REQUEST_INVALID"
        assert message
