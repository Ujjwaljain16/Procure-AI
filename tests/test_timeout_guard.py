"""Tests for src/agent/timeout_guard.py: the deadline, the cancellation signal
it sends to the worker, exception propagation, and that the worker is a daemon
so the process can exit."""

from __future__ import annotations

import threading
import time

import pytest

from src.agent.timeout_guard import run_with_timeout


class TestRunWithTimeout:
    def test_returns_the_callables_result_when_it_finishes_in_time(self):
        assert run_with_timeout(lambda cancel: 42, timeout_seconds=1.0) == 42

    def test_the_worker_receives_a_cancel_event(self):
        seen = {}

        def record(cancel):
            seen["event"] = cancel
            return "ok"

        run_with_timeout(record, timeout_seconds=1.0)
        assert isinstance(seen["event"], threading.Event)

    def test_propagates_a_real_exception_raised_inside_the_callable(self):
        def boom(cancel):
            raise ValueError("real failure")

        with pytest.raises(ValueError, match="real failure"):
            run_with_timeout(boom, timeout_seconds=1.0)

    def test_raises_timeout_error_when_the_callable_is_too_slow(self):
        def slow(cancel):
            time.sleep(0.5)
            return "too late"

        with pytest.raises(TimeoutError):
            run_with_timeout(slow, timeout_seconds=0.05)

    def test_sets_the_cancel_event_on_timeout_so_the_worker_can_stop(self):
        captured = {}

        def cooperative(cancel):
            captured["event"] = cancel
            cancel.wait(2.0)  # a cooperative worker notices the signal
            return "stopped"

        with pytest.raises(TimeoutError):
            run_with_timeout(cooperative, timeout_seconds=0.05)
        assert captured["event"].is_set()

    def test_does_not_block_the_caller_waiting_for_the_abandoned_thread(self):
        def slow(cancel):
            time.sleep(0.5)
            return "irrelevant"

        start = time.monotonic()
        with pytest.raises(TimeoutError):
            run_with_timeout(slow, timeout_seconds=0.05)
        assert time.monotonic() - start < 0.3

    def test_worker_thread_is_a_daemon_so_the_process_can_exit(self):
        names = {}

        def inspect(cancel):
            names["daemon"] = threading.current_thread().daemon
            return None

        run_with_timeout(inspect, timeout_seconds=1.0)
        assert names["daemon"] is True
