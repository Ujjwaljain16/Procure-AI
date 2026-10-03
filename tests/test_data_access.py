"""Tests for src/data_access.py's get_request_validated -- the deterministic
pre-analysis gate: a narrow structural check, never a re-implementation of
any src/policy_engine.py business rule.
"""

from __future__ import annotations

import pytest

from src.data_access import MalformedRequestError, get_request_validated


class TestGetRequestValidated:
    def test_a_real_well_formed_request_passes_through_unchanged(self):
        request = get_request_validated("REQ-1001")
        assert request["request_id"] == "REQ-1001"

    def test_unknown_request_id_still_raises_key_error(self):
        with pytest.raises(KeyError):
            get_request_validated("REQ-DOES-NOT-EXIST")

    def test_missing_a_required_key_raises_malformed_request_error(self, monkeypatch):
        import src.data_access as data_access_module

        broken = {"request_id": "REQ-BROKEN", "requester_id": "E001", "product_name": "Tool"}  # no vendor_name
        monkeypatch.setattr(data_access_module, "load_requests", lambda: [broken])
        with pytest.raises(MalformedRequestError, match="vendor_name"):
            get_request_validated("REQ-BROKEN")

    def test_non_numeric_annual_cost_raises_malformed_request_error(self, monkeypatch):
        import src.data_access as data_access_module

        broken = {
            "request_id": "REQ-BROKEN",
            "requester_id": "E001",
            "product_name": "Tool",
            "vendor_name": "PixelCraft",
            "annual_cost_usd": "not-a-number",
        }
        monkeypatch.setattr(data_access_module, "load_requests", lambda: [broken])
        with pytest.raises(MalformedRequestError, match="annual_cost_usd"):
            get_request_validated("REQ-BROKEN")

    def test_non_numeric_user_count_raises_malformed_request_error(self, monkeypatch):
        import src.data_access as data_access_module

        broken = {
            "request_id": "REQ-BROKEN",
            "requester_id": "E001",
            "product_name": "Tool",
            "vendor_name": "PixelCraft",
            "user_count": "a lot",
        }
        monkeypatch.setattr(data_access_module, "load_requests", lambda: [broken])
        with pytest.raises(MalformedRequestError, match="user_count"):
            get_request_validated("REQ-BROKEN")

    def test_a_null_annual_cost_is_not_malformed_its_genuinely_missing(self, monkeypatch):
        """None is a legitimate 'not provided' value -- POL-1's job to flag,
        not this gate's. Only a present-but-wrong-type value is malformed."""
        import src.data_access as data_access_module

        request = {
            "request_id": "REQ-OK",
            "requester_id": "E001",
            "product_name": "Tool",
            "vendor_name": "PixelCraft",
            "annual_cost_usd": None,
            "user_count": None,
        }
        monkeypatch.setattr(data_access_module, "load_requests", lambda: [request])
        assert get_request_validated("REQ-OK") == request

    def test_does_not_flag_missing_business_fields_that_policy_engine_owns(self, monkeypatch):
        """No business_justification, no data_access_level -- both are
        POL-1's job (missing_information), not this structural gate's."""
        import src.data_access as data_access_module

        request = {"request_id": "REQ-OK", "requester_id": "E001", "product_name": "Tool", "vendor_name": "PixelCraft"}
        monkeypatch.setattr(data_access_module, "load_requests", lambda: [request])
        assert get_request_validated("REQ-OK") == request
