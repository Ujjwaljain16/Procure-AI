"""Tests for src/agent/key_pool.py: rotation on quota/overload errors, no
rotation on real failures, exhaustion, factory selection, and that key values
never appear in logs. Uses fake clients only -- no quota spent.
"""

from __future__ import annotations

import logging

import pytest

from src.agent import key_pool
from src.agent.gemini_adapter import GeminiConfigurationError, create_gemini_client
from src.agent.key_pool import PooledGeminiClient, is_rotatable_error, load_key_pool


class _FakeClient:
    """Each instance fails with a scripted error for its key until exhausted."""

    failures_by_key: dict = {}

    def __init__(self, api_key, model):
        self.api_key = api_key

    def generate_turn(self, contents, tool_specs, system_instruction):
        err = self.failures_by_key.get(self.api_key)
        if err is not None:
            raise err
        return f"turn-from-{self.api_key}"

    def generate_structured(self, contents, system_instruction):
        err = self.failures_by_key.get(self.api_key)
        if err is not None:
            raise err
        return f"structured-from-{self.api_key}"

    def build_function_response_content(self, call, result):
        return ("content", self.api_key)


class _Pool(PooledGeminiClient):
    _client_class = _FakeClient


@pytest.fixture(autouse=True)
def _reset_failures():
    _FakeClient.failures_by_key = {}
    yield
    _FakeClient.failures_by_key = {}


def _quota_error():
    return RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")


def _overload_error():
    return RuntimeError("503 UNAVAILABLE: high demand")


class TestRotation:
    def test_uses_first_key_when_healthy(self):
        pool = _Pool(["k1", "k2"], "m")
        assert pool.generate_turn([], [], "") == "turn-from-k1"
        assert pool.rotations == 0

    def test_rotates_on_quota_error(self):
        _FakeClient.failures_by_key = {"k1": _quota_error()}
        pool = _Pool(["k1", "k2"], "m")
        assert pool.generate_turn([], [], "") == "turn-from-k2"
        assert pool.rotations == 1

    def test_rotates_on_overload_error(self):
        _FakeClient.failures_by_key = {"k1": _overload_error()}
        pool = _Pool(["k1", "k2"], "m")
        assert pool.generate_structured([], "") == "structured-from-k2"

    def test_sticks_to_the_working_key_after_rotation(self):
        _FakeClient.failures_by_key = {"k1": _quota_error()}
        pool = _Pool(["k1", "k2"], "m")
        pool.generate_turn([], [], "")
        assert pool.generate_turn([], [], "") == "turn-from-k2"

    def test_non_rotatable_error_is_raised_immediately_not_retried(self):
        _FakeClient.failures_by_key = {"k1": ValueError("malformed request")}
        pool = _Pool(["k1", "k2"], "m")
        with pytest.raises(ValueError):
            pool.generate_turn([], [], "")
        assert pool.rotations == 0

    def test_raises_when_every_key_is_exhausted(self):
        _FakeClient.failures_by_key = {"k1": _quota_error(), "k2": _quota_error()}
        pool = _Pool(["k1", "k2"], "m")
        with pytest.raises(RuntimeError, match="429"):
            pool.generate_turn([], [], "")

    def test_empty_pool_is_rejected(self):
        with pytest.raises(ValueError):
            _Pool([], "m")


class TestErrorClassification:
    @pytest.mark.parametrize("text", ["429 too many", "RESOURCE_EXHAUSTED", "503 Service Unavailable", "UNAVAILABLE: high demand"])
    def test_rotatable_markers(self, text):
        assert is_rotatable_error(RuntimeError(text))

    def test_other_errors_are_not_rotatable(self):
        assert not is_rotatable_error(RuntimeError("400 invalid argument"))


class TestLoadKeyPool:
    def test_parses_comma_separated_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY_POOL", " k1 , k2,,k3 ")
        assert load_key_pool() == ["k1", "k2", "k3"]

    def test_missing_pool_raises(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        with pytest.raises(RuntimeError):
            load_key_pool()


class TestFactorySelection:
    def test_pool_env_selects_the_pooled_client(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY_POOL", "k1,k2")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(PooledGeminiClient, "_client_class", _FakeClient)
        client = create_gemini_client()
        assert isinstance(client, PooledGeminiClient)
        assert client.pool_size == 2

    def test_single_key_still_works_without_a_pool(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "solo")
        client = create_gemini_client()
        assert not isinstance(client, PooledGeminiClient)

    def test_no_key_at_all_still_raises_configuration_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY_POOL", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiConfigurationError):
            create_gemini_client()


class TestKeysNeverLogged:
    def test_log_lines_contain_the_index_not_the_key(self, caplog):
        secret = "AIzaSySECRETVALUE1234567890"
        _FakeClient.failures_by_key = {secret: _quota_error()}
        pool = _Pool([secret, "k2"], "m")
        with caplog.at_level(logging.WARNING, logger=key_pool.logger.name):
            pool.generate_turn([], [], "")
        assert caplog.records, "a rotation should be logged"
        assert all(secret not in r.getMessage() for r in caplog.records)
