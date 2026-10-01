"""Multi-key pooling wrapper for real-API evaluation runs.

The free tier's quota (both the 20-requests/day cap and the 5-requests/minute
cap observed in earlier phases) is scarce enough that a real A-vs-B sample
across several cases can exhaust a single key quickly. This module wraps
several real ``GeminiClient``/``StagedGeminiClient`` instances (one per API
key) and transparently rotates to the next key when one returns a quota
error (HTTP 429), retrying the same call once per remaining key before
giving up. This does not change what is measured -- llm_calls/tool_calls
still count exactly one attempt per real API call made, including the ones
that got a 429 and were retried on a different key (a real request was still
sent to Google's servers for each).

Keys are never read from any file in this repository -- only from a
comma-separated environment variable (``GEMINI_API_KEY_POOL`` by default),
which the operator sets locally before running the evaluator with ``--real
--key-pool``. Never logged, never printed, never written to any results
file.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from src.agent.gemini_adapter import GeminiClient, ModelTurn
from src.agent.schemas import AgentSynthesis
from src.agent.staged_gemini_adapter import StagedGeminiClient
from src.agent.staged_schemas import AnalystReport

logger = logging.getLogger(__name__)


def load_key_pool(env_var: str = "GEMINI_API_KEY_POOL") -> list[str]:
    raw = os.environ.get(env_var, "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError(f"No keys found in ${env_var}. Set it to a comma-separated list of API keys.")
    return keys


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


class PooledGeminiClient:
    """Drop-in for GeminiClientProtocol, backed by several real GeminiClient
    instances. Used for Architecture A's real-API evaluation.
    """

    def __init__(self, keys: list[str], model: str):
        self._clients = [GeminiClient(api_key=k, model=model) for k in keys]
        self._index = 0
        self.real_calls_made = 0
        self.rotations = 0

    def _try_each(self, method_name: str, *args):
        last_exc: Optional[Exception] = None
        for _ in range(len(self._clients)):
            client = self._clients[self._index]
            try:
                self.real_calls_made += 1
                return getattr(client, method_name)(*args)
            except Exception as exc:
                last_exc = exc
                if _is_quota_error(exc):
                    logger.warning("pooled client: key index %d exhausted, rotating", self._index)
                    self._index = (self._index + 1) % len(self._clients)
                    self.rotations += 1
                    continue
                raise
        raise last_exc  # every key in the pool is exhausted

    def generate_turn(self, contents, tool_specs, system_instruction) -> ModelTurn:
        return self._try_each("generate_turn", contents, tool_specs, system_instruction)

    def generate_structured(self, contents, system_instruction) -> Optional[AgentSynthesis]:
        return self._try_each("generate_structured", contents, system_instruction)

    def build_function_response_content(self, call, result):
        return self._clients[self._index].build_function_response_content(call, result)


class PooledStagedGeminiClient(PooledGeminiClient):
    """Same pooling behavior, additionally exposing generate_analyst_report
    for Architecture B."""

    def __init__(self, keys: list[str], model: str):
        self._clients = [StagedGeminiClient(api_key=k, model=model) for k in keys]
        self._index = 0
        self.real_calls_made = 0
        self.rotations = 0

    def generate_analyst_report(self, contents, system_instruction) -> Optional[AnalystReport]:
        return self._try_each("generate_analyst_report", contents, system_instruction)
