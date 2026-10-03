from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


class MalformedRequestError(Exception):
    """Raised when a request record exists (a real request_id) but is
    structurally invalid -- missing a key every request must have, or a
    field holding a value that can't be used as its expected type at all.

    Deliberately narrow: this answers "is this a valid request object to
    hand to the agent," never "should this request be approved" -- it must
    never duplicate any check src/policy_engine.py already makes (missing
    business fields, budget sufficiency, approval thresholds, security/
    privacy/legal triggers). Distinct from KeyError, which means "no such
    request_id" rather than "this request_id's record is broken."
    """


def load_employees() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "employees.csv")


def load_budgets() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "department_budgets.csv")


def load_software_catalog() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "software_catalog.csv")


def load_vendors() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "vendors.csv")


def load_purchase_history() -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "purchase_history.csv")


def load_requests() -> list[dict]:
    return json.loads((DATA_DIR / "requests.json").read_text(encoding="utf-8"))


def get_request(request_id: str) -> dict:
    for request in load_requests():
        if request["request_id"] == request_id:
            return request
    raise KeyError(f"Unknown request_id: {request_id}")


_REQUEST_KEYS_THAT_MUST_EXIST = ("request_id", "requester_id", "product_name", "vendor_name")


def get_request_validated(request_id: str) -> dict:
    """Deterministic pre-analysis gate: get_request() plus a narrow
    structural check, so a broken record fails with a clear,
    specifically-named error before any LLM call is made, instead of
    crashing deep inside RequestFields.from_raw() or evidence-building code
    with an unhelpful generic traceback.

    Checks only structure (keys present, numeric-looking fields are
    numeric-looking) -- never the business rules in src/policy_engine.py.
    """
    request = get_request(request_id)  # KeyError propagates unchanged for an unknown request_id

    missing_keys = [key for key in _REQUEST_KEYS_THAT_MUST_EXIST if not request.get(key)]
    if missing_keys:
        raise MalformedRequestError(f"Request {request_id} is missing required field(s): {', '.join(missing_keys)}")

    cost = request.get("annual_cost_usd")
    if cost is not None:
        try:
            Decimal(str(cost))
        except (InvalidOperation, ValueError):
            raise MalformedRequestError(f"Request {request_id} has a non-numeric annual_cost_usd: {cost!r}") from None

    user_count = request.get("user_count")
    if user_count is not None and not isinstance(user_count, (int, float)):
        raise MalformedRequestError(f"Request {request_id} has a non-numeric user_count: {user_count!r}")

    return request


def load_policy_text() -> str:
    return (DATA_DIR / "procurement_policy.md").read_text(encoding="utf-8")
