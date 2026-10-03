"""CloseRouter adapter: Gemini models through CloseRouter's OpenAI-compatible chat-completions endpoint.

It implements the same interface as the Gemini adapter (src/agent/gemini_adapter.py), so the orchestrators
and the policy path are unchanged. Only the transport differs.

Configuration (environment only; never read from a file):
    CLOSEROUTER_API_KEY   required for live calls
    CLOSEROUTER_MODEL     optional; default google/gemini-3-flash
    CLOSEROUTER_BASE_URL  optional; default https://api.closerouter.dev/v1

Attempts: record_attempt() runs immediately before each HTTP request, so a failed request is one attempt, the
same convention as the Gemini adapter. The counter is observational; it does not affect any decision.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional, Sequence

import requests

from src.agent.attempts import record_attempt
from src.agent.gemini_adapter import GENERATION_TEMPERATURE, GeminiConfigurationError, ModelOutputError, ModelTurn, ToolCall
from src.agent.schemas import AgentSynthesis
from src.agent.staged_schemas import AnalystReport

DEFAULT_MODEL = "google/gemini-3-flash"
DEFAULT_BASE_URL = "https://api.closerouter.dev/v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
KEY_ENV = "CLOSEROUTER_API_KEY"
MODEL_ENV = "CLOSEROUTER_MODEL"
BASE_URL_ENV = "CLOSEROUTER_BASE_URL"


def extract_json_object(text: str) -> str:
    """Return the first complete JSON object in a model reply. Models in JSON mode sometimes wrap the object in a
    code fence or add a sentence before it. Those wrappers are removed here. The object itself is still validated
    against the Pydantic model, so a reply that is not a valid object still fails."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_line_end = stripped.find("\n")
        stripped = stripped[first_line_end + 1 :] if first_line_end >= 0 else stripped[3:]
        stripped = stripped.rsplit("```", 1)[0]
    start = stripped.find("{")
    if start < 0:
        return stripped
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return stripped[start:]


class _RequestsHttp:
    """The HTTP boundary: one method, post(). Tests and the evaluator's instrumentation replace this object."""

    def post(self, url: str, headers: dict, json: dict, timeout: float):
        return requests.post(url, headers=headers, json=json, timeout=timeout)


class CloseRouterClient:
    counts_api_attempts = True

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL, http=None, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        if not api_key:
            raise GeminiConfigurationError("CLOSEROUTER_API_KEY is not set.")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._http = http if http is not None else _RequestsHttp()
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model

    # --- the interface the orchestrators call ---------------------------------------------------------

    def generate_turn(self, contents: list, tool_specs: Sequence, system_instruction: str) -> ModelTurn:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(system_instruction, contents),
            "temperature": GENERATION_TEMPERATURE,
        }
        if tool_specs:
            payload["tools"] = [self._tool(spec) for spec in tool_specs]
        message = self._chat(payload)
        calls = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            calls.append(ToolCall(call_id=str(call.get("id") or f"call_{len(calls)}"), name=fn.get("name") or "", arguments=self._arguments(fn.get("arguments"))))
        calls = [c for c in calls if c.name]
        text = None if calls else (message.get("content") or "")
        return ModelTurn(function_calls=tuple(calls), text=text, raw_content=message)

    def generate_structured(self, contents: list, system_instruction: str) -> AgentSynthesis:
        return self._structured(contents, system_instruction, AgentSynthesis)

    def build_function_response_content(self, call: ToolCall, result: dict) -> Any:
        return {"role": "tool", "tool_call_id": call.call_id, "name": call.name, "content": json.dumps(result, default=str)}

    # --- internals ------------------------------------------------------------------------------------

    def _structured(self, contents: list, system_instruction: str, schema_model) -> Any:
        schema = json.dumps(schema_model.model_json_schema(), sort_keys=True)
        instruction = f"{system_instruction}\n\nReply with a single JSON object that matches this JSON schema, and nothing else:\n{schema}"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(instruction, contents),
            "temperature": GENERATION_TEMPERATURE,
            "response_format": {"type": "json_object"},
        }
        message = self._chat(payload)
        text = message.get("content") or ""
        if not text.strip():
            raise ModelOutputError("EMPTY_RESPONSE")
        try:
            return schema_model.model_validate_json(extract_json_object(text))
        except Exception as exc:
            raise ModelOutputError("PARSE_FAILED", type(exc).__name__) from exc

    def _chat(self, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        record_attempt()
        response = self._http.post(f"{self._base_url}/chat/completions", headers=headers, json=payload, timeout=self._timeout)
        response.raise_for_status()  # a non-2xx status raises requests.HTTPError, classified as a transport failure
        try:
            choice = response.json()["choices"][0]
            return choice["message"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelOutputError("PARSE_FAILED", type(exc).__name__) from exc

    @staticmethod
    def _tool(spec) -> dict:
        return {"type": "function", "function": {"name": spec.name, "description": spec.description, "parameters": spec.parameters_schema}}

    @staticmethod
    def _arguments(raw) -> dict:
        if raw in (None, ""):
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ModelOutputError("PARSE_FAILED", type(exc).__name__) from exc
        if not isinstance(value, dict):
            raise ModelOutputError("PARSE_FAILED", "NotAnObject")
        return value

    @staticmethod
    def _messages(system_instruction: str, contents: list) -> list[dict]:
        """Convert the orchestrators' history to chat messages. Gemini-style dicts ({"role", "parts"}) become
        plain text messages; dicts already in chat form (assistant turns with tool calls, tool results) pass through."""
        messages: list[dict] = [{"role": "system", "content": system_instruction}]
        for item in contents:
            if not isinstance(item, dict):
                raise ModelOutputError("PARSE_FAILED", "UnsupportedHistoryItem")
            if "parts" in item:
                role = "assistant" if item.get("role") == "model" else "user"
                text = "".join(part.get("text", "") for part in item["parts"] if isinstance(part, dict))
                messages.append({"role": role, "content": text})
            else:
                messages.append(item)
        return messages


class CloseRouterStagedClient(CloseRouterClient):
    """Adds the analyst's structured report, mirroring StagedGeminiClient."""

    def generate_analyst_report(self, contents: list, system_instruction: str) -> AnalystReport:
        return self._structured(contents, system_instruction, AnalystReport)


def create_closerouter_client(staged: bool = False):
    api_key = os.environ.get(KEY_ENV)
    if not api_key:
        raise GeminiConfigurationError("CLOSEROUTER_API_KEY is not set.")
    model = os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    base_url = os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
    cls = CloseRouterStagedClient if staged else CloseRouterClient
    return cls(api_key=api_key, model=model, base_url=base_url)
