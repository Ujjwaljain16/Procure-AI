"""Vendor registry + live vendor-risk retrieval tool.

Crosses two independent sources for a vendor:

* the internal procurement registry (``vendors.csv``), read locally; and
* the live vendor-risk service (``src/vendor_client.py``), called over HTTP.

Both observations are returned as-is. This tool never decides whether the two
sources agree, whether an assessment is still valid, or what approvals that
implies -- that is ``evaluate_vendor_security_assessment`` /
``evaluate_policy`` in ``src/policy_engine.py``. Where the two raw statuses
visibly disagree, an extra, purely observational evidence item notes the
disagreement; it does not change what is returned to the policy engine.

``src/vendor_client.get_vendor_risk`` raises on any non-2xx response (see its
docstring) -- this module is the safety boundary around that call. A 503
(e.g. NimbusAI's simulated outage) or a 404 (unknown vendor) both become an
explicit ``VendorRiskEvidence.unavailable(...)``, never a favorable inference
and never an uncaught crash.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from src import data_access, vendor_client
from src.contracts import EvidenceItem
from src.policy_engine import VendorRegistryEvidence, VendorRiskAvailability, VendorRiskEvidence


@dataclass(frozen=True)
class VendorEvidenceResult:
    registry: VendorRegistryEvidence | None
    vendor_risk: VendorRiskEvidence
    evidence: tuple[EvidenceItem, ...]


def _load_registry_evidence(vendor_name: str) -> tuple[VendorRegistryEvidence | None, EvidenceItem]:
    vendors = data_access.load_vendors()
    match = vendors[vendors["vendor_name"] == vendor_name]
    if match.empty:
        return None, EvidenceItem(
            source="vendor_registry",
            finding=f"No internal registry record found for vendor '{vendor_name}'.",
            reference="vendors.csv",
        )
    registry = VendorRegistryEvidence.from_row(match.iloc[0].to_dict())
    finding = (
        f"Registry status for {vendor_name}: procurement={registry.procurement_status}, "
        f"security={registry.security_status}, security_review_date={registry.security_review_date}."
    )
    return registry, EvidenceItem(source="vendor_registry", finding=finding, reference=f"vendors.csv:{registry.vendor_name}")


def _load_vendor_risk_evidence(vendor_name: str) -> tuple[VendorRiskEvidence, EvidenceItem]:
    endpoint_reference = f"GET /vendor-risk/{vendor_name}"
    try:
        payload = vendor_client.get_vendor_risk(vendor_name)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 404:
            finding = f"No vendor-risk record exists for '{vendor_name}' (HTTP 404)."
        else:
            finding = f"Vendor-risk service returned an error for '{vendor_name}' (HTTP {status_code})."
        return VendorRiskEvidence.unavailable(vendor_name), EvidenceItem(
            source="vendor_risk_service", finding=finding, reference=endpoint_reference
        )
    except requests.RequestException as exc:
        finding = f"Vendor-risk service was unreachable for '{vendor_name}': {type(exc).__name__}."
        return VendorRiskEvidence.unavailable(vendor_name), EvidenceItem(
            source="vendor_risk_service", finding=finding, reference=endpoint_reference
        )

    vendor_risk = VendorRiskEvidence.from_api_response(vendor_name, payload)
    finding = f"Vendor-risk service reports security_review_status={vendor_risk.security_review_status} for {vendor_name}."
    return vendor_risk, EvidenceItem(source="vendor_risk_service", finding=finding, reference=endpoint_reference)


def _status_is_approved_text(status: str | None) -> bool | None:
    if status is None:
        return None
    return status.strip().lower() == "approved"


def get_vendor_evidence(vendor_name: str) -> VendorEvidenceResult:
    vendor_name = (vendor_name or "").strip()
    registry, registry_evidence = _load_registry_evidence(vendor_name)
    vendor_risk, vendor_risk_evidence = _load_vendor_risk_evidence(vendor_name)

    evidence = [registry_evidence, vendor_risk_evidence]

    # Purely observational: note a raw-status disagreement between the two
    # sources without resolving it. The policy engine independently computes
    # AssessmentState.CONFLICTING from `registry` + `vendor_risk` regardless
    # of this note; this is evidence for a human/agent, not a decision.
    if registry is not None and vendor_risk.availability is VendorRiskAvailability.AVAILABLE:
        registry_approved = _status_is_approved_text(registry.security_status)
        service_approved = _status_is_approved_text(vendor_risk.security_review_status)
        if registry_approved is not None and service_approved is not None and registry_approved != service_approved:
            evidence.append(
                EvidenceItem(
                    source="vendor_risk_service",
                    finding=(
                        f"Registry and vendor-risk service disagree on {vendor_name}'s security status "
                        f"(registry: {registry.security_status}, service: {vendor_risk.security_review_status})."
                    ),
                    reference=f"vendors.csv:{vendor_name} vs GET /vendor-risk/{vendor_name}",
                )
            )

    return VendorEvidenceResult(registry=registry, vendor_risk=vendor_risk, evidence=tuple(evidence))
