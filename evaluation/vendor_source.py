"""Deterministic vendor-risk source for evaluation runs.

The evidence preflight consults the vendor-risk service for every request. If an
evaluation depended on whether mock_api happened to be listening, the same
code and cases could give different results on different machines. The frozen
baseline was recorded with the mock up, and the mock serves exactly the records
in data/vendor_risk.json, so evaluation serves those records directly, with no
network involved. Every answer, including "no such vendor", is the one the mock
would give.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import requests

from src.tools import vendor_risk as vendor_risk_tool

ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = ROOT / "data" / "vendor_risk.json"
SOURCE_LABEL = "data/vendor_risk.json served in-process (mock_api-equivalent, no network)"


def _http_status_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


def records_lookup(records: dict):
    """A vendor_client.get_vendor_risk replacement that answers exactly as mock_api/app.py does:
    404 for an unknown vendor, 503 for a record flagged force_error, otherwise the record."""

    def lookup(name, timeout_seconds=3.0):
        record = records.get(name)
        if record is None:
            raise _http_status_error(404)
        if record.get("force_error"):
            raise _http_status_error(503)
        return {"vendor_name": name, **record}

    return lookup


def load_records() -> dict:
    return json.loads(RECORDS_PATH.read_text(encoding="utf-8"))


@contextmanager
def serve_vendor_records_from_data() -> Iterator[None]:
    original = vendor_risk_tool.vendor_client.get_vendor_risk
    vendor_risk_tool.vendor_client.get_vendor_risk = records_lookup(load_records())
    try:
        yield
    finally:
        vendor_risk_tool.vendor_client.get_vendor_risk = original
