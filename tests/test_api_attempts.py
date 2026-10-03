"""Attempted vs logical model calls: ``api_attempts`` counts real transport calls.

Every test stubs the TRANSPORT (``google.genai`` ``client.models.generate_content``) of the real
adapter classes and compares telemetry/counters with the number of times the stub was actually called.
Nothing here counts ``record_attempt`` calls made inside a fake, and nothing depends on how many
turns an orchestrator happens to take (no nudge, no turn sequence): expected totals are read from
the transport stub itself.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from src.agent.attempts import current_attempts, record_attempt
from src.agent.gemini_adapter import GeminiClient
from src.agent.key_pool import PooledGeminiClient, PooledStagedGeminiClient
from src.agent.schemas import AgentSynthesis
from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.agent.staged_gemini_adapter import StagedGeminiClient
from src.agent.staged_schemas import AnalystReport

_REPORT = AnalystReport(request_summary="s")
_SYNTH = AgentSynthesis(recommendation="Review.", rationale="r", evidence_refs=[], next_step="Reviewers act.")
MSG = [{"role": "user", "parts": [{"text": "x"}]}]


class _Transport:
    """Stands in for the google.genai client: ``models.generate_content`` is the only HTTP boundary.

    It answers according to the response schema the adapter asked for, so any orchestrator sequence works.
    ``fail_with`` makes every call raise (after being counted)."""

    def __init__(self, fail_with=None):
        self.http_calls = 0
        self._fail_with = fail_with
        outer = self

        class _Models:
            @staticmethod
            def generate_content(model=None, contents=None, config=None):
                outer.http_calls += 1
                if outer._fail_with is not None:
                    raise outer._fail_with
                schema = getattr(config, "response_schema", None)
                parsed = _REPORT if schema is AnalystReport else _SYNTH if schema is AgentSynthesis else None
                return SimpleNamespace(parsed=parsed, text=None, function_calls=None, candidates=[])

        self.models = _Models


def _real(cls, transport, model="m"):
    client = cls(api_key="fake", model=model)
    client._client = transport
    return client


def _delta(fn):
    before = current_attempts()
    try:
        fn()
    except Exception:
        pass
    return current_attempts() - before


# --- the counter itself ------------------------------------------------------------------------------


def test_counter_is_per_thread():
    results = {}

    def work(n):
        before = current_attempts()
        for _ in range(n):
            record_attempt()
        results[n] = current_attempts() - before

    threads = [threading.Thread(target=work, args=(n,)) for n in (1, 3, 7, 11)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == {1: 1, 3: 3, 7: 7, 11: 11}


# --- exactly one attempt per transport call, per adapter method -------------------------------------------


@pytest.mark.parametrize("cls", [GeminiClient, StagedGeminiClient], ids=["GeminiClient", "StagedGeminiClient"])
def test_generate_turn_counts_one_attempt_per_transport_call(cls):
    transport = _Transport()
    client = _real(cls, transport)
    assert _delta(lambda: client.generate_turn(MSG, [], "sys")) == 1
    assert transport.http_calls == 1


@pytest.mark.parametrize("cls", [GeminiClient, StagedGeminiClient], ids=["GeminiClient", "StagedGeminiClient"])
def test_generate_structured_counts_one_attempt_per_transport_call(cls):
    transport = _Transport()
    client = _real(cls, transport)
    assert _delta(lambda: client.generate_structured(MSG, "sys")) == 1
    assert transport.http_calls == 1


def test_generate_analyst_report_counts_one_attempt_per_transport_call():
    transport = _Transport()
    client = _real(StagedGeminiClient, transport)
    assert _delta(lambda: client.generate_analyst_report(MSG, "sys")) == 1
    assert transport.http_calls == 1


@pytest.mark.parametrize("method", ["generate_turn", "generate_structured", "generate_analyst_report"])
def test_a_failed_transport_call_is_still_exactly_one_attempt(method):
    transport = _Transport(fail_with=ConnectionError("down"))
    client = _real(StagedGeminiClient, transport)
    args = (MSG, [], "sys") if method == "generate_turn" else (MSG, "sys")
    assert _delta(lambda: getattr(client, method)(*args)) == 1
    assert transport.http_calls == 1


def test_n_transport_calls_record_n_attempts():
    transport = _Transport()
    client = _real(StagedGeminiClient, transport)
    assert _delta(lambda: [client.generate_analyst_report(MSG, "sys") for _ in range(5)]) == 5
    assert transport.http_calls == 5


def test_the_attempt_count_always_equals_the_transport_call_count_across_mixed_calls():
    transport = _Transport()
    client = _real(StagedGeminiClient, transport)
    before = current_attempts()
    client.generate_turn(MSG, [], "s")
    client.generate_structured(MSG, "s")
    client.generate_analyst_report(MSG, "s")
    client.generate_structured(MSG, "s")
    assert current_attempts() - before == transport.http_calls == 4


# --- pool rotation: each HTTP attempt counted once ----------------------------------------------------------


class _Factory:
    """Builds real adapter clients whose transport is a per-key stub, so rotation runs through real code."""

    transports: dict = {}
    staged = False

    def __new__(cls, api_key, model):
        return _real(StagedGeminiClient if cls.staged else GeminiClient, cls.transports[api_key], model)


@pytest.fixture
def factory(monkeypatch):
    _Factory.staged = False
    monkeypatch.setattr(PooledGeminiClient, "_client_class", _Factory)
    monkeypatch.setattr("src.agent.key_pool._staged_client_class", lambda: _Factory)
    yield _Factory
    _Factory.staged = False


def _total_http(transports):
    return sum(t.http_calls for t in transports.values())


def test_pool_rotation_counts_each_transport_attempt_once(factory):
    quota = RuntimeError("429 RESOURCE_EXHAUSTED")
    factory.transports = {"k1": _Transport(quota), "k2": _Transport(quota), "k3": _Transport()}
    pool = PooledGeminiClient(["k1", "k2", "k3"], "m")
    before = current_attempts()
    assert pool.generate_structured(MSG, "sys") is _SYNTH
    assert [t.http_calls for t in factory.transports.values()] == [1, 1, 1]
    assert current_attempts() - before == _total_http(factory.transports) == 3
    assert pool.real_calls_made == 3


def test_staged_pool_rotation_counts_each_transport_attempt_once(factory):
    factory.staged = True
    factory.transports = {"k1": _Transport(RuntimeError("503 UNAVAILABLE")), "k2": _Transport()}
    pool = PooledStagedGeminiClient(["k1", "k2"], "m")
    before = current_attempts()
    assert pool.generate_analyst_report(MSG, "sys") is _REPORT
    assert [t.http_calls for t in factory.transports.values()] == [1, 1]
    assert current_attempts() - before == 2


def test_a_pool_where_every_key_fails_counts_every_attempt_once(factory):
    quota = RuntimeError("429 RESOURCE_EXHAUSTED")
    factory.transports = {"k1": _Transport(quota), "k2": _Transport(quota)}
    pool = PooledGeminiClient(["k1", "k2"], "m")
    assert _delta(lambda: pool.generate_structured(MSG, "sys")) == 2 == _total_http(factory.transports)


# --- telemetry equals the transport's own count, whatever sequence the orchestrator takes ------------------------


def test_single_run_telemetry_equals_the_transport_call_count():
    transport = _Transport()
    telemetry = run_single_agent_with_trace("REQ-1001", client=_real(GeminiClient, transport)).decision.telemetry
    assert transport.http_calls >= 1
    assert telemetry.api_attempts == transport.http_calls
    assert telemetry.model == "m"


def test_staged_run_telemetry_equals_the_transport_call_count():
    transport = _Transport()
    telemetry = run_staged_agent_with_trace("REQ-1001", client=_real(StagedGeminiClient, transport)).decision.telemetry
    assert transport.http_calls >= 2  # at least the analyst report and the reviewer
    assert telemetry.api_attempts == transport.http_calls


def test_a_run_through_a_rotating_pool_reports_every_transport_attempt(factory):
    quota = RuntimeError("429 RESOURCE_EXHAUSTED")
    factory.transports = {"k1": _Transport(quota), "k2": _Transport()}
    pool = PooledGeminiClient(["k1", "k2"], "pool-model")
    telemetry = run_single_agent_with_trace("REQ-1001", client=pool).decision.telemetry
    assert telemetry.api_attempts == _total_http(factory.transports)
    assert telemetry.api_attempts > telemetry.llm_calls  # k1's failed attempt is visible beyond the logical calls
    assert telemetry.model == "pool-model"


def test_attempts_made_before_a_run_are_not_counted():
    for _ in range(5):
        record_attempt()
    transport = _Transport()
    telemetry = run_single_agent_with_trace("REQ-1001", client=_real(GeminiClient, transport)).decision.telemetry
    assert telemetry.api_attempts == transport.http_calls


def test_clients_that_make_no_http_calls_report_unknown_not_zero():
    from tests.agent_fakes import ScriptedGeminiClient, stop_turn
    from tests.test_agent_single import _synthesis

    telemetry = run_single_agent_with_trace("REQ-1001", client=ScriptedGeminiClient(turns=[stop_turn()], structured_result=_synthesis())).decision.telemetry
    assert telemetry.api_attempts is None and telemetry.model is None
