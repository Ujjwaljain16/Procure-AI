"""Optional real end-to-end smoke test against the live Gemini API.

Skipped automatically when no GEMINI_API_KEY is available (e.g. in CI or a
fresh clone) -- the rest of the test suite never depends on this file or on
network access. Run manually with a real key present (via .env or the
environment) to exercise one real request through the full single-agent
pipeline, including a real function-calling round trip and a real
structured-output call.

Deliberately limited to exactly ONE real request: a full agent run can
itself consume several Gemini calls (multiple tool-gathering turns plus a
final synthesis call), so this file intentionally does not iterate over
several requests or architectures here.
"""

from __future__ import annotations

import os

import pytest

from src.agent.single_agent import run_single_agent

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"), reason="no GEMINI_API_KEY supplied -- real smoke test not run"
)


def test_real_single_agent_end_to_end_smoke():
    decision = run_single_agent("REQ-1001")

    assert decision.request_id == "REQ-1001"
    assert decision.recommendation
    assert decision.next_step
    assert decision.telemetry is not None
    assert decision.telemetry.llm_calls is not None and decision.telemetry.llm_calls > 0
