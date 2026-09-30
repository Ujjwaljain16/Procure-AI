"""Deterministic procurement policy engine.

This module is the CODE layer of the AI / CODE / HUMAN split described in the
assignment brief: it takes normalized evidence that some future tool layer has
already gathered, and deterministically computes which policy consequences
follow from it (required approvals, missing information, risk flags, and
whether human review is required).

Every rule implemented here traces back to a numbered rule in
``data/procurement_policy.md`` (POL-1 .. POL-11); each ``PolicyCheck`` in a
``PolicyEvaluation`` carries the rule id it came from so a reviewer can see
exactly why a conclusion was reached.

Hard constraints, enforced throughout this module:

* No LLM calls, no network calls, no filesystem access, no ``datetime.now()``.
* No architecture-specific logic (single-agent vs. staged) — this module is
  shared by both.
* Free-text business fields (``business_justification`` in particular) are
  never inspected by any rule below. That is the whole of how POL-9 (prompt
  injection) is enforced here: the engine simply has no code path through
  which untrusted text could reach a decision.
* Missing evidence is always represented as missing (``None``/absent), never
  guessed at or defaulted to a favorable value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable, Optional, Union

POLICY_VERSION = "2026.09"
REFERENCE_DATE = date(2026, 9, 30)
SECURITY_ASSESSMENT_VALIDITY_DAYS = 365
LEGAL_NEW_VENDOR_SPEND_THRESHOLD_USD = Decimal("10000")

FINANCIAL_TIER_MANAGER_MAX_USD = Decimal("1000")
FINANCIAL_TIER_DEPT_PROCUREMENT_MAX_USD = Decimal("10000")
FINANCIAL_TIER_DEPT_FINANCE_PROCUREMENT_MAX_USD = Decimal("25000")


# ---------------------------------------------------------------------------
# Monetary normalization
# ---------------------------------------------------------------------------


def to_decimal(value: Union[None, int, float, str, Decimal]) -> Optional[Decimal]:
    """Normalize a raw numeric value (as loaded from CSV/JSON/pandas) to
    ``Decimal``, going through ``str()`` first so float binary-representation
    error never leaks into a policy threshold comparison. Returns ``None`` for
    ``None`` input — this function never invents a value for missing data.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError(f"Cannot interpret {value!r} as a monetary amount") from exc


def _is_blank(value: Optional[str]) -> bool:
    return value is None or not value.strip()


def _dedupe_preserve_order(items: Iterable[str]) -> tuple[str, ...]:
    """Deduplicate while preserving first-seen order. Deliberately avoids
    ``set`` here: dict insertion-order iteration is guaranteed by the
    language, whereas set iteration order is not a safe thing to depend on
    for deterministic, reproducible output.
    """
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return tuple(seen.keys())


# ---------------------------------------------------------------------------
# Input model — evidence already gathered by a future tool layer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestFields:
    """Normalized procurement-request fields.

    ``business_justification`` is intentionally present here (for pass-through
    display) but no function in this module ever branches on its content —
    that is what makes POL-9 enforcement structural rather than a matter of
    filtering.
    """

    request_id: str
    requester_id: Optional[str] = None
    department: Optional[str] = None
    product_name: Optional[str] = None
    vendor_name: Optional[str] = None
    annual_cost_usd: Optional[Decimal] = None
    user_count: Optional[int] = None
    business_justification: Optional[str] = None
    data_access_level: Optional[str] = None
    requested_integrations: Optional[tuple[str, ...]] = None

    @staticmethod
    def from_raw(raw: dict, *, department: Optional[str] = None) -> "RequestFields":
        """Build from a ``requests.json``-shaped dict. ``department`` is not
        present on the raw request (it comes from an employee lookup) so the
        caller supplies it once resolved; if omitted it is correctly reported
        as missing by POL-1 rather than guessed at.
        """
        integrations = raw.get("requested_integrations")
        return RequestFields(
            request_id=raw["request_id"],
            requester_id=raw.get("requester_id"),
            department=department,
            product_name=raw.get("product_name"),
            vendor_name=raw.get("vendor_name"),
            annual_cost_usd=to_decimal(raw.get("annual_cost_usd")),
            user_count=raw.get("user_count"),
            business_justification=raw.get("business_justification"),
            data_access_level=raw.get("data_access_level"),
            requested_integrations=tuple(integrations) if integrations is not None else None,
        )


