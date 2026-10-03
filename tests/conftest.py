"""Test-session environment.

The suite is hermetic by default: Gemini keys from a local .env are removed
from the environment, so no test can reach the live API by accident and spend
quota. Real-API tests opt in explicitly with RUN_REAL_GEMINI_TESTS=1, which
loads .env as run_local.py does.

The vendor-risk service is hermetic in the same way. The evidence preflight
always consults it, so whether a test passes must not depend on whether a
mock_api server happens to be running on port 8001. By default every lookup
is treated as unreachable. A test that needs a live answer requests the
``live_vendor_records`` fixture, which serves the same records the mock serves,
from data/vendor_risk.json, without HTTP.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

from src.tools import vendor_risk as vendor_risk_tool

_GEMINI_VARS = ("GEMINI_API_KEY", "GEMINI_API_KEY_POOL")
_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
_VENDOR_RECORDS = Path(__file__).resolve().parents[1] / "data" / "vendor_risk.json"

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


def _http_status_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.fixture(autouse=True)
def _vendor_service_unreachable_by_default(monkeypatch):
    """Every vendor-risk lookup fails as an unreachable service unless a test says otherwise."""

    def unreachable(name, timeout_seconds=3.0):
        raise requests.ConnectionError("vendor-risk service is disabled for the test suite")

    monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", unreachable)


@pytest.fixture
def live_vendor_records(monkeypatch):
    """Answer vendor-risk lookups with the records mock_api serves, read from the same data file, without HTTP."""
    records = json.loads(_VENDOR_RECORDS.read_text(encoding="utf-8"))

    def lookup(name, timeout_seconds=3.0):
        if name not in records:
            raise _http_status_error(404)
        return {"vendor_name": name, **records[name]}

    monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", lookup)
    return records
