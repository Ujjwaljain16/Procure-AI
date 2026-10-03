"""The UI has no authentication, so it must not be reachable from the network by default."""

from __future__ import annotations

from pathlib import Path

import run_local

ROOT = Path(__file__).resolve().parents[1]


def test_default_ui_address_is_loopback():
    assert run_local.ui_bind_address({}) == "127.0.0.1"
    cmd = run_local.streamlit_command({})
    assert cmd[cmd.index("--server.address") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--server.port") + 1] == "8501"


def test_external_exposure_requires_an_explicit_opt_in():
    assert run_local.ui_bind_address({"PROCUREAI_ALLOW_EXTERNAL": "0"}) == "127.0.0.1"
    assert run_local.ui_bind_address({"PROCUREAI_ALLOW_EXTERNAL": "true"}) == "127.0.0.1"
    assert run_local.ui_bind_address({"PROCUREAI_ALLOW_EXTERNAL": "1"}) == "0.0.0.0"


def test_streamlit_config_file_also_pins_loopback():
    assert 'address = "127.0.0.1"' in (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")


def test_mock_api_is_started_on_loopback():
    assert '"127.0.0.1"' in (ROOT / "run_local.py").read_text(encoding="utf-8")
