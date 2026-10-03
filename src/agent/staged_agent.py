"""Architecture B: lightweight staged / two-agent variant (analyst -> reviewer).

    USER REQUEST -> ANALYST AGENT -> TOOL CALLS -> EVIDENCE PACK
                  -> POLICY ENGINE -> REVIEWER AGENT -> FINAL VALIDATION
                  -> ProcurementDecision -> HUMAN HANDOFF

At most two reasoning stages. The analyst gathers evidence via the exact
same allowlisted tools Architecture A uses (``src/tools/*.py`` via
``src/agent/tools_registry.py``) and produces a structured
``AnalystReport``; the reviewer then consumes that report plus the evidence
and the deterministic ``PolicyEvaluation`` -- it has no tools of its own and
makes zero additional tool calls by design (it should review the analyst's
evidence, not go hunting for more). The policy engine and final validator
(``src/agent/validation.py``) are the exact same code Architecture A uses;
only the reasoning/orchestration layer differs, per the Phase 6 requirement
that both architectures share tools, policy engine, validator, and contract.

This module intentionally does not share its tool-gathering loop with
``src/agent/single_agent.py``, even though the two are structurally similar:
Architecture A's files are frozen for the Phase 6 A-vs-B experiment (see
``docs/architecture_a_baseline.md``) and must not be modified or refactored
during this phase. The loop bodies are consequently near-duplicates of each
other; everything downstream of the loop (tools, policy engine, validator,
contracts) is 100% shared, not duplicated -- exactly the boundary the
experiment needs to be credible.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from src import data_access
from src.agent import staged_prompts
from src.agent.schemas import AgentSynthesis
from src.agent.staged_gemini_adapter import StagedGeminiClient, create_staged_gemini_client
from src.agent.staged_schemas import AnalystReport
from src.agent.tools_registry import TOOL_SPECS, ToolRegistry
from src.agent.validation import build_procurement_decision
from src.contracts import ProcurementDecision, RunTelemetry
from src.policy_engine import PolicyContext, PolicyEvaluation, RequestFields, evaluate_policy

logger = logging.getLogger(__name__)

MAX_ANALYST_TOOL_TURNS = 6
ARCHITECTURE_NAME = "staged"


@dataclass(frozen=True)
class StagedAgentRunResult:
    """Field names mirror ``AgentRunResult`` (``src/agent/single_agent.py``)
    so ``src/ui/view_model.py`` can render either result without any change
    -- only the extra analyst/reviewer breakdown fields are new.
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


def run_staged_agent(request_id: str, client: Optional[StagedGeminiClient] = None) -> ProcurementDecision:
    return run_staged_agent_with_trace(request_id, client).decision


def run_staged_agent_with_trace(request_id: str, client: Optional[StagedGeminiClient] = None) -> StagedAgentRunResult:
    start = time.monotonic()
    raw = data_access.get_request_validated(request_id)  # KeyError / MalformedRequestError propagate before any LLM call, by design

    registry = ToolRegistry()
    analyst_llm_calls = 0
    reviewer_llm_calls = 0
    gemini_unavailable_reason: Optional[str] = None

    active_client = client
    if active_client is None:
        try:
            active_client = create_staged_gemini_client()
        except Exception as exc:
            gemini_unavailable_reason = type(exc).__name__
            logger.warning("request=%s architecture=%s gemini_unavailable reason=%s", request_id, ARCHITECTURE_NAME, exc)

    # --- Analyst stage: bounded tool-gathering loop, then a structured report ---
    analyst_report: Optional[AnalystReport] = None
    contents: list = [staged_prompts.build_analyst_initial_message(raw)]
    seen_calls: set = set()

    if active_client is not None and gemini_unavailable_reason is None:
        for _ in range(MAX_ANALYST_TOOL_TURNS):
            analyst_llm_calls += 1
            try:
                turn = active_client.generate_turn(contents, list(TOOL_SPECS.values()), staged_prompts.ANALYST_SYSTEM_PROMPT)
            except Exception as exc:
                gemini_unavailable_reason = type(exc).__name__
                logger.warning(
                    "request=%s architecture=%s gemini_call_failed stage=analyst_tool_turn error=%s",
                    request_id, ARCHITECTURE_NAME, exc,
                )
                break

            if not turn.function_calls:
                break

            all_calls_redundant = True
            response_pairs = []
            for call in turn.function_calls:
                call_key = (call.name, tuple(sorted(call.arguments.items())))
                if call_key not in seen_calls:
                    all_calls_redundant = False
                seen_calls.add(call_key)

                record = registry.execute(call.name, call.arguments)
                logger.info(
                    "request=%s architecture=%s stage=analyst tool=%s success=%s",
                    request_id, ARCHITECTURE_NAME, call.name, record.success,
                )
                response_pairs.append((call, record))

            if turn.raw_content is not None:
                contents.append(turn.raw_content)
            for call, record in response_pairs:
                contents.append(active_client.build_function_response_content(call, record.to_model_payload()))

            if all_calls_redundant:
                break

        analyst_contents = contents + [staged_prompts.build_analyst_final_instruction()]
        analyst_llm_calls += 1
        try:
            analyst_report = active_client.generate_analyst_report(analyst_contents, staged_prompts.ANALYST_SYSTEM_PROMPT)
        except Exception as exc:
            gemini_unavailable_reason = type(exc).__name__
            logger.warning(
                "request=%s architecture=%s gemini_call_failed stage=analyst_report error=%s",
                request_id, ARCHITECTURE_NAME, exc,
            )

    # --- Policy evaluation: identical construction to Architecture A, from
    # whatever evidence the analyst collected (possibly none, if Gemini
    # failed before any tool call happened). ---
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

    # --- Reviewer stage: zero tool calls, one structured-output call,
    # consuming the analyst's report + evidence + policy evaluation. ---
    synthesis: Optional[AgentSynthesis] = None
    if active_client is not None and gemini_unavailable_reason is None and analyst_report is not None:
        reviewer_contents = [
            staged_prompts.build_reviewer_message(raw, registry.evidence_index(), analyst_report, policy_evaluation)
        ]
        reviewer_llm_calls += 1
        try:
            synthesis = active_client.generate_structured(reviewer_contents, staged_prompts.REVIEWER_SYSTEM_PROMPT)
        except Exception as exc:
            gemini_unavailable_reason = type(exc).__name__
            logger.warning(
                "request=%s architecture=%s gemini_call_failed stage=reviewer error=%s",
                request_id, ARCHITECTURE_NAME, exc,
            )

    latency_ms = (time.monotonic() - start) * 1000
    telemetry = RunTelemetry(
        llm_calls=analyst_llm_calls + reviewer_llm_calls,
        tool_calls=registry.call_count,
        tool_names=registry.tool_names,
        architecture=ARCHITECTURE_NAME,
        latency_ms=latency_ms,
    )

    logger.info(
        "request=%s architecture=%s analyst_llm_calls=%d reviewer_llm_calls=%d tool_calls=%d latency_ms=%.1f "
        "human_review_required=%s required_approvals=%s risk_flags=%s",
        request_id, ARCHITECTURE_NAME, analyst_llm_calls, reviewer_llm_calls, registry.call_count, latency_ms,
        policy_evaluation.human_review_required, policy_evaluation.required_approvals, policy_evaluation.risk_flags,
    )

    # Reused, unmodified: the exact same final validator Architecture A uses.
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
    )
