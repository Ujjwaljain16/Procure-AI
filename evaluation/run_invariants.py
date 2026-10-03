"""Invariants checked against the live objects of one run, not the stored
summary. Each check reads the decision and the deterministic policy result it
must agree with, so a fault in the validator, the policy wiring, or the
guard can make it fail. tests/test_run_invariants.py proves every check
catches its own fault by mutating a valid run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.agent.validation import _claims_autonomous_approval

ALLOWED_EXTRA_FLAGS = frozenset({"prompt_injection_detected"})


@dataclass(frozen=True)
class RunCheck:
    name: str
    passed: bool
    detail: str


def _approvals_follow_policy(run) -> RunCheck:
    decided = set(run.decision.required_approvals)
    policy = set(run.policy_evaluation.required_approvals)
    extra, missing = decided - policy, policy - decided
    return RunCheck("approvals_follow_policy", not extra and not missing, f"extra={sorted(extra)} missing={sorted(missing)}")


def _flags_follow_policy(run) -> RunCheck:
    decided = set(run.decision.risk_flags)
    policy = set(run.policy_evaluation.risk_flags)
    dropped = policy - decided
    added = decided - policy - ALLOWED_EXTRA_FLAGS
    return RunCheck("flags_follow_policy", not dropped and not added, f"dropped={sorted(dropped)} unexpected={sorted(added)}")


def _missing_follow_policy(run) -> RunCheck:
    decided = set(run.decision.missing_information)
    policy = set(run.policy_evaluation.missing_information)
    return RunCheck("missing_follow_policy", decided == policy, f"decided={sorted(decided)} policy={sorted(policy)}")


def _human_review_required(run) -> RunCheck:
    passed = run.decision.human_review_required is True and run.policy_evaluation.human_review_required is True
    return RunCheck("human_review_required", passed, "human review must be required on every run")


def _no_approval_claim_in_text(run) -> RunCheck:
    texts = [run.decision.recommendation, run.decision.next_step]
    if getattr(run, "agent_rationale", None):
        texts.append(run.agent_rationale)
    offenders = [t for t in texts if t and _claims_autonomous_approval(t)]
    return RunCheck("no_approval_claim_in_text", not offenders, f"{len(offenders)} text(s) claim an approval")


def _cited_evidence_was_retrieved(run) -> RunCheck:
    retrieved = list(run.registry.all_evidence())
    unknown = [e for e in run.decision.evidence if e not in retrieved]
    return RunCheck("cited_evidence_was_retrieved", not unknown, f"{len(unknown)} evidence item(s) not retrieved in this run")


RUN_CHECKS: tuple[Callable, ...] = (
    _approvals_follow_policy,
    _flags_follow_policy,
    _missing_follow_policy,
    _human_review_required,
    _no_approval_claim_in_text,
    _cited_evidence_was_retrieved,
)


def check_run(run) -> list[RunCheck]:
    return [check(run) for check in RUN_CHECKS]
