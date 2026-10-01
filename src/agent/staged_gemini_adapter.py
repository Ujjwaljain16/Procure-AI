"""Extends ``GeminiClient`` (unmodified, frozen with Architecture A) with one
additional structured-output method for the analyst stage's ``AnalystReport``
schema.

``GeminiClient.generate_structured`` (in ``gemini_adapter.py``) is typed
specifically against ``AgentSynthesis``, since that is the only schema
Architecture A ever needs. Rather than modify that frozen file to make it
generic, this module subclasses it and adds exactly the one method
Architecture B's analyst stage needs -- ``generate_turn`` and
``build_function_response_content`` are inherited unchanged.
"""

from __future__ import annotations

import os
from typing import Optional

from src.agent.gemini_adapter import DEFAULT_MODEL, GeminiClient, GeminiConfigurationError
from src.agent.staged_schemas import AnalystReport


class StagedGeminiClient(GeminiClient):
    def generate_analyst_report(self, contents: list, system_instruction: str) -> Optional[AnalystReport]:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=AnalystReport,
        )
        response = self._client.models.generate_content(model=self._model, contents=contents, config=config)
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, AnalystReport):
            return parsed
        text = getattr(response, "text", None)
        if not text:
            return None
        try:
            return AnalystReport.model_validate_json(text)
        except Exception:
            return None


def create_staged_gemini_client() -> StagedGeminiClient:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiConfigurationError("GEMINI_API_KEY is not set.")
    model = os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    return StagedGeminiClient(api_key=api_key, model=model)