@dataclass(frozen=True)
class BudgetEvidence:
    department: str
    available_usd: Optional[Decimal]

    @staticmethod
    def from_row(row: dict) -> "BudgetEvidence":
        return BudgetEvidence(
            department=row["department"],
            available_usd=to_decimal(row.get("available_usd")),
        )


@dataclass(frozen=True)
class CatalogMatch:
    """An existing catalog entry a tool layer has already matched against the
    request (by product, vendor, or category). The policy engine never does
    this matching itself and never collapses ``status`` to a boolean — it is
    passed straight into ``PolicyCheck`` detail text verbatim, so a value like
    ``"Approved - limited use"`` is never mistaken for an unrestricted
    ``"Approved"``.
    """

    software_id: str
    product_name: str
    category: str
    vendor_name: str
    status: str
    licensed_seats: Optional[int] = None

    @staticmethod
    def from_row(row: dict) -> "CatalogMatch":
        seats = row.get("licensed_seats")
        return CatalogMatch(
            software_id=row["software_id"],
            product_name=row["product_name"],
            category=row["category"],
            vendor_name=row["vendor_name"],
            status=row["status"],
            licensed_seats=int(seats) if seats is not None else None,
        )


@dataclass(frozen=True)
class VendorRegistryEvidence:
    """The internal procurement/vendor registry (``vendors.csv``). This can be
    stale relative to the live vendor-risk service — see ``vendors.csv``'s own
    note on SignalWatch — which is exactly what POL-5's conflict handling
    exists for.
    """

    vendor_name: str
    procurement_status: Optional[str] = None
    security_status: Optional[str] = None
    security_review_date: Optional[date] = None
    legal_terms_status: Optional[str] = None

    @staticmethod
    def from_row(row: dict) -> "VendorRegistryEvidence":
        review_date_raw = row.get("security_review_date")
        return VendorRegistryEvidence(
            vendor_name=row["vendor_name"],
            procurement_status=row.get("procurement_status") or None,
            security_status=row.get("security_status") or None,
            security_review_date=date.fromisoformat(review_date_raw) if review_date_raw else None,
            legal_terms_status=row.get("legal_terms_status") or None,
        )


class VendorRiskAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class VendorRiskEvidence:
    """The live vendor-risk service's evidence for a vendor. Use
    :meth:`unavailable` when the tool that would call the service failed
    (e.g. the mock API's simulated 503 for NimbusAI) — the policy engine
    never makes that call itself, it only reacts to the availability state a
    tool reports.
    """

    vendor_name: str
    availability: VendorRiskAvailability
    security_review_status: Optional[str] = None
    last_review_date: Optional[date] = None
    processes_personal_data: Optional[bool] = None
    stores_data_outside_region: Optional[bool] = None
    risk_level: Optional[str] = None

    @staticmethod
    def from_api_response(vendor_name: str, payload: dict) -> "VendorRiskEvidence":
        review_date_raw = payload.get("last_review_date")
        return VendorRiskEvidence(
            vendor_name=vendor_name,
            availability=VendorRiskAvailability.AVAILABLE,
            security_review_status=payload.get("security_review_status"),
            last_review_date=date.fromisoformat(review_date_raw) if review_date_raw else None,
            processes_personal_data=payload.get("processes_personal_data"),
            stores_data_outside_region=payload.get("stores_data_outside_region"),
            risk_level=payload.get("risk_level"),
        )

    @staticmethod
    def unavailable(vendor_name: str) -> "VendorRiskEvidence":
        return VendorRiskEvidence(vendor_name=vendor_name, availability=VendorRiskAvailability.UNAVAILABLE)


@dataclass(frozen=True)
class PolicyContext:
    """Everything the policy engine needs for one request, already gathered
    by a future tool layer. Immutable by design — the engine never mutates
    its input.
    """

    request: RequestFields
    budget: Optional[BudgetEvidence] = None
    catalog_overlap_matches: tuple[CatalogMatch, ...] = ()
    vendor_registry: Optional[VendorRegistryEvidence] = None
    vendor_risk: Optional[VendorRiskEvidence] = None
    reference_date: date = REFERENCE_DATE


# ---------------------------------------------------------------------------
# Output model — auditable, richer than the final ProcurementDecision
# ---------------------------------------------------------------------------


class CheckStatus(str, Enum):
    OK = "ok"  # evaluated; nothing added to approvals/flags/missing-info
    FLAGGED = "flagged"  # evaluated; contributed to approvals/flags/missing-info
    SKIPPED = "skipped"  # could not be evaluated — evidence missing/unavailable


