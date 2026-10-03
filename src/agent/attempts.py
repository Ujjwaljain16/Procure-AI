"""Per-thread count of real model-API attempts.

Every ``generate_content`` call a real client makes records one attempt here, including attempts a
key pool makes while rotating past an exhausted key. A run executes on one thread, so the difference
between two readings is that run's attempts even when several runs share a pooled client.
``llm_calls`` (logical calls the orchestrator asked for) and ``api_attempts`` (HTTP attempts really
made) therefore diverge exactly when quota or availability problems inflate cost and latency.
"""

from __future__ import annotations

import threading

_local = threading.local()


def record_attempt() -> None:
    _local.count = getattr(_local, "count", 0) + 1


def current_attempts() -> int:
    return getattr(_local, "count", 0)
