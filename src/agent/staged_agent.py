"""Architecture B: lightweight staged / two-agent variant (analyst -> reviewer).

    USER REQUEST -> MANDATORY EVIDENCE PREFLIGHT (src/evidence.py)
                  -> ANALYST AGENT (supplemental, identity-bound tool calls)
                  -> POLICY ENGINE -> REVIEWER AGENT -> FINAL VALIDATION
                  -> ProcurementDecision -> HUMAN HANDOFF

At most two reasoning stages. The policy inputs are gathered by the same
deterministic preflight Architecture A uses, before any model call, so the
analyst cannot change what the policy engine sees. The analyst then produces
a structured ``AnalystReport`` from that evidence, with optional supplemental
lookups bound to this request's own identity values. The reviewer consumes the
report, the evidence and the deterministic ``PolicyEvaluation``; it has no
tools and makes zero tool calls by design. The policy engine and final
validator (``src/agent/validation.py``) are the same code Architecture A uses;
only the reasoning/orchestration layer differs.

If the reviewer fails, the run keeps the analyst's report and evidence, marks
``reviewer_status`` as FAILED with the reason, and still passes everything
through the shared validator -- analyst text never bypasses the guard.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from src import data_access
from src.agent import staged_prompts
from src.agent.gemini_adapter import classify_model_exception
from src.agent.loop_utils import canonical_arguments, is_cancelled
from src.agent.schemas import AgentSynthesis
from src.evidence import gather_mandatory_evidence
from src.agent.staged_gemini_adapter import StagedGeminiClient, create_staged_gemini_client
from src.agent.staged_schemas import AnalystReport
from src.agent.tools_registry import TOOL_SPECS, ToolRegistry
from src.agent.validation import build_procurement_decision
from src.contracts import ProcurementDecision, RunTelemetry
from src.policy_engine import PolicyContext, PolicyEvaluation, RequestFields, evaluate_policy

logger = logging.getLogger(__name__)

MAX_ANALYST_TOOL_TURNS = 6
ARCHITECTURE_NAME = "staged"
REVIEWER_STATUS_OK = "OK"
REVIEWER_STATUS_SKIPPED = "SKIPPED"
REVIEWER_STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class StagedAgentRunResult:
    """Field names mirror ``AgentRunResult`` (``src/agent/single_agent.py``)
    so ``src/ui/view_model.py`` can render either result without any change
    -- only the analyst/reviewer breakdown fields are new.
    """

    decision: ProcurementDecision
    policy_evaluation: PolicyEvaluation
    raw_request: dict
    registry: ToolRegistry
    agent_rationale: Optional[str]
    gemini_unavailable_reason: Optional[str]
    analyst_report: Optional[AnalystReport]
    analyst_llm_calls: int
    reviewer_llm_calls: int
    reviewer_status: str = REVIEWER_STATUS_SKIPPED


def run_staged_agent(
    request_id: str,
    client: Optional[StagedGeminiClient] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ProcurementDecision:
    return run_staged_agent_with_trace(request_id, client, cancel_event).decision


def run_staged_agent_with_trace(
    request_id: str,
    client: Optional[StagedGeminiClient] = None,
    cancel_event: Optional[threading.Event] = None,
) -> StagedAgentRunResult:
    start = time.monotonic()
    raw = data_access.get_request_validated(request_id)  # KeyError / MalformedRequestError propagate before any LLM call

    # Authoritative evidence is gathered in code before any model call. This is
    # the same preflight Architecture A uses, so the two architectures differ
    # only in how the model is orchestrated, never in the evidence they see.
    registry = gather_mandatory_evidence(raw)
    analyst_llm_calls = 0
    reviewer_llm_calls = 0
    gemini_unavailable_reason: Optional[str] = None

    active_client = client
    if active_client is None:
        try:
            active_client = create_staged_gemini_client()
        except Exception as exc:
            reason = classify_model_exception(exc)
            if reason is None:
                raise
            gemini_unavailable_reason = reason
            logger.warning("request=%s architecture=%s gemini_unavailable reason=%s", request_id, ARCHITECTURE_NAME, reason)

    # --- Analyst stage: bounded tool-gathering loop, then a structured report ---
    analyst_report: Optional[AnalystReport] = None
    contents: list = [staged_prompts.build_analyst_initial_message(raw)]
    seen_calls: set = set()

    if active_client is not None and gemini_unavailable_reason is None:
        for _ in range(MAX_ANALYST_TOOL_TURNS):
            if is_cancelled(cancel_event):
                gemini_unavailable_reason = "ANALYSIS_TIMEOUT"
                break
            analyst_llm_calls += 1
            try:
                turn = active_client.generate_turn(contents, list(TOOL_SPECS.values()), staged_prompts.ANALYST_SYSTEM_PROMPT)
            except Exception as exc:
                reason = classify_model_exception(exc)
                if reason is None:
                    raise
                gemini_unavailable_reason = reason
                logger.warning("request=%s architecture=%s gemini_call_failed stage=analyst_tool_turn reason=%s", request_id, ARCHITECTURE_NAME, reason)
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
                logger.info("request=%s architecture=%s stage=analyst tool=%s success=%s", request_id, ARCHITECTURE_NAME, call.name, record.success)
                response_pairs.append((call, record))

            if turn.raw_content is not None:
                contents.append(turn.raw_content)
            for call, record in response_pairs:
                contents.append(active_client.build_function_response_content(call, record.to_model_payload()))

            if is_cancelled(cancel_event):
                gemini_unavailable_reason = "ANALYSIS_TIMEOUT"
                break
            if all_calls_redundant:
                break

        if gemini_unavailable_reason is None and not is_cancelled(cancel_event):
            analyst_contents = contents + [staged_prompts.build_analyst_final_instruction()]
            analyst_llm_calls += 1
            try:
                analyst_report = active_client.generate_analyst_report(analyst_contents, staged_prompts.ANALYST_SYSTEM_PROMPT)
            except Exception as exc:
                reason = classify_model_exception(exc)
                if reason is None:
                    raise
                gemini_unavailable_reason = reason
                logger.warning("request=%s architecture=%s gemini_call_failed stage=analyst_report reason=%s", request_id, ARCHITECTURE_NAME, reason)

    # --- Policy evaluation: identical construction to Architecture A ---
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

    # --- Reviewer stage: zero tool calls, one structured-output call ---
    synthesis: Optional[AgentSynthesis] = None
    reviewer_status = REVIEWER_STATUS_SKIPPED
    if active_client is not None and gemini_unavailable_reason is None and analyst_report is not None and not is_cancelled(cancel_event):
        reviewer_contents = [staged_prompts.build_reviewer_message(raw, registry.evidence_index(), analyst_report, policy_evaluation)]
        reviewer_llm_calls += 1
        try:
            synthesis = active_client.generate_structured(reviewer_contents, staged_prompts.REVIEWER_SYSTEM_PROMPT)
            reviewer_status = REVIEWER_STATUS_OK
        except Exception as exc:
            reason = classify_model_exception(exc)
            if reason is None:
                raise
            gemini_unavailable_reason = reason
            reviewer_status = REVIEWER_STATUS_FAILED
            logger.warning("request=%s architecture=%s gemini_call_failed stage=reviewer reason=%s", request_id, ARCHITECTURE_NAME, reason)

    latency_ms = (time.monotonic() - start) * 1000
    telemetry = RunTelemetry(
        llm_calls=analyst_llm_calls + reviewer_llm_calls,
        tool_calls=registry.call_count,
        tool_calls_succeeded=sum(1 for record in registry.execution_log if record.success),
        tool_names=registry.tool_names,
        architecture=ARCHITECTURE_NAME,
        latency_ms=latency_ms,
    )

    logger.info(
        "request=%s architecture=%s analyst_llm_calls=%d reviewer_llm_calls=%d reviewer_status=%s tool_calls=%d latency_ms=%.1f "
        "human_review_required=%s required_approvals=%s risk_flags=%s",
        request_id, ARCHITECTURE_NAME, analyst_llm_calls, reviewer_llm_calls, reviewer_status, registry.call_count, latency_ms,
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

    return StagedAgentRunResult(
        decision=decision,
        policy_evaluation=policy_evaluation,
        raw_request=raw,
        registry=registry,
        agent_rationale=synthesis.rationale if synthesis is not None else None,
        gemini_unavailable_reason=gemini_unavailable_reason,
        analyst_report=analyst_report,
        analyst_llm_calls=analyst_llm_calls,
        reviewer_llm_calls=reviewer_llm_calls,
        reviewer_status=reviewer_status,
    )
