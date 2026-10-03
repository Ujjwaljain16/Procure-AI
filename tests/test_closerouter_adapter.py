"""CloseRouter adapter, tested offline against a fake HTTP boundary (no key, no network).

The fake replaces only the object that performs the POST. The adapter, the message conversion, the attempt
counter, response parsing, and both orchestrators run for real.
"""

from __future__ import annotations

import json

import pytest
import requests

from src.agent.attempts import current_attempts
from src.agent.closerouter_adapter import (
    DEFAULT_MODEL,
    CloseRouterClient,
    CloseRouterStagedClient,
    create_closerouter_client,
)
from src.agent.gemini_adapter import GeminiConfigurationError, ModelOutputError, ToolCall
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace

KEY = "test-key-not-real-closerouter"
SYNTH_OK = {"recommendation": "Route to the listed approvers; no purchase has been made.", "rationale": "Based on the evidence provided.", "evidence_refs": [], "next_step": "Route for human approval.", "prompt_injection_detected": False}
REPORT_OK = {"request_summary": "Purchase request under review.", "observations": [], "unresolved_questions": [], "contextual_risks": [], "evidence_refs": []}


class FakeResponse:
    def __init__(self, status: int, body=None, text: str = ""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)


def _choice(message: dict) -> FakeResponse:
    return FakeResponse(200, {"choices": [{"message": message}]})


