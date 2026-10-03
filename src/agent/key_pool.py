"""Multi-key pooling for the Gemini clients.

The free tier caps each key at a small number of requests per day (and a
per-minute cap). Several keys can be used together: this wrapper holds one
real client per key and rotates to the next key when one is exhausted
(HTTP 429 / RESOURCE_EXHAUSTED) or transiently overloaded (HTTP 503 /
UNAVAILABLE). Each real request still counts as one attempt, so telemetry
keeps meaning "API calls made".

Keys come only from the environment variable ``GEMINI_API_KEY_POOL``
(comma-separated). They are never written to any file, never printed, and
only the key *index* is ever logged.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from src.agent.gemini_adapter import GeminiClient, ModelTurn
from src.agent.schemas import AgentSynthesis

logger = logging.getLogger(__name__)

POOL_ENV_VAR = "GEMINI_API_KEY_POOL"
_ROTATABLE_MARKERS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")


def load_key_pool(env_var: str = POOL_ENV_VAR) -> list[str]:
    raw = os.environ.get(env_var, "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError(f"No keys found in ${env_var}. Set it to a comma-separated list of API keys.")
    return keys


def is_rotatable_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker in text for marker in _ROTATABLE_MARKERS)


class PooledGeminiClient:
    """Drop-in for GeminiClientProtocol, backed by several real clients."""

    _client_class = GeminiClient
    counts_api_attempts = True  # the underlying real clients record every HTTP attempt, rotation included

    @property
    def model_name(self) -> str:
        return self._clients[0].model_name

    def __init__(self, keys: list[str], model: str):
        if not keys:
            raise ValueError("PooledGeminiClient needs at least one key")
        self._clients = [self._client_class(api_key=k, model=model) for k in keys]
        self._index = 0
        self.real_calls_made = 0
        self.rotations = 0

    @property
    def pool_size(self) -> int:
        return len(self._clients)

    def _try_each(self, method_name: str, *args):
        last_exc: Optional[Exception] = None
        for _ in range(len(self._clients)):
            client = self._clients[self._index]
            try:
                self.real_calls_made += 1
                return getattr(client, method_name)(*args)
            except Exception as exc:
                last_exc = exc
                if is_rotatable_error(exc):
                    logger.warning("gemini key pool: key index %d unavailable, rotating", self._index)
                    self._index = (self._index + 1) % len(self._clients)
                    self.rotations += 1
                    continue
                raise
        raise last_exc  # every key in the pool is unavailable

    def generate_turn(self, contents, tool_specs, system_instruction) -> ModelTurn:
        return self._try_each("generate_turn", contents, tool_specs, system_instruction)

    def generate_structured(self, contents, system_instruction) -> Optional[AgentSynthesis]:
        return self._try_each("generate_structured", contents, system_instruction)

    def build_function_response_content(self, call, result):
        return self._clients[self._index].build_function_response_content(call, result)


def _staged_client_class():
    from src.agent.staged_gemini_adapter import StagedGeminiClient

    return StagedGeminiClient


class PooledStagedGeminiClient(PooledGeminiClient):
    """Same pooling behavior, additionally exposing generate_analyst_report."""

    def __init__(self, keys: list[str], model: str):
        staged_class = _staged_client_class()
        if not keys:
            raise ValueError("PooledStagedGeminiClient needs at least one key")
        self._clients = [staged_class(api_key=k, model=model) for k in keys]
        self._index = 0
        self.real_calls_made = 0
        self.rotations = 0

    def generate_analyst_report(self, contents, system_instruction):
        return self._try_each("generate_analyst_report", contents, system_instruction)
