"""Tests for the src.solution.handle_request adapter -- the actual entrypoint
the public/hidden evaluation harness calls.
"""

from __future__ import annotations

import pytest

import src.agent.single_agent as single_agent_module
import src.agent.staged_agent as staged_agent_module
from src.contracts import ProcurementDecision
from src.data_access import MalformedRequestError
from src.solution import handle_request
from tests.agent_fakes import ScriptedGeminiClient, stop_turn, tool_call, tool_turn
from tests.staged_agent_fakes import ScriptedStagedGeminiClient
from tests.test_agent_single import _synthesis
from tests.test_staged_agent import _analyst_report


class TestArchitectureRouting:
    def test_single_architecture_routes_to_run_single_agent(self, monkeypatch):
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(),
        )
        monkeypatch.setattr(single_agent_module, "create_gemini_client", lambda: client)

        decision = handle_request("REQ-1001", architecture="single")

        assert isinstance(decision, ProcurementDecision)
        assert decision.request_id == "REQ-1001"
        assert decision.telemetry.architecture == "single"

    def test_staged_architecture_routes_to_run_staged_agent(self, monkeypatch):
        client = ScriptedStagedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            analyst_report=_analyst_report(),
            structured_result=_synthesis(),
        )
        monkeypatch.setattr(staged_agent_module, "create_staged_gemini_client", lambda: client)

        decision = handle_request("REQ-1001", architecture="staged")

        assert isinstance(decision, ProcurementDecision)
        assert decision.request_id == "REQ-1001"
        assert decision.telemetry.architecture == "staged"

    def test_unknown_architecture_value_is_rejected(self):
        with pytest.raises(ValueError):
            handle_request("REQ-1001", architecture="triple")  # type: ignore[arg-type]

    def test_unknown_request_id_raises_not_a_fabricated_decision(self, monkeypatch):
        client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis())
        monkeypatch.setattr(single_agent_module, "create_gemini_client", lambda: client)
        with pytest.raises(KeyError):
            handle_request("REQ-DOES-NOT-EXIST", architecture="single")


class TestNoRealApiKeyRequired:
    def test_missing_gemini_api_key_degrades_gracefully_instead_of_crashing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        decision = handle_request("REQ-1001", architecture="single")
        assert isinstance(decision, ProcurementDecision)
        assert decision.human_review_required is True
        assert "unavailable" in decision.recommendation.lower()


class TestPreAnalysisGate:
    def test_a_structurally_broken_request_raises_before_any_llm_call(self, monkeypatch):
        import src.data_access as data_access_module

        broken = {"request_id": "REQ-BROKEN", "requester_id": "E001", "product_name": "Tool"}  # no vendor_name
        monkeypatch.setattr(data_access_module, "load_requests", lambda: [broken])

        def fail_if_called():
            raise AssertionError("Gemini client should never be constructed for a malformed request")

        monkeypatch.setattr(single_agent_module, "create_gemini_client", fail_if_called)

        with pytest.raises(MalformedRequestError):
            handle_request("REQ-BROKEN", architecture="single")


class TestAnalysisTimeout:
    def test_a_run_that_exceeds_the_deadline_degrades_to_a_conservative_decision(self, monkeypatch):
        import src.agent.timeout_guard as timeout_guard_module

        def always_times_out(fn, timeout_seconds=None):
            raise TimeoutError("simulated deadline")

        # solution.py imports run_with_timeout with a deferred `from ... import`
        # inside handle_request(), so patching the name on its source module
        # (rather than on src.solution, which never holds it as a module-level
        # attribute) is what the deferred import actually picks up at call time.
        monkeypatch.setattr(timeout_guard_module, "run_with_timeout", always_times_out)

        decision = handle_request("REQ-1001", architecture="single")

        assert isinstance(decision, ProcurementDecision)
        assert decision.human_review_required is True
        assert "timed out" in decision.recommendation.lower()
        assert "analysis_timeout" in decision.risk_flags
        assert decision.telemetry.architecture == "single"
