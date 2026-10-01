from __future__ import annotations

from src.contracts import Architecture, ProcurementDecision


def handle_request(request_id: str, architecture: Architecture = "single") -> ProcurementDecision:
    """Assessment adapter.

    Keep this function callable by the public/hidden evaluation harness.
    """
    if architecture == "single":
        from src.agent.single_agent import run_single_agent

        return run_single_agent(request_id)
    if architecture == "staged":
        from src.agent.staged_agent import run_staged_agent

        return run_staged_agent(request_id)
    raise ValueError(f"Unknown architecture: {architecture!r}")
