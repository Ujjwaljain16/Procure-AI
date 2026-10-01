"""Tests for the src.solution.handle_request adapter -- the actual entrypoint
the public/hidden evaluation harness calls.
"""

from __future__ import annotations

import pytest

import src.agent.single_agent as single_agent_module
import src.agent.staged_agent as staged_agent_module
from src.contracts import ProcurementDecision
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
