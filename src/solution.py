from __future__ import annotations

import time

from src.contracts import Architecture, ProcurementDecision, RunTelemetry


def _timeout_decision(request_id: str, architecture: Architecture, elapsed_ms: float) -> ProcurementDecision:
    """Conservative result for a run that hit the deadline. Counts are unknown
    (None), not zero, and no approval list is implied: the deterministic
    policy result was never produced for this run."""
    from src.agent.timeout_guard import MAX_ANALYSIS_SECONDS

    return ProcurementDecision(
        request_id=request_id,
        recommendation=(
            f"Analysis did not complete within {MAX_ANALYSIS_SECONDS:.0f}s; no policy result is available. Manual review required."
        ),
        next_step="A human reviewer should evaluate this request manually; no required approvals were determined automatically.",
        risk_flags=["analysis_timeout"],
        human_review_required=True,
        telemetry=RunTelemetry(architecture=architecture, llm_calls=None, tool_calls=None, latency_ms=elapsed_ms),
    )


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter.

    Keep this function callable by the public/hidden evaluation harness.

    Runs a narrow structural pre-analysis gate (src/data_access.py::
    get_request_validated) before any LLM call -- an unknown request_id
    still raises KeyError, a structurally broken record raises
    MalformedRequestError, neither is ever silently turned into a fabricated
    decision. The whole run is also bounded by a hard wall-clock deadline
    (src/agent/timeout_guard.py); a timeout degrades to a conservative,
    human-review decision instead of hanging indefinitely.
    """
    from src.agent.timeout_guard import run_with_timeout
    from src.data_access import get_request_validated

    get_request_validated(request_id)

    if architecture == "single":
        from src.agent.single_agent import run_single_agent

        runner = lambda: run_single_agent(request_id)
    elif architecture == "staged":
        from src.agent.staged_agent import run_staged_agent

        runner = lambda: run_staged_agent(request_id)
    else:
        raise ValueError(f"Unknown architecture: {architecture!r}")

    started = time.monotonic()
    try:
        return run_with_timeout(runner)
    except TimeoutError:
        return _timeout_decision(request_id, architecture, (time.monotonic() - started) * 1000)
