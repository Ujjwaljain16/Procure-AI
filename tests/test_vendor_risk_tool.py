"""Tests for src/tools/vendor_risk.py.

`src.vendor_client.get_vendor_risk` is monkeypatched at the tool's import
boundary (`vendor_risk_tool.vendor_client.get_vendor_risk`) rather than
requiring a real running mock API process. This exercises exactly what this
module owns -- translating that client's documented success/HTTPError/
RequestException contract into safe VendorRiskEvidence states -- without a
flaky dependency on a live server. The mock API's own request/response
handling is separately covered by tests/test_mock_api.py.

Response payloads used below are the actual values from data/vendor_risk.json
and data/vendors.csv where noted.
"""

from __future__ import annotations

import requests

from src.policy_engine import VendorRiskAvailability
from src.tools import vendor_risk as vendor_risk_tool


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


class TestNormalVendor:
    def test_successful_live_response_is_preserved(self, monkeypatch):
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "vendor_name": "PixelCraft",
                "risk_level": "low",
                "security_review_status": "approved",
                "last_review_date": "2026-04-12",
                "processes_personal_data": False,
                "stores_data_outside_region": False,
                "notes": "Current assessment.",
            },
        )
        result = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        assert result.vendor_risk.availability is VendorRiskAvailability.AVAILABLE
        assert result.vendor_risk.security_review_status == "approved"
        assert result.registry is not None
        assert result.registry.vendor_name == "PixelCraft"
        assert result.registry.security_status == "Approved"

    def test_no_conflict_note_when_sources_agree(self, monkeypatch):
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {"security_review_status": "approved", "last_review_date": "2026-04-12"},
        )
        result = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        assert not any("disagree" in item.finding.lower() for item in result.evidence)


class TestUnknownVendor:
    def test_404_becomes_unavailable_not_fabricated(self, monkeypatch):
        def raise_404(name, timeout_seconds=3.0):
            raise _http_error(404)

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", raise_404)
        result = vendor_risk_tool.get_vendor_evidence("Nonexistent Vendor XYZ")
        assert result.vendor_risk.availability is VendorRiskAvailability.UNAVAILABLE
        assert result.registry is None
        assert any("404" in item.finding for item in result.evidence)


class TestNimbusAiOutage:
    def test_503_becomes_unavailable_never_approved(self, monkeypatch):
        def raise_503(name, timeout_seconds=3.0):
            raise _http_error(503)

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", raise_503)
        result = vendor_risk_tool.get_vendor_evidence("NimbusAI")
        assert result.vendor_risk.availability is VendorRiskAvailability.UNAVAILABLE
        assert result.vendor_risk.security_review_status is None

    def test_registry_side_is_still_preserved_despite_live_outage(self, monkeypatch):
        def raise_503(name, timeout_seconds=3.0):
            raise _http_error(503)

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", raise_503)
        result = vendor_risk_tool.get_vendor_evidence("NimbusAI")
        # NimbusAI's real registry row: procurement_status=New, security_status=Unknown
        assert result.registry is not None
        assert result.registry.vendor_name == "NimbusAI"
        assert result.registry.security_status == "Unknown"

    def test_connection_failure_also_becomes_unavailable(self, monkeypatch):
        def raise_connection_error(name, timeout_seconds=3.0):
            raise requests.ConnectionError("simulated network failure")

        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", raise_connection_error)
        result = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        assert result.vendor_risk.availability is VendorRiskAvailability.UNAVAILABLE


class TestSignalWatchConflict:
    def test_disagreement_is_surfaced_not_resolved(self, monkeypatch):
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {
                "vendor_name": "SignalWatch",
                "risk_level": "medium",
                "security_review_status": "expired",
                "last_review_date": "2025-07-01",
                "processes_personal_data": False,
                "stores_data_outside_region": False,
                "notes": "Reassessment required before expanded production access.",
            },
        )
        result = vendor_risk_tool.get_vendor_evidence("SignalWatch")
        # both raw claims preserved, neither discarded
        assert result.registry.security_status == "Approved"
        assert result.vendor_risk.security_review_status == "expired"
        conflict_notes = [item for item in result.evidence if "disagree" in item.finding.lower()]
        assert len(conflict_notes) == 1
        assert "Approved" in conflict_notes[0].finding
        assert "expired" in conflict_notes[0].finding


class TestMalformedResponse:
    def test_missing_fields_in_payload_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(vendor_risk_tool.vendor_client, "get_vendor_risk", lambda name, timeout_seconds=3.0: {})
        result = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        assert result.vendor_risk.availability is VendorRiskAvailability.AVAILABLE
        assert result.vendor_risk.security_review_status is None
        assert result.vendor_risk.last_review_date is None


class TestEvidenceProvenance:
    def test_evidence_references_the_actual_endpoint_and_source_file(self, monkeypatch):
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {"security_review_status": "approved", "last_review_date": "2026-04-12"},
        )
        result = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        references = [item.reference for item in result.evidence]
        assert "GET /vendor-risk/PixelCraft" in references
        assert any(ref is not None and ref.startswith("vendors.csv") for ref in references)


class TestDeterminism:
    def test_repeated_call_with_same_dependency_behavior_is_stable(self, monkeypatch):
        monkeypatch.setattr(
            vendor_risk_tool.vendor_client,
            "get_vendor_risk",
            lambda name, timeout_seconds=3.0: {"security_review_status": "approved", "last_review_date": "2026-04-12"},
        )
        first = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        second = vendor_risk_tool.get_vendor_evidence("PixelCraft")
        assert first == second


class TestMockApiEncodingAndErrors:
    def test_percent_encoded_vendor_name_is_decoded_exactly_once(self):
        from fastapi.testclient import TestClient

        from mock_api.app import app

        client = TestClient(app)
        response = client.get("/vendor-risk/SignalWatch")
        assert response.status_code == 200
        assert response.json()["vendor_name"] == "SignalWatch"

    def test_unknown_vendor_error_does_not_echo_the_input(self):
        from fastapi.testclient import TestClient

        from mock_api.app import app

        response = TestClient(app).get("/vendor-risk/%3Cscript%3E")
        assert response.status_code == 404
        assert "<script>" not in response.text
