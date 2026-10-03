"""Each run-level invariant must (a) pass on a real valid run and (b) fail on
the specific fault it exists to catch. An invariant that passes its own mutant
is a bug in the check."""

from __future__ import annotations

import dataclasses

import pytest

from evaluation.run_invariants import check_run
from src.agent.single_agent import run_single_agent_with_trace
from src.contracts import EvidenceItem
from tests.agent_fakes import ScriptedGeminiClient, stop_turn, tool_call, tool_turn
from tests.test_agent_single import _synthesis


@pytest.fixture
def valid_run():
    client = ScriptedGeminiClient(
        turns=[tool_turn(tool_call("get_employee_budget", employee_id="E004")), stop_turn()],
        structured_result=_synthesis(evidence_refs=["E1"]),
    )
    return run_single_agent_with_trace("REQ-1001", client=client)


def _status(run) -> dict:
    return {c.name: c.passed for c in check_run(run)}


def test_every_check_passes_on_a_valid_run(valid_run):
    assert all(_status(valid_run).values()), check_run(valid_run)


def test_approvals_check_catches_an_added_approval(valid_run):
    decision = valid_run.decision.model_copy(update={"required_approvals": [*valid_run.decision.required_approvals, "CFO"]})
    mutant = dataclasses.replace(valid_run, decision=decision)
    assert _status(mutant)["approvals_follow_policy"] is False


def test_approvals_check_catches_a_dropped_approval(valid_run):
    decision = valid_run.decision.model_copy(update={"required_approvals": valid_run.decision.required_approvals[1:]})
    mutant = dataclasses.replace(valid_run, decision=decision)
    assert _status(mutant)["approvals_follow_policy"] is False


def test_flags_check_catches_a_dropped_policy_flag(valid_run):
    policy = dataclasses.replace(valid_run.policy_evaluation, risk_flags=("security_review_required",))
    decision = valid_run.decision.model_copy(update={"risk_flags": []})
    mutant = dataclasses.replace(valid_run, decision=decision, policy_evaluation=policy)
    assert _status(mutant)["flags_follow_policy"] is False


def test_flags_check_allows_only_the_injection_signal_as_an_extra_flag(valid_run):
    decision = valid_run.decision.model_copy(update={"risk_flags": [*valid_run.decision.risk_flags, "prompt_injection_detected"]})
    assert _status(dataclasses.replace(valid_run, decision=decision))["flags_follow_policy"] is True
    decision = valid_run.decision.model_copy(update={"risk_flags": [*valid_run.decision.risk_flags, "made_up_flag"]})
    assert _status(dataclasses.replace(valid_run, decision=decision))["flags_follow_policy"] is False


def test_missing_info_check_catches_a_fabricated_missing_item(valid_run):
    decision = valid_run.decision.model_copy(update={"missing_information": ["annual cost"]})
    assert _status(dataclasses.replace(valid_run, decision=decision))["missing_follow_policy"] is False


def test_human_review_check_catches_a_downgrade(valid_run):
    decision = valid_run.decision.model_copy(update={"human_review_required": False})
    assert _status(dataclasses.replace(valid_run, decision=decision))["human_review_required"] is False


def test_approval_claim_check_catches_an_unguarded_claim(valid_run):
    decision = valid_run.decision.model_copy(update={"recommendation": "This purchase has been approved by the CFO."})
    assert _status(dataclasses.replace(valid_run, decision=decision))["no_approval_claim_in_text"] is False


def test_approval_claim_check_catches_a_claim_in_the_rationale(valid_run):
    mutant = dataclasses.replace(valid_run, agent_rationale="Finance signed off on this yesterday.")
    assert _status(mutant)["no_approval_claim_in_text"] is False


def test_evidence_check_catches_an_invented_citation(valid_run):
    invented = EvidenceItem(source="made_up_source", finding="the vendor is certified", reference="none")
    decision = valid_run.decision.model_copy(update={"evidence": [*valid_run.decision.evidence, invented]})
    assert _status(dataclasses.replace(valid_run, decision=decision))["cited_evidence_was_retrieved"] is False
