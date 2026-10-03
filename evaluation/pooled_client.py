"""Compatibility re-export: the key-pool implementation lives in
``src/agent/key_pool.py`` so the production app and the evaluation harness
share one code path. Keys come only from ``GEMINI_API_KEY_POOL`` and are
never logged or written anywhere.
"""

from __future__ import annotations

from src.agent.key_pool import (  # noqa: F401
    POOL_ENV_VAR,
    PooledGeminiClient,
    PooledStagedGeminiClient,
    is_rotatable_error,
    load_key_pool,
)