@dataclass(frozen=True)
class PolicyCheck:
    rule_id: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class PolicyEvaluation:
    """The engine's full, inspectable output. ``ProcurementDecision`` (in
    ``src/contracts.py``) is the external contract the harness validates
    against; this is the richer internal record a future agent/UI can use to
    explain *why*.
    """

    request_id: str
    policy_version: str
    reference_date: date
    checks: tuple[PolicyCheck, ...]
    required_approvals: tuple[str, ...]
    missing_information: tuple[str, ...]
    risk_flags: tuple[str, ...]
    human_review_required: bool


@dataclass(frozen=True)
class _RuleOutcome:
    checks: tuple[PolicyCheck, ...]
    required_approvals: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# POL-1 — required request information
# ---------------------------------------------------------------------------

_UNKNOWN_DATA_ACCESS_VALUES = {"unknown", ""}


def _check_required_fields(request: RequestFields) -> _RuleOutcome:
    missing: list[str] = []
    if _is_blank(request.requester_id):
        missing.append("requester")
    if _is_blank(request.department):
        missing.append("department")
    if _is_blank(request.product_name) or _is_blank(request.vendor_name):
        missing.append("product/vendor")
    if request.annual_cost_usd is None:
        missing.append("annual cost")
    if request.user_count is None:
        missing.append("number of users/licenses")
    if _is_blank(request.business_justification):
        missing.append("business purpose")
    if _is_blank(request.data_access_level) or request.data_access_level.strip().lower() in _UNKNOWN_DATA_ACCESS_VALUES:
        missing.append("data-access level")
    if request.requested_integrations is None:
        missing.append("required integrations")

    if missing:
        detail = f"Missing required fields (POL-1): {', '.join(missing)}."
        status = CheckStatus.FLAGGED
    else:
        detail = "All POL-1 required request fields are present."
        status = CheckStatus.OK
    return _RuleOutcome(checks=(PolicyCheck("POL-1", status, detail),), missing_information=tuple(missing))


# ---------------------------------------------------------------------------
# POL-2 — budget
# ---------------------------------------------------------------------------


def _check_budget(request: RequestFields, budget: Optional[BudgetEvidence]) -> _RuleOutcome:
    if request.annual_cost_usd is None:
        return _RuleOutcome(
            checks=(PolicyCheck("POL-2", CheckStatus.SKIPPED, "Annual cost not provided; budget check skipped."),)
        )
    if budget is None or budget.available_usd is None:
        return _RuleOutcome(
            checks=(PolicyCheck("POL-2", CheckStatus.SKIPPED, "Department budget unavailable; budget check skipped."),),
            missing_information=("department budget",),
        )
    if request.annual_cost_usd > budget.available_usd:
        detail = f"Annual cost ${request.annual_cost_usd} exceeds available budget ${budget.available_usd}."
        return _RuleOutcome(
            checks=(PolicyCheck("POL-2", CheckStatus.FLAGGED, detail),),
            risk_flags=("budget_insufficient",),
        )
    detail = f"Annual cost ${request.annual_cost_usd} is within available budget ${budget.available_usd}."
    return _RuleOutcome(checks=(PolicyCheck("POL-2", CheckStatus.OK, detail),))


# ---------------------------------------------------------------------------
# POL-3 — existing tool / overlap
# ---------------------------------------------------------------------------


def _check_overlap(matches: tuple[CatalogMatch, ...]) -> _RuleOutcome:
    if not matches:
        return _RuleOutcome(checks=(PolicyCheck("POL-3", CheckStatus.OK, "No existing catalog overlap found."),))
    names = "; ".join(f"{m.product_name} ({m.software_id}, status: {m.status})" for m in matches)
    detail = (
        f"Existing catalog option(s) found: {names}. Not an automatic rejection — "
        "surfacing for a credible-gap determination, per POL-3."
    )
    return _RuleOutcome(
        checks=(PolicyCheck("POL-3", CheckStatus.FLAGGED, detail),),
        risk_flags=("existing_tool_overlap",),
    )


# ---------------------------------------------------------------------------
# POL-4 — financial approval thresholds
# ---------------------------------------------------------------------------


