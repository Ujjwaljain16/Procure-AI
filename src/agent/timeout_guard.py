"""External analysis deadline.

Runs a full agent call on a daemon thread with a wall-clock deadline. The
worker receives a ``threading.Event``; when the deadline passes the event is
set, and the orchestration loops check it between turns and before each tool
call, so an abandoned run stops spending quota at the next boundary instead of
running to completion. The thread is a daemon, so the process can still exit.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, TypeVar

T = TypeVar("T")

# B's measured real-mode median is ~20.8s (docs/final_evaluation.md). The
# deadline sits above normal behavior for either architecture; override with
# ANALYSIS_TIMEOUT_SECONDS if a slower model or network needs more room.
DEFAULT_MAX_ANALYSIS_SECONDS = 45.0
MAX_ANALYSIS_SECONDS = float(os.environ.get("ANALYSIS_TIMEOUT_SECONDS", DEFAULT_MAX_ANALYSIS_SECONDS))


def run_with_timeout(fn: Callable[[threading.Event], T], timeout_seconds: float = MAX_ANALYSIS_SECONDS) -> T:
    """Runs ``fn(cancel_event)`` with a hard deadline.

    Raises the stdlib builtin ``TimeoutError`` if it does not finish in time,
    after setting ``cancel_event`` so the worker stops at its next checkpoint.
    Exceptions raised inside ``fn`` are re-raised in the caller unchanged.
    """
    cancel_event = threading.Event()
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["value"] = fn(cancel_event)
        except BaseException as exc:  # re-raised in the caller below
            outcome["error"] = exc

    thread = threading.Thread(target=worker, name="procureai-analysis", daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        cancel_event.set()
        raise TimeoutError(f"Analysis did not complete within {timeout_seconds:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
