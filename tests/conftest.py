"""Test-session environment.

The suite is hermetic by default: Gemini keys from a local .env are removed
from the environment, so no test can reach the live API by accident and spend
quota. Real-API tests opt in explicitly with RUN_REAL_GEMINI_TESTS=1, which
loads .env as run_local.py does.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_GEMINI_VARS = ("GEMINI_API_KEY", "GEMINI_API_KEY_POOL")
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

if os.environ.get("RUN_REAL_GEMINI_TESTS") == "1":
    load_dotenv(_ENV_FILE, override=False)
else:
    for name in _GEMINI_VARS:
        os.environ.pop(name, None)
    _non_gemini = {}
    if _ENV_FILE.exists():
        from dotenv import dotenv_values

        _non_gemini = {k: v for k, v in dotenv_values(_ENV_FILE).items() if k not in _GEMINI_VARS and v is not None}
    for key, value in _non_gemini.items():
        os.environ.setdefault(key, value)
