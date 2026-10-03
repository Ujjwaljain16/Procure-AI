"""Thin adapter around the Gemini API's official Python SDK (``google-genai``,
``from google import genai``).

Every direct use of the SDK lives in this one module, behind a small
``GeminiClient`` interface (``generate_turn`` / ``generate_structured`` /
``build_function_response_content``) expressed in this project's own
``ToolCall``/``ModelTurn`` types. ``src/agent/single_agent.py`` and every test
in this project depend only on that interface, never on ``google.genai``
directly -- tests substitute a fake implementing the same three methods, with
no need to construct real SDK objects.

Manual (non-automatic) function calling is used throughout: this module
never lets the SDK execute a function on our behalf
(``automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)``).
``src/agent/single_agent.py`` is the one place that decides whether and how a
requested tool actually runs.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence

from src.agent.schemas import AgentSynthesis

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
GENERATION_TEMPERATURE = 0.0  # recorded in every evaluation manifest; deterministic-leaning decoding


class GeminiConfigurationError(Exception):
    """Raised when the Gemini client cannot be configured, e.g. a missing API key."""


class ModelOutputError(Exception):
    """The model answered, but the answer could not be used as the requested
    structure. ``reason`` is a stable code (EMPTY_RESPONSE, PARSE_FAILED) that
    the orchestrators record and show, instead of silently producing no output.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


_TRANSPORT_EXCEPTION_NAMES = frozenset(
    {"ClientError", "ServerError", "APIError", "HTTPError", "RequestException", "Timeout", "ConnectionError", "ReadTimeout", "ConnectTimeout"}
)
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0


def classify_model_exception(exc: BaseException) -> Optional[str]:
    """Returns the user-facing reason for an exception raised by a model
    call, or ``None`` when the exception is a programming error that must not
    be swallowed. Transport and service errors (the SDK's own error classes,
    network timeouts, HTTP errors) and output errors are recognized;
    everything else -- an AttributeError from a changed response shape, a
    TypeError from a bad argument -- is re-raised so it surfaces as a bug.
    """
    if isinstance(exc, ModelOutputError):
        return exc.reason
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    if module.startswith("google") or name in _TRANSPORT_EXCEPTION_NAMES:
        return name
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return name
    return None


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ModelTurn:
    """Our own normalized view of one ``generate_content`` response,
    independent of the raw SDK response shape."""

    function_calls: tuple[ToolCall, ...]
    text: Optional[str]
    raw_content: Any  # the SDK's Content object for this turn, replayed back into `contents`


class GeminiClientProtocol(Protocol):
    """The interface src/agent/single_agent.py depends on. Tests implement
    this directly with canned responses instead of touching the real SDK."""

    def generate_turn(self, contents: list, tool_specs: Sequence, system_instruction: str) -> ModelTurn: ...

    def generate_structured(self, contents: list, system_instruction: str) -> AgentSynthesis: ...

    def build_function_response_content(self, call: ToolCall, result: dict) -> Any: ...


class GeminiClient:
    """Real implementation backed by ``google.genai.Client``. The SDK import
    is deferred to ``__init__`` so importing this module (and everything that
    imports it) never requires the ``google-genai`` package to be installed
    unless a real client is actually constructed.
    """

    def __init__(self, api_key: str, model: str, http_timeout_seconds: Optional[float] = None) -> None:
        from google import genai  # deferred import -- see class docstring

        timeout_s = http_timeout_seconds or float(os.environ.get("GEMINI_HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS))
        self._genai = genai
        self._client = genai.Client(api_key=api_key, http_options={"timeout": int(timeout_s * 1000)})
        self._model = model

    def generate_turn(self, contents: list, tool_specs: Sequence, system_instruction: str) -> ModelTurn:
        from google.genai import types

        tool = self._build_tool(tool_specs) if tool_specs else None
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=GENERATION_TEMPERATURE,
            tools=[tool] if tool else None,
            automatic_function_calling=(
                types.AutomaticFunctionCallingConfig(disable=True) if tool else None
            ),
        )
        response = self._client.models.generate_content(model=self._model, contents=contents, config=config)
        return self._to_model_turn(response)

    def generate_structured(self, contents: list, system_instruction: str) -> AgentSynthesis:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=GENERATION_TEMPERATURE,
            response_mime_type="application/json",
            response_schema=AgentSynthesis,
        )
        response = self._client.models.generate_content(model=self._model, contents=contents, config=config)
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, AgentSynthesis):
            return parsed
        text = getattr(response, "text", None)
        if not text:
            logger.warning("gemini structured call returned an empty response")
            raise ModelOutputError("EMPTY_RESPONSE")
        try:
            return AgentSynthesis.model_validate_json(text)
        except Exception as exc:
            logger.warning("gemini structured output did not parse (response length %d)", len(text))
            raise ModelOutputError("PARSE_FAILED", type(exc).__name__) from exc

    def build_function_response_content(self, call: ToolCall, result: dict) -> Any:
        from google.genai import types

        part = types.Part.from_function_response(name=call.name, response=result)
        return types.Content(role="tool", parts=[part])

    def _build_tool(self, tool_specs: Sequence) -> Any:
        from google.genai import types

        function_declarations = [
            types.FunctionDeclaration(
                name=spec.name, description=spec.description, parameters_json_schema=spec.parameters_schema
            )
            for spec in tool_specs
        ]
        return types.Tool(function_declarations=function_declarations)

    @staticmethod
    def _to_model_turn(response: Any) -> ModelTurn:
        # Defensive against either a bare FunctionCall or a wrapper exposing a
        # nested `.function_call` attribute for each item in
        # `response.function_calls`: this project's own testing could not
        # independently confirm the exact shape against a live API response
        # at implementation time, so both are handled rather than assumed.
        raw_function_calls = getattr(response, "function_calls", None) or []
        calls = []
        for index, item in enumerate(raw_function_calls):
            fc = getattr(item, "function_call", item)
            name = getattr(fc, "name", None)
            args = dict(getattr(fc, "args", None) or {})
            call_id = getattr(item, "id", None) or getattr(fc, "id", None) or f"call_{index}"
            if name:
                calls.append(ToolCall(call_id=str(call_id), name=name, arguments=args))

        # The SDK warns when .text is read from a response that contains
        # function calls, so only read it for a plain text answer.
        text = None if calls else getattr(response, "text", None)
        raw_content = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            raw_content = getattr(candidates[0], "content", None)

        return ModelTurn(function_calls=tuple(calls), text=text, raw_content=raw_content)


def create_gemini_client():
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    if os.environ.get("GEMINI_API_KEY_POOL"):
        from src.agent.key_pool import PooledGeminiClient, load_key_pool

        return PooledGeminiClient(load_key_pool(), model)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiConfigurationError("GEMINI_API_KEY is not set.")
    return GeminiClient(api_key=api_key, model=model)
