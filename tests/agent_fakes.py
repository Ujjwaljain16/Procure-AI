"""A scripted fake Gemini client shared by the agent test files.

Implements the same three-method interface as
``src.agent.gemini_adapter.GeminiClient`` (``generate_turn`` /
``generate_structured`` / ``build_function_response_content``) with
programmer-supplied canned responses, so agent tests never touch the real
``google.genai`` SDK or require an API key.
"""

from __future__ import annotations

from typing import Optional, Union

from src.agent.gemini_adapter import ModelTurn, ToolCall
from src.agent.schemas import AgentSynthesis


def tool_call(name: str, **arguments) -> ToolCall:
    return ToolCall(call_id=f"call_{name}", name=name, arguments=arguments)


def tool_turn(*calls: ToolCall) -> ModelTurn:
    return ModelTurn(function_calls=tuple(calls), text=None, raw_content=object())


def stop_turn(text: str = "") -> ModelTurn:
    """A turn where the model makes no further tool calls."""
    return ModelTurn(function_calls=(), text=text, raw_content=object())


class ScriptedGeminiClient:
    """`turns`: ModelTurn objects returned from successive `generate_turn`
    calls, in order. `structured_result`: what `generate_structured` returns
    -- an AgentSynthesis, None, or an Exception instance to raise.
    `raise_on_turn_index`: if set, `generate_turn` raises a RuntimeError on
    that 0-based call instead of returning a scripted turn.
    """

    def __init__(
        self,
        turns: list[ModelTurn],
        structured_result: Union[AgentSynthesis, None, Exception] = None,
        raise_on_turn_index: Optional[int] = None,
    ):
        self._turns = list(turns)
        self._structured_result = structured_result
        self._raise_on_turn_index = raise_on_turn_index
        self.turn_calls = 0
        self.structured_calls = 0
        self.turn_call_log: list[tuple] = []
        self.function_response_log: list[tuple] = []

    def generate_turn(self, contents, tool_specs, system_instruction) -> ModelTurn:
        if self._raise_on_turn_index is not None and self.turn_calls == self._raise_on_turn_index:
            self.turn_calls += 1
            raise RuntimeError("simulated Gemini failure during a tool-gathering turn")
        self.turn_call_log.append((len(contents), [spec.name for spec in tool_specs], system_instruction))
        turn = self._turns[self.turn_calls]
        self.turn_calls += 1
        return turn

    def generate_structured(self, contents, system_instruction) -> Optional[AgentSynthesis]:
        self.structured_calls += 1
        if isinstance(self._structured_result, Exception):
            raise self._structured_result
        return self._structured_result

    def build_function_response_content(self, call: ToolCall, result: dict):
        self.function_response_log.append((call.name, result))
        return {"role": "tool", "function_response_for": call.name, "result": result}
