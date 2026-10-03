"""External analysis-timeout guard.

Wraps a full agent run in a hard wall-clock deadline without touching the
bounded tool-turn loop inside the frozen src/agent/single_agent.py -- one
stdlib primitive (concurrent.futures), not a distributed cancellation system.

Caveat, documented rather than hidden: Python threads cannot be forcibly
killed, so a timed-out call keeps running in the background after
run_with_timeout returns; its result is simply discarded. Harmless for
correctness (nothing from an abandoned call is written anywhere), but worth
knowing if you're watching resource usage during a live demo.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeoutError
from typing import Callable, TypeVar

T = TypeVar("T")

# The real 6-case sample measured Architecture B's median real-mode latency
# at ~20.8s (docs/final_evaluation.md) -- this leaves real headroom above
# normal behavior for either architecture, while still giving a hard
# operational bound instead of none at all.
MAX_ANALYSIS_SECONDS = 45.0


def run_with_timeout(fn: Callable[[], T], timeout_seconds: float = MAX_ANALYSIS_SECONDS) -> T:
    """Runs fn() in a worker thread with a hard wall-clock deadline.

    Raises the stdlib builtin TimeoutError (not asyncio's) if fn() doesn't
    finish in time -- callers decide what that means for their own return
    type, since there's no generic "timed-out result" to invent here.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_seconds)
    except _FutureTimeoutError:
        raise TimeoutError(f"Analysis did not complete within {timeout_seconds:.0f}s") from None
    finally:
        # wait=False: never block the caller on an abandoned, still-running
        # thread -- that would defeat the point of a hard deadline.
        executor.shutdown(wait=False)
