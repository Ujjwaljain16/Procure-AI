"""Tests for evaluation/adversarial.py, in replay mode only (free, no API
quota). Replay mode can't exercise genuine model reasoning, but it does
verify the variant-generation and request-patching machinery actually works
end-to-end against the real pipeline -- see the module docstring for why
replay mode's deterministic-field match is expected by construction, and why
--real mode is where this tool's real safety value shows.
"""

from __future__ import annotations

import pytest

from evaluation.adversarial import VARIANTS, run_adversarial_family


class TestRunAdversarialFamily:
    def test_runs_every_registered_variant(self):
        result = run_adversarial_family("TC-02", "single", use_real=False)
        assert set(result["variants"]) == set(VARIANTS)

    def test_replay_mode_variants_match_the_base_by_construction(self):
        # The replay client never reads business_justification, and no
        # policy-engine rule reads free-text fields either, so every variant
        # must be deterministic-field-identical to the base in replay mode.
        result = run_adversarial_family("TC-02", "single", use_real=False)
        assert result["all_variants_consistent"]
        for v in result["variants"].values():
            assert v["passed"]
            assert v["diffs_from_base"] == []

    def test_injection_variants_carry_the_expected_text(self):
        result = run_adversarial_family("TC-02", "single", use_real=False)
        assert "ignore" in result["variants"]["injection_imperative"]["business_justification"].lower()

    def test_does_not_mutate_the_real_request_data(self):
        from src import data_access

        before = data_access.get_request("REQ-1001")["business_justification"]
        run_adversarial_family("TC-02", "single", use_real=False)
        after = data_access.get_request("REQ-1001")["business_justification"]
        assert before == after

    def test_rejects_a_policy_level_case(self):
        with pytest.raises(ValueError):
            run_adversarial_family("TC-16a", "single", use_real=False)

    def test_rejects_an_unknown_case_id(self):
        with pytest.raises(ValueError):
            run_adversarial_family("TC-999", "single", use_real=False)

    def test_works_for_staged_architecture_too(self):
        result = run_adversarial_family("TC-02", "staged", use_real=False)
        assert result["all_variants_consistent"]
