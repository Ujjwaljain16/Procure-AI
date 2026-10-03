"""Whether live model analysis is enabled, read from the process environment only.

The application never reads a .env file. Local development sets variables in the shell
(for example `set GEMINI_API_KEY=...` on Windows, `export GEMINI_API_KEY=...` elsewhere)
and then starts the app. The status shown in the UI is computed here, so the UI and the
tests agree on what "enabled" means.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

KEY_VARS = ("GEMINI_API_KEY", "GEMINI_API_KEY_POOL")


def live_analysis_status(env: Optional[Mapping[str, str]] = None) -> tuple[bool, str]:
    """Return (enabled, message). The message is the exact text the UI shows.

    Direct Gemini (GEMINI_API_KEY or GEMINI_API_KEY_POOL) is used when set. Otherwise an
    OpenAI-compatible provider is used when CLOSEROUTER_API_KEY is set (CloseRouter, or any
    OpenAI-compatible endpoint named by CLOSEROUTER_BASE_URL)."""
    source = os.environ if env is None else env
    if source.get("GEMINI_API_KEY_POOL"):
        return True, "Live analysis: Enabled (key pool from GEMINI_API_KEY_POOL)"
    if source.get("GEMINI_API_KEY"):
        return True, "Live analysis: Enabled"
    if source.get("CLOSEROUTER_API_KEY"):
        model = source.get("CLOSEROUTER_MODEL") or "google/gemini-3.7-flash"
        return True, f"Live analysis: Enabled (OpenAI-compatible endpoint, model {model})"
    return False, "Live analysis: Disabled — GEMINI_API_KEY not configured"