def _check_financial_threshold(annual_cost_usd: Optional[Decimal]) -> _RuleOutcome:
    if annual_cost_usd is None:
        return _RuleOutcome(
            checks=(
                PolicyCheck(
                    "POL-4", CheckStatus.SKIPPED, "Annual cost not provided; approval tier cannot be determined."
                ),
            )
        )

    if annual_cost_usd <= FINANCIAL_TIER_MANAGER_MAX_USD:
        rule_id, approvals = "POL-4a", ("Manager",)
    elif annual_cost_usd <= FINANCIAL_TIER_DEPT_PROCUREMENT_MAX_USD:
        rule_id, approvals = "POL-4b", ("Department Head", "Procurement")
    elif annual_cost_usd <= FINANCIAL_TIER_DEPT_FINANCE_PROCUREMENT_MAX_USD:
        rule_id, approvals = "POL-4c", ("Department Head", "Finance", "Procurement")
    else:
        rule_id, approvals = "POL-4d", ("Department Head", "Finance", "CFO", "Procurement")

    detail = f"Annual cost ${annual_cost_usd} falls in the {rule_id} tier, requiring: {', '.join(approvals)}."
    return _RuleOutcome(
        checks=(PolicyCheck(rule_id, CheckStatus.FLAGGED, detail),),
        required_approvals=approvals,
    )


# ---------------------------------------------------------------------------
# Data-access classification — shared by POL-5 and POL-6
# ---------------------------------------------------------------------------

_SOURCE_CODE_KEYWORDS = ("source_code", "source code", "git")
_PROD_CLOUD_KEYWORDS = ("production", "cloud")
_CONFIDENTIAL_KEYWORDS = ("confidential",)
_PII_KEYWORDS = ("pii", "personal data", "personally identifiable")
_CREDENTIALS_KEYWORDS = ("credential", "secret", "password", "token")


@dataclass(frozen=True)
class DataAccessProfile:
    source_code_access: bool
    production_or_cloud_integration: bool
    confidential_documents: bool
    employee_or_customer_pii: bool
    credentials_or_secrets: bool


def classify_data_access(
    data_access_level: Optional[str], requested_integrations: Optional[tuple[str, ...]]
) -> DataAccessProfile:
    """Deterministic keyword classification of the request's own declared
    data-access level and integrations against the POL-5 trigger categories.
    Operates only on these two structured/categorical fields — never on
    ``business_justification`` (see the module docstring re: POL-9).
    """
    haystack = " ".join(filter(None, [data_access_level or "", *(requested_integrations or ())])).lower()
    return DataAccessProfile(
        source_code_access=any(k in haystack for k in _SOURCE_CODE_KEYWORDS),
        production_or_cloud_integration=any(k in haystack for k in _PROD_CLOUD_KEYWORDS),
        confidential_documents=any(k in haystack for k in _CONFIDENTIAL_KEYWORDS),
        employee_or_customer_pii=any(k in haystack for k in _PII_KEYWORDS),
        credentials_or_secrets=any(k in haystack for k in _CREDENTIALS_KEYWORDS),
    )


# ---------------------------------------------------------------------------
# Vendor security-assessment freshness/conflict resolution — feeds POL-5/10
# ---------------------------------------------------------------------------


class AssessmentState(str, Enum):
    CURRENT = "current"
    EXPIRED = "expired"
    NOT_COMPLETED = "not_completed"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    CONFLICTING = "conflicting"


def _within_validity(review_date: Optional[date], reference_date: date, validity_days: int) -> Optional[bool]:
    """``True``/``False`` if a review date is known, ``None`` if it is not —
    never collapses "unknown" into either a positive or negative answer.
    365 days from the review date counts as still current (inclusive).
    """
    if review_date is None:
        return None
    return (reference_date - review_date).days <= validity_days


def _status_is_approved(status: Optional[str]) -> Optional[bool]:
    if status is None:
        return None
    return status.strip().lower() == "approved"


