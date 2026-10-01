"""A scripted fake staged-Gemini client, mirroring tests/agent_fakes.py's
ScriptedGeminiClient but additionally implementing generate_analyst_report
for Architecture B's analyst stage. Kept separate from agent_fakes.py so
Architecture A's existing tests/fakes are never touched.
"""

from __future__ import annotations

from typing import Optional, Union

from src.agent.gemini_adapter import ModelTurn, ToolCall
from src.agent.schemas import AgentSynthesis
from src.agent.staged_schemas import AnalystReport


class ScriptedStagedGeminiClient:
    def __init__(
        self,
        turns: list[ModelTurn],
        analyst_report: Union[AnalystReport, None, Exception] = None,
        structured_result: Union[AgentSynthesis, None, Exception] = None,
        raise_on_turn_index: Optional[int] = None,
    ):
        self._turns = list(turns)
        self._analyst_report = analyst_report
        self._structured_result = structured_result
        self._raise_on_turn_index = raise_on_turn_index
        self.turn_calls = 0
        self.analyst_report_calls = 0
        self.structured_calls = 0
        self.function_response_log: list[tuple] = []

    def generate_turn(self, contents, tool_specs, system_instruction) -> ModelTurn:
        if self._raise_on_turn_index is not None and self.turn_calls == self._raise_on_turn_index:
            self.turn_calls += 1
            raise RuntimeError("simulated Gemini failure during analyst tool turn")
        turn = self._turns[self.turn_calls]
        self.turn_calls += 1
        return turn

    def generate_analyst_report(self, contents, system_instruction) -> Optional[AnalystReport]:
        self.analyst_report_calls += 1
        if isinstance(self._analyst_report, Exception):
            raise self._analyst_report
        return self._analyst_report

    def generate_structured(self, contents, system_instruction) -> Optional[AgentSynthesis]:
        self.structured_calls += 1
        if isinstance(self._structured_result, Exception):
            raise self._structured_result
        return self._structured_result

    def build_function_response_content(self, call: ToolCall, result: dict):
        self.function_response_log.append((call.name, result))
        return {"role": "tool", "function_response_for": call.name, "result": result}
