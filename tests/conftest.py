"""Load .env (if present) before the test suite runs, exactly like
run_local.py does, so a locally-supplied GEMINI_API_KEY is picked up by any
test that conditionally exercises the real Gemini API.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
