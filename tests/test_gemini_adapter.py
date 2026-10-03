"""Tests for src/agent/gemini_adapter.py.

`GeminiClient._to_model_turn` is tested against real `google.genai.types`
response objects (constructed directly, no network call) rather than fakes,
since this is exactly the SDK-response-shape-parsing logic this project could
not independently confirm against a live API call at implementation time --
these tests exist specifically to catch a shape mismatch against the real,
installed SDK version.

No test in this file requires a GEMINI_API_KEY or makes a network call.
"""

from __future__ import annotations

import pytest

from src.agent.gemini_adapter import GeminiClient, GeminiConfigurationError, create_gemini_client


class TestCreateGeminiClient:
    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        with pytest.raises(GeminiConfigurationError):
            create_gemini_client()

    def test_error_message_never_contains_the_env_var_name_as_a_value_placeholder(self, monkeypatch):
        # sanity: the error message must never echo back a key value (there
        # is none here, but this guards against a future regression that
        # might start interpolating os.environ values into the message).
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        try:
            create_gemini_client()
        except GeminiConfigurationError as exc:
            assert "sk-" not in str(exc) and "AIza" not in str(exc)

    def test_uses_default_model_when_unset(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        client = create_gemini_client()
        assert client._model == "gemini-2.5-flash"

    def test_respects_explicit_model_override(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
        client = create_gemini_client()
        assert client._model == "gemini-2.5-flash"


class TestModelTurnParsingAgainstRealSdkTypes:
    """Constructs actual google.genai.types objects (no network call) to
    verify _to_model_turn parses the real response shape correctly.
    """

    def test_single_function_call_is_parsed(self):
        from google.genai import types

        function_call = types.FunctionCall(id="call_1", name="get_employee_budget", args={"employee_id": "E004"})
        part = types.Part(function_call=function_call)
        content = types.Content(role="model", parts=[part])
        candidate = types.Candidate(content=content)
        response = types.GenerateContentResponse(candidates=[candidate])

        turn = GeminiClient._to_model_turn(response)

        assert len(turn.function_calls) == 1
        assert turn.function_calls[0].name == "get_employee_budget"
        assert turn.function_calls[0].arguments == {"employee_id": "E004"}
        assert turn.function_calls[0].call_id == "call_1"

    def test_multiple_function_calls_in_one_turn_are_all_parsed(self):
        from google.genai import types

        parts = [
            types.Part(function_call=types.FunctionCall(id="call_1", name="get_employee_budget", args={"employee_id": "E004"})),
            types.Part(function_call=types.FunctionCall(id="call_2", name="search_catalog", args={"vendor_name": "SignFlow"})),
        ]
        content = types.Content(role="model", parts=parts)
        candidate = types.Candidate(content=content)
        response = types.GenerateContentResponse(candidates=[candidate])

        turn = GeminiClient._to_model_turn(response)

        assert [c.name for c in turn.function_calls] == ["get_employee_budget", "search_catalog"]

    def test_text_only_response_has_no_function_calls(self):
        from google.genai import types

        part = types.Part(text="Here is my analysis.")
        content = types.Content(role="model", parts=[part])
        candidate = types.Candidate(content=content)
        response = types.GenerateContentResponse(candidates=[candidate])

        turn = GeminiClient._to_model_turn(response)

        assert turn.function_calls == ()
        assert turn.text == "Here is my analysis."

    def test_raw_content_is_preserved_for_conversation_replay(self):
        from google.genai import types

        content = types.Content(role="model", parts=[types.Part(text="ok")])
        candidate = types.Candidate(content=content)
        response = types.GenerateContentResponse(candidates=[candidate])

        turn = GeminiClient._to_model_turn(response)

        assert turn.raw_content is content

    def test_no_candidates_does_not_crash(self):
        from google.genai import types

        response = types.GenerateContentResponse(candidates=[])
        turn = GeminiClient._to_model_turn(response)
        assert turn.function_calls == ()
        assert turn.raw_content is None
