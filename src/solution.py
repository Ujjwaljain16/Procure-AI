from __future__ import annotations

import logging
import time

from src.contracts import Architecture, ProcurementDecision, RunTelemetry

logger = logging.getLogger(__name__)


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


def _unexpected_failure_decision(request_id: str, architecture: Architecture, elapsed_ms: float) -> ProcurementDecision:
    return ProcurementDecision(
        request_id=request_id,
        recommendation="Policy evaluation could not be completed. Manual review required.",
        next_step="A human reviewer should evaluate this request manually; the automated analysis hit an internal error.",
        risk_flags=["analysis_failed"],
        human_review_required=True,
        telemetry=RunTelemetry(architecture=architecture, llm_calls=None, tool_calls=None, latency_ms=elapsed_ms),
    )


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter.

    Keep this function callable by the public/hidden evaluation harness.

    Runs a narrow structural pre-analysis gate (src/data_access.py::
    get_request_validated) before any LLM call -- an unknown request_id still
    raises KeyError and a structurally broken record raises
    MalformedRequestError; neither is turned into a fabricated decision. The run
    is bounded by a hard deadline (src/agent/timeout_guard.py): a timeout
    degrades to a conservative human-review decision and tells the worker to
    stop at its next checkpoint. An unexpected internal error is logged with
    its traceback and returned as an explicit human-review decision, never a
    raw traceback to the caller.
    """
    from src.agent.timeout_guard import run_with_timeout
    from src.data_access import get_request_validated

    get_request_validated(request_id)

    if architecture == "single":
        from src.agent.single_agent import run_single_agent

        runner = lambda cancel: run_single_agent(request_id, cancel_event=cancel)
    elif architecture == "staged":
        from src.agent.staged_agent import run_staged_agent

        runner = lambda cancel: run_staged_agent(request_id, cancel_event=cancel)
    else:
        raise ValueError(f"Unknown architecture: {architecture!r}")

    started = time.monotonic()
    try:
        return run_with_timeout(runner)
    except TimeoutError:
        return _timeout_decision(request_id, architecture, (time.monotonic() - started) * 1000)
    except Exception:
        logger.exception("request=%s architecture=%s unexpected internal error", request_id, architecture)
        return _unexpected_failure_decision(request_id, architecture, (time.monotonic() - started) * 1000)
