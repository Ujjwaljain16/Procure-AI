"""Pure presentation layer: transforms an ``AgentRunResult`` (Architecture
A's full internal trace) into small, Streamlit-agnostic display structures.

This module makes no policy decisions and duplicates no business logic --
every status label, approval, risk flag, and missing-information item is
read directly off ``PolicyEvaluation``/``ProcurementDecision``. It only
formats, labels, and groups what the backend already decided, plus one
purely cosmetic derived field (``list_status_badge``) computed from which of
those already-decided lists happen to be empty -- never from re-evaluating
any rule itself.

Testing this module (``tests/test_ui.py``) instead of the Streamlit render
functions is the point: ``ProcurementDecision``/``AgentRunResult`` ->
view model is plain, deterministic Python, so it is fast and reliable to
test without a browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from src.agent.single_agent import AgentRunResult
from src.policy_engine import CheckStatus, PolicyCheck

MISSING_LABEL = "Missing"
NOT_PROVIDED_LABEL = "Not provided"

# Maps a request-detail field key to the exact POL-1 missing_information
# label policy_engine.py uses for it, so "is this field missing" is read
# from the policy evaluation rather than re-derived here.
_POLICY_MISSING_LABELS = {
    "requester": "requester",
    "department": "department",
    "product_vendor": "product/vendor",
    "annual_cost": "annual cost",
    "user_count": "number of users/licenses",
    "business_justification": "business purpose",
    "data_access_level": "data-access level",
    "integrations": "required integrations",
}

_RISK_FLAG_LABELS = {
    "existing_tool_overlap": "Existing tool overlap",
    "budget_insufficient": "Budget insufficient",
    "conflicting_vendor_evidence": "Conflicting vendor evidence",
    "security_review_required": "Security review required",
    "privacy_review_required": "Privacy review required",
    "legal_review_required": "Legal review required",
    "vendor_review_expired": "Vendor security review expired",
    "vendor_risk_unavailable": "Vendor risk service unavailable",
    "missing_information": "Missing information",
    "prompt_injection_detected": "Possible prompt injection detected in request text",
}

_CHECK_STATUS_LABELS = {
    CheckStatus.OK: "PASS",
    CheckStatus.FLAGGED: "REQUIRED",
    CheckStatus.SKIPPED: "SKIPPED",
}


@dataclass(frozen=True)
class FieldView:
    label: str
    value: str
    is_missing: bool


@dataclass(frozen=True)
class EvidenceView:
    evidence_id: str
    source: str
    finding: str
    reference: Optional[str]


@dataclass(frozen=True)
class PolicyCheckView:
    rule_id: str
    status_label: str
    status_kind: str  # "ok" | "flagged" | "skipped" -- for icon/color selection
    detail: str


@dataclass(frozen=True)
class RiskFlagView:
    raw: str
    label: str


@dataclass(frozen=True)
class HumanHandoffView:
    required: bool
    reason_lines: tuple[str, ...]
    required_reviewers: tuple[str, ...]
    ai_action_note: str


@dataclass(frozen=True)
class ToolCallView:
    tool_name: str
    success: bool
    summary: str


@dataclass(frozen=True)
class AuditStageView:
    label: str
    status: str  # "done" | "skipped" | "failed"


@dataclass(frozen=True)
class TelemetryView:
    architecture: str
    llm_calls: Optional[int]
    tool_calls: Optional[int]
    latency_seconds: Optional[float]
    analyst_llm_calls: Optional[int] = None
    reviewer_llm_calls: Optional[int] = None


@dataclass(frozen=True)
class ProcurementView:
    request_id: str
    analysis_status: str  # "Analyzed" | "Automated analysis unavailable"
    list_status_badge: str  # "READY" | "REVIEW" | "MISSING" | "RISK" | "UNAVAILABLE"
    error_banner: Optional[str]

    request_details: tuple[FieldView, ...]
    evidence: tuple[EvidenceView, ...]
    policy_checks: tuple[PolicyCheckView, ...]

    recommendation: str
    rationale: Optional[str]
    next_step: str

    required_approvals: tuple[str, ...]
    risk_flags: tuple[RiskFlagView, ...]
    missing_information: tuple[str, ...]

    human_handoff: HumanHandoffView
    handoff_summary_text: str

    tool_calls: tuple[ToolCallView, ...]
    audit_timeline: tuple[AuditStageView, ...]
    telemetry: TelemetryView


def _field(label: str, raw_value, missing_key: Optional[str], missing_information: tuple) -> FieldView:
    is_missing = missing_key is not None and _POLICY_MISSING_LABELS.get(missing_key) in missing_information
    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        return FieldView(label, MISSING_LABEL if is_missing else NOT_PROVIDED_LABEL, True)
    return FieldView(label, str(raw_value), is_missing)


def _format_cost(value) -> Optional[str]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except Exception:
        return str(value)
    return f"${amount:,.2f}"


def _build_request_details(raw_request: dict, employee_name: Optional[str], department: Optional[str], missing_information: tuple) -> tuple[FieldView, ...]:
    requester_id = raw_request.get("requester_id")
    requester_display = employee_name or requester_id
    integrations = raw_request.get("requested_integrations")
    integrations_display = None
    if integrations is not None:
        integrations_display = ", ".join(integrations) if integrations else "None"

    fields = [
        _field("Requester", requester_display, "requester", missing_information),
        _field("Department", department, "department", missing_information),
        _field("Product", raw_request.get("product_name"), "product_vendor", missing_information),
        _field("Vendor", raw_request.get("vendor_name"), "product_vendor", missing_information),
        _field("Category", raw_request.get("category"), None, missing_information),
        _field("Annual cost", _format_cost(raw_request.get("annual_cost_usd")), "annual_cost", missing_information),
        _field("Users/licenses", raw_request.get("user_count"), "user_count", missing_information),
        _field("Data-access level", raw_request.get("data_access_level"), "data_access_level", missing_information),
        _field("Requested integrations", integrations_display, "integrations", missing_information),
        _field("Urgency", raw_request.get("urgency"), None, missing_information),
        _field("Business justification", raw_request.get("business_justification"), "business_justification", missing_information),
    ]
    return tuple(fields)


def _build_evidence(evidence_index: tuple) -> tuple[EvidenceView, ...]:
    return tuple(
        EvidenceView(evidence_id=eid, source=item.source, finding=item.finding, reference=item.reference)
        for eid, item in evidence_index
    )


def _build_policy_checks(checks: tuple[PolicyCheck, ...]) -> tuple[PolicyCheckView, ...]:
    return tuple(
        PolicyCheckView(rule_id=c.rule_id, status_label=_CHECK_STATUS_LABELS[c.status], status_kind=c.status.value, detail=c.detail)
        for c in checks
    )


def _build_risk_flags(risk_flags: list) -> tuple[RiskFlagView, ...]:
    return tuple(RiskFlagView(raw=flag, label=_RISK_FLAG_LABELS.get(flag, flag.replace("_", " ").capitalize())) for flag in risk_flags)


def _build_human_handoff(decision, risk_flags: tuple[RiskFlagView, ...]) -> HumanHandoffView:
    reasons = [flag.label for flag in risk_flags] or ["Every recommendation from this copilot requires human sign-off before any action is taken."]
    reviewers = tuple(decision.required_approvals)
    return HumanHandoffView(
        required=decision.human_review_required,
        reason_lines=tuple(reasons),
        required_reviewers=reviewers,
        ai_action_note="Recommendation only -- no purchase, approval, or policy exception was executed.",
    )


def _build_handoff_summary_text(decision) -> str:
    lines = [
        "PROCUREMENT REVIEW SUMMARY",
        "",
        f"Request: {decision.request_id}",
        f"Recommendation: {decision.recommendation}",
        "",
        "Required approvals:",
        *([f"- {a}" for a in decision.required_approvals] or ["- (none on record)"]),
        "",
        "Risk flags:",
        *([f"- {f}" for f in decision.risk_flags] or ["- (none)"]),
        "",
        "Missing information:",
        *([f"- {m}" for m in decision.missing_information] or ["- (none)"]),
        "",
        "Evidence:",
        *([f"- [{e.source}] {e.finding}" + (f" (ref: {e.reference})" if e.reference else "") for e in decision.evidence] or ["- (none collected)"]),
        "",
        f"Next step: {decision.next_step}",
    ]
    return "\n".join(lines)


_AUDIT_TOOL_STAGES = (
    ("get_employee_budget", "Employee/budget retrieved"),
    ("search_catalog", "Catalog searched"),
    ("get_vendor_evidence", "Vendor status retrieved"),
    ("search_purchase_history", "Purchase history retrieved"),
)


def _build_audit_timeline(tool_calls: tuple[ToolCallView, ...], gemini_unavailable_reason: Optional[str]) -> tuple[AuditStageView, ...]:
    called = {tc.tool_name for tc in tool_calls}
    stages = [AuditStageView("Request received", "done")]
    for tool_name, label in _AUDIT_TOOL_STAGES:
        stages.append(AuditStageView(label, "done" if tool_name in called else "skipped"))
    stages.append(AuditStageView("Policy evaluated", "done"))
    stages.append(AuditStageView("Recommendation generated", "failed" if gemini_unavailable_reason else "done"))
    stages.append(AuditStageView("Human review determined", "done"))
    return tuple(stages)


def _list_status_badge(decision, gemini_unavailable_reason: Optional[str]) -> str:
    if gemini_unavailable_reason is not None:
        return "UNAVAILABLE"
    if decision.missing_information:
        return "MISSING"
    if decision.risk_flags:
        return "RISK"
    return "READY"


def build_procurement_view(result) -> ProcurementView:
    """Accepts either Architecture A's ``AgentRunResult`` or Architecture
    B's ``StagedAgentRunResult`` (``src/agent/single_agent.py`` /
    ``src/agent/staged_agent.py``) -- the two share every field name this
    function reads, by design, so no architecture-specific branching is
    needed here.
    """
    decision = result.decision
    registry = result.registry
    employee = registry.employee_record()

    tool_calls = tuple(
        ToolCallView(tool_name=r.tool_name, success=r.success, summary=r.summary if r.success else (r.error or "Failed"))
        for r in registry.execution_log
    )
    risk_flags = _build_risk_flags(decision.risk_flags)
    telemetry = decision.telemetry

    rationale = result.agent_rationale
    analyst_report = getattr(result, "analyst_report", None)
    if analyst_report is not None and analyst_report.observations:
        analyst_note = "Analyst observations: " + "; ".join(analyst_report.observations)
        rationale = f"{rationale}\n\n{analyst_note}" if rationale else analyst_note

    return ProcurementView(
        request_id=decision.request_id,
        analysis_status="Automated analysis unavailable" if result.gemini_unavailable_reason else "Analyzed",
        list_status_badge=_list_status_badge(decision, result.gemini_unavailable_reason),
        error_banner=(
            f"AI analysis unavailable. Reason: {result.gemini_unavailable_reason}. "
            "System response: no procurement action was taken. Next step: manual review."
            if result.gemini_unavailable_reason
            else None
        ),
        request_details=_build_request_details(
            result.raw_request, employee.name if employee else None, registry.employee_department(), tuple(decision.missing_information)
        ),
        evidence=_build_evidence(registry.evidence_index()),
        policy_checks=_build_policy_checks(result.policy_evaluation.checks),
        recommendation=decision.recommendation,
        rationale=rationale,
        next_step=decision.next_step,
        required_approvals=tuple(decision.required_approvals),
        risk_flags=risk_flags,
        missing_information=tuple(decision.missing_information),
        human_handoff=_build_human_handoff(decision, risk_flags),
        handoff_summary_text=_build_handoff_summary_text(decision),
        tool_calls=tool_calls,
        audit_timeline=_build_audit_timeline(tool_calls, result.gemini_unavailable_reason),
        telemetry=TelemetryView(
            architecture=(telemetry.architecture if telemetry else "single") or "single",
            llm_calls=telemetry.llm_calls if telemetry else None,
            tool_calls=telemetry.tool_calls if telemetry else None,
            latency_seconds=(telemetry.latency_ms / 1000.0) if telemetry and telemetry.latency_ms is not None else None,
            analyst_llm_calls=getattr(result, "analyst_llm_calls", None),
            reviewer_llm_calls=getattr(result, "reviewer_llm_calls", None),
        ),
    )
