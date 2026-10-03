"""Audit record, live-status banner, and environment-only configuration.

These protect three claims: the audit record holds what the copilot concluded and nothing else;
the banner says whether live analysis is enabled, from the environment alone; and no part of the
application reads a .env file.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src import audit, data_access
from src.agent.single_agent import run_single_agent_with_trace
from src.live_status import live_analysis_status
from tests.agent_fakes import ScriptedGeminiClient, stop_turn
from tests.test_agent_single import _synthesis

ROOT = Path(__file__).resolve().parents[1]
SENTINEL_KEY = "SENTINEL-KEY-AUDIT-TEST"


def _real_run(request_id="REQ-1001"):
    client = ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis(evidence_refs=[]))
    return run_single_agent_with_trace(request_id, client=client)


# --- audit record ----------------------------------------------------------------------------------


def test_record_holds_the_minimal_fields_and_no_prose_or_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SENTINEL_KEY)
    result = _real_run()
    raw = data_access.get_request("REQ-1001")
    record = audit.build_record(
        request_id="REQ-1001", raw_request=raw, architecture="single", status="ok",
        decision=result.decision, registry=result.registry, model="gemini-2.5-flash", revision="abc1234",
    )
    assert set(record) == {
        "timestamp", "request_id", "input_hash", "architecture", "model", "policy_version", "git_revision",
        "worktree_dirty", "run_status", "error_class", "evidence_ids", "required_approvals", "risk_flags",
        "missing_information", "human_review_required",
    }
    assert record["policy_version"] == "2026.09"
    text = json.dumps(record)
    assert SENTINEL_KEY not in text
    assert raw["business_justification"] not in text  # request prose never stored
    assert "Based on the evidence provided." not in text  # model prose never stored
    assert raw["business_justification"][:30] not in text


def test_evidence_ids_are_the_registry_ids_of_the_cited_items():
    result = _real_run()
    retrieved = {eid for eid, _ in result.registry.evidence_index()}
    record = audit.build_record(request_id="REQ-1001", raw_request=None, architecture="single", status="ok",
                                decision=result.decision, registry=result.registry, revision="abc1234")
    assert set(record["evidence_ids"]) <= retrieved


def test_input_hash_is_stable_for_one_request_and_changes_with_the_request():
    raw = data_access.get_request("REQ-1001")
    assert audit.input_hash(raw) == audit.input_hash(dict(raw))
    assert audit.input_hash(raw) != audit.input_hash({**raw, "annual_cost_usd": raw["annual_cost_usd"] + 1})
    assert len(audit.input_hash(raw)) == 64


def test_failed_run_is_recorded_with_its_status_and_no_policy_fields():
    record = audit.build_record(request_id="REQ-1001", raw_request=None, architecture="staged",
                                status="rejected:MalformedRequestError", revision="abc1234")
    assert record["run_status"] == "rejected:MalformedRequestError"
    assert record["input_hash"] is None
    assert "required_approvals" not in record and "risk_flags" not in record


def test_each_append_is_one_json_line_and_the_folder_is_created(tmp_path):
    target = tmp_path / "nested" / "audit.jsonl"
    audit.append_record({"run_status": "ok", "request_id": "A"}, target)
    audit.append_record({"run_status": "timeout", "request_id": "B"}, target)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["request_id"] for line in lines] == ["A", "B"]


def test_a_write_failure_never_raises_into_the_decision_path(tmp_path, caplog):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    audit.append_record({"run_status": "ok"}, blocker / "audit.jsonl")  # must not raise
    assert "audit record not written" in caplog.text


def test_default_location_is_git_ignored_runs_folder_and_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.delenv(audit.AUDIT_ENV, raising=False)
    assert audit.audit_path() == ROOT / "runs" / "audit.jsonl"
    monkeypatch.setenv(audit.AUDIT_ENV, str(tmp_path / "x.jsonl"))
    assert audit.audit_path() == tmp_path / "x.jsonl"
    assert "runs/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


# --- live-status banner ----------------------------------------------------------------------------


def test_banner_is_disabled_with_no_key_and_says_why():
    enabled, message = live_analysis_status({})
    assert enabled is False
    assert message == "Live analysis: Disabled — GEMINI_API_KEY not configured"


def test_banner_is_enabled_with_a_key_and_reports_the_pool_when_used():
    assert live_analysis_status({"GEMINI_API_KEY": "k"}) == (True, "Live analysis: Enabled")
    enabled, message = live_analysis_status({"GEMINI_API_KEY_POOL": "a,b"})
    assert enabled is True and "key pool" in message


def test_banner_reads_the_environment_by_default(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
    assert live_analysis_status()[0] is False


# --- environment-only configuration ----------------------------------------------------------------

ENTRY_POINTS = [ROOT / "app.py", ROOT / "run_local.py", ROOT / "evaluation" / "correctness" / "evaluator.py"]


def _imports_dotenv(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("dotenv"):
            return True
        if isinstance(node, ast.Import) and any(alias.name.startswith("dotenv") for alias in node.names):
            return True
    return False


@pytest.mark.parametrize("path", sorted((ROOT / "src").rglob("*.py")) + ENTRY_POINTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_application_module_reads_a_dotenv_file(path):
    assert not _imports_dotenv(path), f"{path.relative_to(ROOT)} imports dotenv; configuration must come from the environment"


def test_the_dotenv_detector_actually_fires_on_a_loader(tmp_path):
    """Non-vacuity: the static check above must be able to fail. A module that loads .env is flagged."""
    loader = tmp_path / "loads_env.py"
    loader.write_text("from dotenv import load_dotenv\nload_dotenv('.env')\n", encoding="utf-8")
    other = tmp_path / "plain.py"
    other.write_text("import os\nprint(os.environ.get('X'))\n", encoding="utf-8")
    assert _imports_dotenv(loader) is True
    assert _imports_dotenv(other) is False


# --- provenance and error class -------------------------------------------------------------------


def test_dirty_worktree_is_recorded_and_never_changes_the_run_status(monkeypatch):
    raw = data_access.get_request("REQ-1001")
    clean = audit.build_record(request_id="REQ-1001", raw_request=raw, architecture="single", status="ok",
                               revision="69e483d", dirty=False)
    dirty = audit.build_record(request_id="REQ-1001", raw_request=raw, architecture="single", status="ok",
                               revision="69e483d", dirty=True)
    assert clean["worktree_dirty"] is False and dirty["worktree_dirty"] is True
    assert clean["run_status"] == dirty["run_status"] == "ok"
    assert clean["git_revision"] == dirty["git_revision"] == "69e483d"


def test_error_class_is_taken_from_the_run_status():
    assert audit.error_class_for("ok") is None
    assert audit.error_class_for("timeout") == "TimeoutError"
    assert audit.error_class_for("degraded:GeminiConfigurationError") == "GeminiConfigurationError"
    assert audit.error_class_for("rejected:MalformedRequestError") == "MalformedRequestError"
    assert audit.error_class_for("unexpected_error:ValueError") == "ValueError"


def test_worktree_dirty_is_a_boolean_or_none_and_records_no_file_names():
    value = audit.worktree_dirty()
    assert value in (True, False, None)
    record = audit.build_record(request_id="REQ-1001", raw_request=None, architecture="single", status="ok", revision="x")
    assert all(not str(v).endswith((".py", ".md")) for v in record.values() if isinstance(v, str))


def test_banner_names_the_openai_compatible_route_when_only_its_key_is_set():
    enabled, message = live_analysis_status({"CLOSEROUTER_API_KEY": "k", "CLOSEROUTER_MODEL": "m1"})
    assert enabled is True
    assert "OpenAI-compatible endpoint" in message and "m1" in message


def test_direct_gemini_takes_precedence_over_the_openai_compatible_route():
    enabled, message = live_analysis_status({"GEMINI_API_KEY": "g", "CLOSEROUTER_API_KEY": "c"})
    assert message == "Live analysis: Enabled"
