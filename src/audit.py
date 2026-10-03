"""Minimal append-only record of each analysis run: what the copilot saw and concluded.

One JSON object per line, one line per analysis attempt, including attempts that failed.
Deliberately small. The record holds identifiers, a hash of the submitted request, evidence
identifiers, the deterministic policy fields, and run metadata. It holds no request prose,
no model prose, no API key, and no personal data beyond the requester identifier that the
request itself carries.

Location: PROCUREAI_AUDIT_LOG if set, else runs/audit.jsonl (git-ignored). Writing the log is
best-effort: a failure to write never changes the decision shown to the user.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
AUDIT_ENV = "PROCUREAI_AUDIT_LOG"
DEFAULT_PATH = ROOT / "runs" / "audit.jsonl"


def audit_path() -> Path:
    override = os.environ.get(AUDIT_ENV)
    return Path(override) if override else DEFAULT_PATH


def input_hash(raw_request: dict) -> str:
    """SHA-256 of the canonical JSON of the submitted request. The request itself is not stored."""
    canonical = json.dumps(raw_request, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def git_revision() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip() or None
    except Exception:
        return None


def evidence_ids_for(decision, registry) -> list[str]:
    """Identifiers of the evidence items the final decision cites, in the registry's own ID scheme."""
    if decision is None or registry is None:
        return []
    cited = set()
    for item in decision.evidence:
        cited.add((item.source, item.finding, item.reference))
    return [eid for eid, item in registry.evidence_index() if (item.source, item.finding, item.reference) in cited]


def build_record(
    *,
    request_id: str,
    raw_request: Optional[dict],
    architecture: str,
    status: str,
    decision=None,
    registry=None,
    model: Optional[str] = None,
    revision: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    record: dict[str, Any] = {
        "timestamp": stamp,
        "request_id": request_id,
        "input_hash": input_hash(raw_request) if raw_request is not None else None,
        "architecture": architecture,
        "model": model,
        "git_revision": revision if revision is not None else git_revision(),
        "run_status": status,
        "evidence_ids": evidence_ids_for(decision, registry),
    }
    if decision is not None:
        record["required_approvals"] = list(decision.required_approvals)
        record["risk_flags"] = list(decision.risk_flags)
        record["missing_information"] = list(decision.missing_information)
        record["human_review_required"] = decision.human_review_required
    return record


def append_record(record: dict[str, Any], path: Optional[Path] = None) -> None:
    target = path or audit_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        # Best effort: the user's decision must not depend on the log. Record only the error class.
        logger.warning("audit record not written: %s", type(exc).__name__)