def evaluate_vendor_security_assessment(
    registry: Optional[VendorRegistryEvidence],
    vendor_risk: Optional[VendorRiskEvidence],
    reference_date: date = REFERENCE_DATE,
) -> AssessmentState:
    """Resolve the vendor's security-assessment state from up to two
    independent sources, per POL-5 / POL-10.

    - If the live vendor-risk service is unavailable, the state is always
      ``UNAVAILABLE`` — the registry is never used as a favorable substitute
      for a service we could not reach (POL-10: "do not infer a favorable
      status").
    - If both sources are available and disagree on whether the vendor is
      currently approved, the state is ``CONFLICTING`` — neither side is
      silently preferred (POL-5).
    - Otherwise the live service's own status drives the result, with an
      independent 365-day freshness check applied to its review date as a
      defensive cross-check against a stale "approved" label.
    """
    if vendor_risk is None or vendor_risk.availability is VendorRiskAvailability.UNAVAILABLE:
        return AssessmentState.UNAVAILABLE

    registry_approved = _status_is_approved(registry.security_status) if registry is not None else None
    service_approved = _status_is_approved(vendor_risk.security_review_status)

    if registry_approved is not None and service_approved is not None and registry_approved != service_approved:
        return AssessmentState.CONFLICTING

    if vendor_risk.security_review_status is not None:
        status = vendor_risk.security_review_status.strip().lower()
        if status == "not_completed":
            return AssessmentState.NOT_COMPLETED
        if status == "expired":
            return AssessmentState.EXPIRED
        if status == "approved":
            fresh = _within_validity(vendor_risk.last_review_date, reference_date, SECURITY_ASSESSMENT_VALIDITY_DAYS)
            return AssessmentState.EXPIRED if fresh is False else AssessmentState.CURRENT

    return AssessmentState.MISSING


# ---------------------------------------------------------------------------
# POL-5 — security review
# ---------------------------------------------------------------------------

_ASSESSMENT_STATE_DETAIL = {
    AssessmentState.CONFLICTING: "Vendor registry and vendor-risk service disagree on approval status.",
    AssessmentState.UNAVAILABLE: "Vendor-risk service unavailable; security assessment could not be verified.",
    AssessmentState.EXPIRED: f"Vendor security assessment is older than {SECURITY_ASSESSMENT_VALIDITY_DAYS} days.",
    AssessmentState.NOT_COMPLETED: "Vendor security assessment has not been completed.",
    AssessmentState.MISSING: "Vendor security assessment status is unknown.",
    AssessmentState.CURRENT: "Vendor has a current security assessment on file.",
}

_ASSESSMENT_STATE_RISK_FLAG = {
    AssessmentState.CONFLICTING: "conflicting_vendor_evidence",
    AssessmentState.UNAVAILABLE: "vendor_risk_unavailable",
    AssessmentState.EXPIRED: "vendor_review_expired",
}

_DATA_ACCESS_SECURITY_TRIGGERS: tuple[tuple[str, str], ...] = (
    ("source_code_access", "source-code access requested"),
    ("production_or_cloud_integration", "production/cloud-account integration requested"),
    ("confidential_documents", "confidential-document access requested"),
    ("employee_or_customer_pii", "employee/customer PII involved"),
    ("credentials_or_secrets", "credentials/secrets access requested"),
)


def _check_security(profile: DataAccessProfile, assessment_state: AssessmentState) -> _RuleOutcome:
    checks: list[PolicyCheck] = []
    reasons: list[str] = []
    for attr, description in _DATA_ACCESS_SECURITY_TRIGGERS:
        if getattr(profile, attr):
            reasons.append(description)
            checks.append(PolicyCheck("POL-5", CheckStatus.FLAGGED, description.capitalize() + "."))

    risk_flags: list[str] = []
    assessment_detail = _ASSESSMENT_STATE_DETAIL[assessment_state]
    assessment_rule_id = "POL-10" if assessment_state is AssessmentState.UNAVAILABLE else "POL-5"
    assessment_ok = assessment_state is AssessmentState.CURRENT
    checks.append(
        PolicyCheck(assessment_rule_id, CheckStatus.OK if assessment_ok else CheckStatus.FLAGGED, assessment_detail)
    )
    if assessment_state in _ASSESSMENT_STATE_RISK_FLAG:
        risk_flags.append(_ASSESSMENT_STATE_RISK_FLAG[assessment_state])

    security_needed = bool(reasons) or not assessment_ok
    if security_needed:
        risk_flags.append("security_review_required")
    if not reasons and assessment_ok:
        checks.append(PolicyCheck("POL-5", CheckStatus.OK, "No security-sensitive data access requested."))

    approvals = ("Security",) if security_needed else ()
    return _RuleOutcome(checks=tuple(checks), required_approvals=approvals, risk_flags=tuple(risk_flags))


# ---------------------------------------------------------------------------
# POL-6 — privacy
# ---------------------------------------------------------------------------


