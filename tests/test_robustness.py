"""Behavioral tests for the robustness changes: cancellation at turn
boundaries, the single corrective turn, programming errors surfacing instead of
being hidden, canonical duplicate detection, reviewer status, the typed
model-output errors, and the top-level catch-all decision."""

from __future__ import annotations

import threading

import pytest

import src.agent.single_agent as single_agent_module
from src.agent.gemini_adapter import ModelOutputError, classify_model_exception
from src.agent.loop_utils import canonical_arguments
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.contracts import ProcurementDecision
from src.solution import handle_request
from tests.agent_fakes import ScriptedGeminiClient, stop_turn, tool_call, tool_turn
from tests.staged_agent_fakes import ScriptedStagedGeminiClient
from tests.test_agent_single import _synthesis
from tests.test_staged_agent import _analyst_report


class TestClassifyModelException:
    def test_typed_model_output_errors_keep_their_reason(self):
        assert classify_model_exception(ModelOutputError("PARSE_FAILED")) == "PARSE_FAILED"

    def test_connection_and_timeout_errors_are_transport_failures(self):
        assert classify_model_exception(ConnectionError("down")) == "ConnectionError"
        assert classify_model_exception(TimeoutError("slow")) == "TimeoutError"

    def test_sdk_error_classes_are_recognized_by_module(self):
        SdkError = type("ServerError", (Exception,), {"__module__": "google.genai.errors"})
        assert classify_model_exception(SdkError("503")) == "ServerError"

    def test_programming_errors_are_not_transport_failures(self):
        assert classify_model_exception(AttributeError("shape changed")) is None
        assert classify_model_exception(TypeError("bad argument")) is None


class TestProgrammingErrorsSurface:
    def test_attribute_error_in_the_model_call_is_raised_not_hidden(self):
        class _Buggy(ScriptedGeminiClient):
            def generate_turn(self, contents, tool_specs, system_instruction):
                raise AttributeError("response has no attribute 'function_calls'")

        with pytest.raises(AttributeError):
            run_single_agent_with_trace("REQ-1001", client=_Buggy(turns=[], structured_result=_synthesis()))


class TestCancellation:
    def test_a_cancelled_run_makes_no_further_model_calls(self):
        cancel = threading.Event()
        cancel.set()
        client = ScriptedGeminiClient(turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()], structured_result=_synthesis())
        result = run_single_agent_with_trace("REQ-1001", client=client, cancel_event=cancel)
        assert client.turn_calls == 0
        assert client.structured_calls == 0
        assert result.gemini_unavailable_reason == "ANALYSIS_TIMEOUT"

    def test_cancellation_between_turns_stops_the_loop(self):
        cancel = threading.Event()

        class _CancelAfterFirst(ScriptedGeminiClient):
            def generate_turn(self, contents, tool_specs, system_instruction):
                turn = super().generate_turn(contents, tool_specs, system_instruction)
                cancel.set()
                return turn

        client = _CancelAfterFirst(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), tool_turn(tool_call("search_catalog", product_name="X"))],
            structured_result=_synthesis(),
        )
        run_single_agent_with_trace("REQ-1001", client=client, cancel_event=cancel)
        assert client.turn_calls == 1


class TestCorrectiveTurn:
    def test_a_text_first_answer_gets_exactly_one_corrective_turn_then_tools_run(self):
        client = ScriptedGeminiClient(
            turns=[stop_turn(), tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        result = run_single_agent_with_trace("REQ-1001", client=client)
        assert result.decision.telemetry.tool_calls == 1
        assert client.turn_calls == 3

    def test_no_corrective_turn_once_evidence_has_been_gathered(self):
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        run_single_agent_with_trace("REQ-1001", client=client)
        assert client.turn_calls == 2


class TestCanonicalDuplicateDetection:
    def test_argument_order_does_not_make_a_repeat_look_new(self):
        assert canonical_arguments({"a": 1, "b": 2}) == canonical_arguments({"b": 2, "a": 1})

    def test_repeated_call_with_reordered_arguments_stops_the_loop(self):
        client = ScriptedGeminiClient(
            turns=[
                tool_turn(tool_call("search_catalog", product_name="X", vendor_name="Y")),
                tool_turn(tool_call("search_catalog", vendor_name="Y", product_name="X")),
                tool_turn(tool_call("search_catalog", product_name="X", vendor_name="Y")),
            ],
            structured_result=_synthesis(evidence_refs=[]),
        )
        run_single_agent_with_trace("REQ-1001", client=client)
        assert client.turn_calls == 2


class TestStagedReviewerStatus:
    def test_successful_reviewer_is_marked_ok(self):
        client = ScriptedStagedGeminiClient(turns=[stop_turn()], analyst_report=_analyst_report(), structured_result=_synthesis())
        result = run_staged_agent_with_trace("REQ-1001", client=client)
        assert result.reviewer_status == "OK"

    def test_missing_analyst_report_means_the_reviewer_was_skipped(self):
        client = ScriptedStagedGeminiClient(turns=[stop_turn()], analyst_report=ModelOutputError("PARSE_FAILED"), structured_result=_synthesis())
        result = run_staged_agent_with_trace("REQ-1001", client=client)
        assert result.reviewer_status == "SKIPPED"

    def test_reviewer_failure_keeps_the_analyst_report_and_its_reason(self):
        client = ScriptedStagedGeminiClient(
            turns=[stop_turn()], analyst_report=_analyst_report(), structured_result=ModelOutputError("EMPTY_RESPONSE")
        )
        result = run_staged_agent_with_trace("REQ-1001", client=client)
        assert result.reviewer_status == "FAILED"
        assert result.gemini_unavailable_reason == "EMPTY_RESPONSE"
        assert result.analyst_report is not None


class TestTelemetrySplit:
    def test_tool_calls_succeeded_counts_only_successful_calls(self):
        client = ScriptedGeminiClient(
            turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004"), tool_call("delete_everything", employee_id="E004")), stop_turn()],
            structured_result=_synthesis(evidence_refs=["E1"]),
        )
        telemetry = run_single_agent_with_trace("REQ-1001", client=client).decision.telemetry
        assert telemetry.tool_calls == 2
        assert telemetry.tool_calls_succeeded == 1


class TestUnexpectedInternalErrorIsAHumanReviewDecision:
    def test_handle_request_never_leaks_a_traceback_for_an_internal_bug(self, monkeypatch):
        def broken(request_id, client=None, cancel_event=None):
            raise RuntimeError("internal bug")

        monkeypatch.setattr(single_agent_module, "run_single_agent", broken)
        decision = handle_request("REQ-1001", architecture="single")
        assert isinstance(decision, ProcurementDecision)
        assert decision.human_review_required is True
        assert "analysis_failed" in decision.risk_flags
