"""Architecture A: single-agent baseline.

    USER REQUEST -> SINGLE AGENT -> TOOL CALLS -> EVIDENCE PACK
                  -> POLICY ENGINE -> SAFETY VALIDATION
                  -> ProcurementDecision -> HUMAN HANDOFF

There is exactly one reasoning agent (one Gemini "conversation" per request,
across a bounded number of turns). Tools (``src/tools/*.py``) remain
deterministic retrieval components; the policy engine (``src/policy_engine.py``)
remains deterministic and authoritative and is never exposed to the model as
a callable tool -- its result is handed to the model only as trusted context
for the final synthesis call, and the model's synthesis can never change it
(enforced in ``src/agent/validation.py``, not merely requested in the prompt).

Every model call is classified: a transport or output failure degrades to a
conservative human-review decision with its reason recorded; a programming
error is re-raised so it surfaces as a bug instead of being hidden.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from src import data_access
from src.agent import prompts
from src.agent.loop_utils import canonical_arguments, is_cancelled
from src.evidence import gather_mandatory_evidence
from src.agent.gemini_adapter import GeminiClientProtocol, GeminiConfigurationError, classify_model_exception, create_gemini_client
from src.agent.schemas import AgentSynthesis
from src.agent.tools_registry import TOOL_SPECS, ToolRegistry
from src.agent.validation import build_procurement_decision
from src.contracts import ProcurementDecision, RunTelemetry
from src.policy_engine import PolicyContext, PolicyEvaluation, RequestFields, evaluate_policy

logger = logging.getLogger(__name__)

MAX_TOOL_TURNS = 6
ARCHITECTURE_NAME = "single"


@dataclass(frozen=True)
class AgentRunResult:
    """Everything one Architecture A run produced, for a consumer (the UI)
    that needs more than the external ``ProcurementDecision`` contract
    carries -- the full POL-rule breakdown, the raw request fields, the
    evidence index, the tool execution log, and the model's own rationale
    text. ``src/solution.py`` and the evaluation harness use
    ``run_single_agent`` (just the ``ProcurementDecision``); the UI uses
    ``run_single_agent_with_trace`` (this).
    """

    decision: ProcurementDecision
    policy_evaluation: PolicyEvaluation
    raw_request: dict
    registry: ToolRegistry
    agent_rationale: Optional[str]
    gemini_unavailable_reason: Optional[str]


def run_single_agent(
    request_id: str,
    client: Optional[GeminiClientProtocol] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ProcurementDecision:
    """Execute Architecture A for one request and return just the external
    ``ProcurementDecision`` contract. See ``run_single_agent_with_trace`` for
    the fuller result a UI needs.

    ``client`` is injectable for tests; production code always calls this with
    no client, which constructs the real Gemini-backed one from environment
    configuration. ``cancel_event`` lets a deadline stop the run at the next
    turn boundary instead of letting it keep spending quota.

    An unknown or malformed ``request_id`` raises before any model call -- no
    ProcurementDecision is fabricated for a request that does not exist. A
    model or transport failure degrades to a conservative human-review decision.
    """
    return run_single_agent_with_trace(request_id, client, cancel_event).decision


def run_single_agent_with_trace(
    request_id: str,
    client: Optional[GeminiClientProtocol] = None,
    cancel_event: Optional[threading.Event] = None,
) -> AgentRunResult:
    """Same execution as ``run_single_agent``, returning the full internal
    trace (policy evaluation, raw request, tool registry, model rationale)
    alongside the ``ProcurementDecision``.
    """
    start = time.monotonic()
    raw = data_access.get_request_validated(request_id)  # KeyError / MalformedRequestError propagate before any LLM call

    # Authoritative evidence is gathered in code before any model call, so the
    # policy result does not depend on whether, or how well, the model works.
    registry = gather_mandatory_evidence(raw)
    llm_calls = 0
    gemini_unavailable_reason: Optional[str] = None

    active_client = client
    if active_client is None:
        try:
            active_client = create_gemini_client()
        except GeminiConfigurationError as exc:
            gemini_unavailable_reason = type(exc).__name__
            logger.warning("request=%s architecture=%s gemini_unavailable reason=%s", request_id, ARCHITECTURE_NAME, exc)

    contents: list = [prompts.build_initial_user_message(raw)]
    seen_calls: set = set()

    if active_client is not None and gemini_unavailable_reason is None:
        for _ in range(MAX_TOOL_TURNS):
            if is_cancelled(cancel_event):
                gemini_unavailable_reason = "ANALYSIS_TIMEOUT"
                break
            llm_calls += 1  # counts every attempt, including one that fails below -- an API call was made either way
            try:
                turn = active_client.generate_turn(contents, list(TOOL_SPECS.values()), prompts.SYSTEM_PROMPT)
            except Exception as exc:
                reason = classify_model_exception(exc)
                if reason is None:
                    raise
                gemini_unavailable_reason = reason
                logger.warning("request=%s architecture=%s gemini_call_failed stage=tool_turn reason=%s", request_id, ARCHITECTURE_NAME, reason)
                break

            if not turn.function_calls:
                break

            all_calls_redundant = True
            response_pairs = []
            for call in turn.function_calls:
                if is_cancelled(cancel_event):
                    break
                call_key = (call.name, canonical_arguments(call.arguments))
                if call_key not in seen_calls:
                    all_calls_redundant = False
                seen_calls.add(call_key)

                record = registry.execute(call.name, call.arguments, bound_request=raw)
                logger.info("request=%s architecture=%s tool=%s success=%s", request_id, ARCHITECTURE_NAME, call.name, record.success)
                response_pairs.append((call, record))

            if turn.raw_content is not None:
                contents.append(turn.raw_content)
            for call, record in response_pairs:
                contents.append(active_client.build_function_response_content(call, record.to_model_payload()))

            if is_cancelled(cancel_event):
                gemini_unavailable_reason = "ANALYSIS_TIMEOUT"
                break
            if all_calls_redundant:
                # the model asked for nothing new this turn -- stop feeding
                # the loop rather than looping indefinitely on repeats.
                break

    department = registry.employee_department()
    request_fields = RequestFields.from_raw(raw, department=department)
    context = PolicyContext(
        request=request_fields,
        budget=registry.budget_evidence(),
        catalog_overlap_matches=registry.catalog_matches(),
        vendor_registry=registry.vendor_registry_evidence(),
        vendor_risk=registry.vendor_risk_evidence(),
    )
    policy_evaluation = evaluate_policy(context)

    synthesis: Optional[AgentSynthesis] = None
    if active_client is not None and gemini_unavailable_reason is None and not is_cancelled(cancel_event):
        synthesis_contents = contents + [prompts.build_synthesis_message(registry.evidence_index(), policy_evaluation)]
        llm_calls += 1  # counts every attempt, including one that fails below
        try:
            synthesis = active_client.generate_structured(synthesis_contents, prompts.SYSTEM_PROMPT)
        except Exception as exc:
            reason = classify_model_exception(exc)
            if reason is None:
                raise
            gemini_unavailable_reason = reason
            logger.warning("request=%s architecture=%s gemini_call_failed stage=synthesis reason=%s", request_id, ARCHITECTURE_NAME, reason)

    latency_ms = (time.monotonic() - start) * 1000
    telemetry = RunTelemetry(
        llm_calls=llm_calls,
        tool_calls=registry.call_count,
        tool_calls_succeeded=sum(1 for record in registry.execution_log if record.success),
        tool_names=registry.tool_names,
        architecture=ARCHITECTURE_NAME,
        latency_ms=latency_ms,
    )

    logger.info(
        "request=%s architecture=%s llm_calls=%d tool_calls=%d latency_ms=%.1f "
        "human_review_required=%s required_approvals=%s risk_flags=%s",
        request_id, ARCHITECTURE_NAME, llm_calls, registry.call_count, latency_ms,
        policy_evaluation.human_review_required, policy_evaluation.required_approvals, policy_evaluation.risk_flags,
    )

    decision = build_procurement_decision(
        request_id=request_id,
        synthesis=synthesis,
        registry=registry,
        policy_evaluation=policy_evaluation,
        telemetry=telemetry,
        gemini_unavailable_reason=gemini_unavailable_reason,
    )

    return AgentRunResult(
        decision=decision,
        policy_evaluation=policy_evaluation,
        raw_request=raw,
        registry=registry,
        agent_rationale=synthesis.rationale if synthesis is not None else None,
        gemini_unavailable_reason=gemini_unavailable_reason,
    )