def _check_privacy(profile: DataAccessProfile, vendor_risk: Optional[VendorRiskEvidence]) -> _RuleOutcome:
    reasons: list[str] = []
    if profile.employee_or_customer_pii:
        reasons.append("request involves employee/customer PII")
    if vendor_risk is not None and vendor_risk.availability is VendorRiskAvailability.AVAILABLE:
        if vendor_risk.processes_personal_data:
            reasons.append("vendor processes personal data")
        if vendor_risk.stores_data_outside_region:
            reasons.append("vendor stores data outside the operating region")

    if not reasons:
        return _RuleOutcome(checks=(PolicyCheck("POL-6", CheckStatus.OK, "No privacy trigger identified."),))

    detail = "; ".join(reasons).capitalize() + "."
    return _RuleOutcome(
        checks=(PolicyCheck("POL-6", CheckStatus.FLAGGED, detail),),
        required_approvals=("Privacy",),
        risk_flags=("privacy_review_required",),
    )


# ---------------------------------------------------------------------------
# POL-7 — legal
# ---------------------------------------------------------------------------


def _check_legal(
    request: RequestFields,
    vendor_registry: Optional[VendorRegistryEvidence],
    vendor_risk: Optional[VendorRiskEvidence],
) -> _RuleOutcome:
    reasons: list[str] = []

    is_new_vendor = (
        vendor_registry is not None
        and vendor_registry.procurement_status is not None
        and vendor_registry.procurement_status.strip().lower() == "new"
    )
    if is_new_vendor and request.annual_cost_usd is not None and request.annual_cost_usd >= LEGAL_NEW_VENDOR_SPEND_THRESHOLD_USD:
        reasons.append(f"new vendor with annual spend at or above ${LEGAL_NEW_VENDOR_SPEND_THRESHOLD_USD}")

    non_standard_terms = (
        vendor_registry is not None
        and vendor_registry.legal_terms_status is not None
        and vendor_registry.legal_terms_status.strip().lower() != "approved"
    )
    if non_standard_terms:
        reasons.append("legal terms are not approved/standard")

    cross_region = (
        vendor_risk is not None
        and vendor_risk.availability is VendorRiskAvailability.AVAILABLE
        and vendor_risk.stores_data_outside_region is True
    )
    if cross_region:
        reasons.append("vendor stores data outside the operating region")

    if not reasons:
        return _RuleOutcome(checks=(PolicyCheck("POL-7", CheckStatus.OK, "No legal trigger identified."),))

    detail = "; ".join(reasons).capitalize() + "."
    return _RuleOutcome(
        checks=(PolicyCheck("POL-7", CheckStatus.FLAGGED, detail),),
        required_approvals=("Legal",),
        risk_flags=("legal_review_required",),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def evaluate_policy(context: PolicyContext) -> PolicyEvaluation:
    """Deterministically evaluate POL-1 through POL-11 against ``context``.

    Same input always produces the same output: no randomness, no clock, no
    I/O. POL-8 (AI tools follow normal rules) and POL-11 (human authority is
    never bypassed) are satisfied structurally — there is no AI-category
    special case anywhere below, and ``human_review_required`` is always
    ``True``. POL-9 (prompt injection) is satisfied structurally too: no rule
    function below ever reads ``request.business_justification``.
    """
    profile = classify_data_access(context.request.data_access_level, context.request.requested_integrations)
    assessment_state = evaluate_vendor_security_assessment(
        context.vendor_registry, context.vendor_risk, context.reference_date
    )

    outcomes = (
        _check_required_fields(context.request),
        _check_budget(context.request, context.budget),
        _check_overlap(context.catalog_overlap_matches),
        _check_financial_threshold(context.request.annual_cost_usd),
        _check_security(profile, assessment_state),
        _check_privacy(profile, context.vendor_risk),
        _check_legal(context.request, context.vendor_registry, context.vendor_risk),
    )

    checks = tuple(check for outcome in outcomes for check in outcome.checks)
    required_approvals = _dedupe_preserve_order(a for o in outcomes for a in o.required_approvals)
    missing_information = _dedupe_preserve_order(m for o in outcomes for m in o.missing_information)
    risk_flags = list(_dedupe_preserve_order(r for o in outcomes for r in o.risk_flags))
    if missing_information and "missing_information" not in risk_flags:
        risk_flags.append("missing_information")

    return PolicyEvaluation(
        request_id=context.request.request_id,
        policy_version=POLICY_VERSION,
        reference_date=context.reference_date,
        checks=checks,
        required_approvals=required_approvals,
        missing_information=missing_information,
        risk_flags=tuple(risk_flags),
        # The copilot is recommendation-only (POL-11): every evaluation always
        # requires human review. This is a fixed value, not a computed one, so
        # no future bug in the rules above can accidentally imply autonomous
        # approval authority.
        human_review_required=True,
    )
