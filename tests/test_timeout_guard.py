"""Tests for src/agent/timeout_guard.py -- the external wall-clock deadline
wrapper, exercised with fast/slow fake callables rather than a real agent run.
"""

from __future__ import annotations

import time

import pytest

from src.agent.timeout_guard import run_with_timeout


class TestRunWithTimeout:
    def test_returns_the_callables_result_when_it_finishes_in_time(self):
        assert run_with_timeout(lambda: 42, timeout_seconds=1.0) == 42

    def test_propagates_a_real_exception_raised_inside_the_callable(self):
        def boom():
            raise ValueError("real failure")

        with pytest.raises(ValueError, match="real failure"):
            run_with_timeout(boom, timeout_seconds=1.0)

    def test_raises_timeout_error_when_the_callable_is_too_slow(self):
        def slow():
            time.sleep(0.5)
            return "too late"

        with pytest.raises(TimeoutError):
            run_with_timeout(slow, timeout_seconds=0.05)

    def test_does_not_block_the_caller_waiting_for_the_abandoned_thread(self):
        def slow():
            time.sleep(0.5)
            return "irrelevant"

        start = time.monotonic()
        with pytest.raises(TimeoutError):
            run_with_timeout(slow, timeout_seconds=0.05)
        elapsed = time.monotonic() - start
        assert elapsed < 0.3  # well under the slow() call's own 0.5s sleep