class FakeCloseRouterHttp:
    """Scripted POST boundary. mode: normal | tool_then_stop | malformed | http503 | unreachable."""

    def __init__(self, mode: str = "normal"):
        self.mode = mode
        self.calls = 0
        self.payloads: list[dict] = []
        self.headers: list[dict] = []
        self._turns = 0

    def post(self, url, headers, json, timeout):
        self.calls += 1
        self.payloads.append(json)
        self.headers.append(headers)
        if self.mode == "unreachable":
            raise requests.ConnectionError("unreachable")
        if self.mode == "http503":
            return FakeResponse(503, {"error": "overloaded"})
        if "tools" in json:
            self._turns += 1
            if self.mode == "tool_then_stop" and self._turns == 1:
                return _choice({"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "get_employee_budget", "arguments": json_dumps({"employee_id": "E004"})}}]})
            return _choice({"role": "assistant", "content": ""})
        system = json["messages"][0]["content"]
        body = REPORT_OK if '"contextual_risks"' in system else SYNTH_OK
        if self.mode == "malformed":
            return _choice({"role": "assistant", "content": "{ not json"})
        return _choice({"role": "assistant", "content": json_dumps(body)})


def json_dumps(value) -> str:
    return json.dumps(value)


def _client(http, staged=False):
    cls = CloseRouterStagedClient if staged else CloseRouterClient
    return cls(api_key=KEY, model=DEFAULT_MODEL, http=http)


# --- normal path -----------------------------------------------------------------------------------------


def test_normal_run_completes_and_counts_one_attempt_per_request():
    http = FakeCloseRouterHttp("normal")
    before = current_attempts()
    result = run_single_agent_with_trace("REQ-1001", client=_client(http))
    assert result.gemini_unavailable_reason is None
    assert result.decision.telemetry.llm_calls == 2  # one tool turn that stops, one structured synthesis
    assert result.decision.telemetry.api_attempts == http.calls == 2
    assert result.decision.telemetry.model == DEFAULT_MODEL
    assert current_attempts() - before == http.calls


def test_the_key_is_sent_in_the_header_and_never_appears_in_the_decision():
    http = FakeCloseRouterHttp("normal")
    result = run_single_agent_with_trace("REQ-1001", client=_client(http))
    assert all(h["Authorization"] == f"Bearer {KEY}" for h in http.headers)
    assert KEY not in result.decision.model_dump_json()


def test_the_history_is_converted_to_chat_messages():
    http = FakeCloseRouterHttp("normal")
    run_single_agent_with_trace("REQ-1001", client=_client(http))
    first = http.payloads[0]["messages"]
    assert first[0]["role"] == "system"
    assert first[1]["role"] == "user" and "content" in first[1] and "parts" not in first[1]


# --- tool calls ------------------------------------------------------------------------------------------


def test_a_model_tool_request_is_executed_supplementally_and_answered_in_chat_form():
    http = FakeCloseRouterHttp("tool_then_stop")
    result = run_single_agent_with_trace("REQ-1001", client=_client(http))
    tool_calls = [r for r in result.registry.execution_log if r.tool_name == "get_employee_budget"]
    assert len(tool_calls) >= 2  # the preflight lookup plus the model's supplemental one
    second_turn = http.payloads[1]["messages"]
    tool_message = next(m for m in second_turn if m.get("role") == "tool")
    assert tool_message["tool_call_id"] == "call_1"
    assert json.loads(tool_message["content"])["success"] is True


def test_a_tool_call_with_bad_argument_json_is_a_parse_failure_not_a_crash():
    with pytest.raises(ModelOutputError):
        CloseRouterClient._arguments("{ not json")


# --- failures --------------------------------------------------------------------------------------------


def test_malformed_structured_output_is_recorded_as_parse_failed():
    http = FakeCloseRouterHttp("malformed")
    result = run_single_agent_with_trace("REQ-1001", client=_client(http))
    assert result.gemini_unavailable_reason == "PARSE_FAILED"
    assert result.decision.human_review_required is True


def test_http_503_is_one_failed_attempt_recorded_as_a_transport_failure():
    http = FakeCloseRouterHttp("http503")
    result = run_single_agent_with_trace("REQ-1001", client=_client(http))
    assert result.gemini_unavailable_reason == "HTTPError"
    assert result.decision.telemetry.api_attempts == http.calls == 1
    assert result.decision.telemetry.llm_calls == 1


def test_unreachable_service_is_one_failed_attempt_recorded_as_connection_error():
    http = FakeCloseRouterHttp("unreachable")
    result = run_single_agent_with_trace("REQ-1001", client=_client(http))
    assert result.gemini_unavailable_reason == "ConnectionError"
    assert result.decision.telemetry.api_attempts == http.calls == 1


def test_a_failure_keeps_the_authoritative_policy_fields():
    normal = run_single_agent_with_trace("REQ-1001", client=_client(FakeCloseRouterHttp("normal"))).decision
    failed = run_single_agent_with_trace("REQ-1001", client=_client(FakeCloseRouterHttp("http503"))).decision
    assert (normal.required_approvals, normal.risk_flags, normal.missing_information) == (failed.required_approvals, failed.risk_flags, failed.missing_information)


# --- staged architecture ---------------------------------------------------------------------------------


def test_the_staged_run_makes_analyst_report_and_reviewer_calls_on_the_same_client():
    http = FakeCloseRouterHttp("normal")
    result = run_staged_agent_with_trace("REQ-1001", client=_client(http, staged=True))
    assert result.gemini_unavailable_reason is None
    assert result.analyst_report is not None
    assert result.decision.telemetry.api_attempts == http.calls == result.decision.telemetry.llm_calls == 3


# --- configuration ---------------------------------------------------------------------------------------


def test_creating_a_client_without_a_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("CLOSEROUTER_API_KEY", raising=False)
    with pytest.raises(GeminiConfigurationError, match="CLOSEROUTER_API_KEY"):
        create_closerouter_client()


def test_the_model_and_base_url_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLOSEROUTER_API_KEY", KEY)
    monkeypatch.delenv("CLOSEROUTER_MODEL", raising=False)
    monkeypatch.delenv("CLOSEROUTER_BASE_URL", raising=False)
    client = create_closerouter_client()
    assert client.model_name == DEFAULT_MODEL
    monkeypatch.setenv("CLOSEROUTER_MODEL", "google/gemini-3.1-flash-lite")
    assert create_closerouter_client().model_name == "google/gemini-3.1-flash-lite"


# --- evaluator integration: same scorers, CloseRouter transport -------------------------------------------

from evaluation.correctness import evaluator as ev  # noqa: E402


def test_the_evaluator_scores_a_closerouter_normal_run_with_all_dimensions_passing():
    truth = ev.load_ground_truth()
    payload = ev.run_real(
        truth, archs=ev.ARCHS, modes=("normal",), case_ids={"S-1001"},
        make_transports=lambda arch, mode, raw: [FakeCloseRouterHttp("normal")], provider="closerouter",
    )
    bad = [(r["architecture"], d) for r in payload["rows"] for d, v in r["dimensions"].items() if v is False]
    assert bad == []
    assert payload["integrity"]["attempt_mismatches"] == 0
    assert payload["integrity"]["attempt_checks"] == 2


def test_the_cli_refuses_a_closerouter_live_run_without_its_key(monkeypatch, capsys):
    monkeypatch.delenv("CLOSEROUTER_API_KEY", raising=False)
    monkeypatch.setattr(ev, "_production_client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a client was built without a key")))
    assert ev.main(["--real", "--provider", "closerouter"]) == 2
    assert "CLOSEROUTER_API_KEY" in capsys.readouterr().out


def test_a_closerouter_production_run_is_reported_as_a_live_model_call(monkeypatch):
    """The production label path, with the HTTP boundary faked: the run is labelled as CloseRouter and counted as live."""
    def production(arch, provider="gemini"):
        cls = CloseRouterStagedClient if arch == "staged" else CloseRouterClient
        return cls(api_key="fake", http=FakeCloseRouterHttp("normal"))

    monkeypatch.setattr(ev, "_production_client", production)
    payload = ev.run_real(ev.load_ground_truth(), archs=ev.ARCHS, modes=("normal",), case_ids={"S-1001"}, provider="closerouter")
    assert payload["transports"] == [ev.CLOSEROUTER_LABEL]
    assert payload["live_model_called"] is True
    assert payload["provider"] == "closerouter"
