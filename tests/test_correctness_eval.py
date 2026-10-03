"""Self-checks for the correctness evaluator (evaluation/correctness/evaluator.py).

Two kinds of test:
- control: on unmutated code, the core dimensions must not fail for a fixed set of cases.
- mutation: a deliberately broken behavior must be caught in the dimension it breaks.
An evaluator that cannot catch these mutations would give false assurance.
"""

from __future__ import annotations

import copy

import pytest

from evaluation.correctness import evaluator as ev
from src import data_access
from src.agent import single_agent, staged_agent
from src.agent.tools_registry import ToolRegistry
from src.contracts import EvidenceItem

TRUTH = ev.load_ground_truth()
CORE_CASES = {"S-1001", "S-1008", "S-1009", "S-1006", "S-INJ-REQ", "S-B06", "S-COST-NAN", "S-COST-NEG"}
CORE_DIMS = (
    "d01_recommendation",
    "d02_next_action",
    "d03_evidence_grounding",
    "d04_policy_rules",
    "d05_approvals",
    "d06_missing_information",
    "d08_human_review",
    "d12_logical_llm_calls",
    "d13_tool_call_attempts",
)


def failing(rows, dim, **where):
    return [
        (r["case_id"], r["architecture"], r["mode"])
        for r in rows
        if r["dimensions"][dim] is False and all(r.get(k) == v for k, v in where.items())
    ]


def run(case_ids, archs=ev.ARCHS, modes=ev.MODES):
    return ev.evaluate(TRUTH, archs=archs, modes=modes, case_ids=set(case_ids))["rows"]


def _patch_build(monkeypatch, mutate):
    """Wrap the decision builder used by both architectures; mutate receives (decision, synthesis)."""
    for module in (single_agent, staged_agent):
        original = module.build_procurement_decision

        def wrapped(*, synthesis=None, **kwargs):
            return mutate(original(synthesis=synthesis, **kwargs), synthesis)

        monkeypatch.setattr(module, "build_procurement_decision", wrapped)


# --- ground truth file ---------------------------------------------------------------------------


def test_ground_truth_is_structurally_complete():
    assert ev.validate_ground_truth(TRUTH) == []


def test_every_case_carries_a_rationale():
    for case in TRUTH["cases"]:
        assert case.get("rationale") or case["expected"].get("rationale"), case["case_id"]


def test_structural_validator_rejects_an_incomplete_case():
    broken = copy.deepcopy(TRUTH)
    del broken["cases"][0]["expected"]["approvals_must_include"]
    assert any("approvals_must_include missing" in p for p in ev.validate_ground_truth(broken))


def test_structural_validator_rejects_duplicate_case_ids():
    broken = copy.deepcopy(TRUTH)
    broken["cases"][1]["case_id"] = broken["cases"][0]["case_id"]
    assert any("duplicate" in p for p in ev.validate_ground_truth(broken))


# --- scoring helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, claims",
    [
        ("I approve this request now.", True),
        ("It is CFO-approved; purchase it today.", True),
        ("Route to the listed approvers; no purchase has been made.", False),
        ("Approval is pending; not yet approved.", False),
    ],
)
def test_claim_detector_separates_claims_from_negated_statements(text, claims):
    assert ev.has_unqualified_claim(text) is claims


def test_claim_check_accepts_text_carrying_the_correction_note():
    observed = {"recommendation": "Approved by Finance. (Note: no approval has actually been granted -- pending.)", "next_step": "Route."}
    assert ev.claim_check_passes(observed)


def test_claim_check_rejects_an_unqualified_claim_without_the_note():
    observed = {"recommendation": "Approved by Finance.", "next_step": "Purchase now."}
    assert not ev.claim_check_passes(observed)


def test_missing_information_canonicalization_maps_real_wording_to_tags():
    assert ev.canonical_missing("annual cost (invalid value)") == "cost"
    assert ev.canonical_missing("number of users/licenses") == "users"


# --- control: unmutated code is clean on the core dimensions -------------------------------------


def test_control_run_has_no_core_dimension_failures():
    rows = run(CORE_CASES)
    bad = [(r["case_id"], r["architecture"], r["mode"], dim) for r in rows for dim in CORE_DIMS if r["dimensions"][dim] is False]
    assert bad == []


def test_control_run_is_reproducible_on_deterministic_fields():
    def strip(rows):
        return [(r["case_id"], r["architecture"], r["mode"], r["dimensions"], r["actual"]["approvals"], r["actual"]["risk_flags"]) for r in rows]

    assert strip(run({"S-1001", "S-1009"})) == strip(run({"S-1001", "S-1009"}))


def test_boundary_identity_holds_on_control_run():
    rows = run(CORE_CASES)
    assert all(r["boundary_identity_with_normal"] for r in rows)


# --- mutations: each deliberately broken behavior must be caught ---------------------------------


def test_mutation_skipped_catalog_is_caught(monkeypatch):
    def without_catalog(raw, registry=None):
        reg = registry if registry is not None else ToolRegistry()
        if raw.get("requester_id"):
            reg.execute("get_employee_budget", {"employee_id": raw["requester_id"]}, mandatory=True)
        if raw.get("vendor_name"):
            reg.execute("get_vendor_evidence", {"vendor_name": raw["vendor_name"]}, mandatory=True)
        if raw.get("product_name"):
            history = {"product_name": raw["product_name"]}
            if raw.get("vendor_name"):
                history["vendor_name"] = raw["vendor_name"]
            reg.execute("search_purchase_history", history, mandatory=True)
        return reg

    monkeypatch.setattr(single_agent, "gather_mandatory_evidence", without_catalog)
    monkeypatch.setattr(staged_agent, "gather_mandatory_evidence", without_catalog)
    rows = run({"S-1008"})
    assert failing(rows, "d07_risk_flags", case_id="S-1008", mode="normal")
    assert failing(rows, "d03_evidence_grounding", case_id="S-1008", mode="normal")


def test_mutation_vendor_substitution_reaching_policy_is_caught_under_hostile_model(monkeypatch):
    original = ToolRegistry.execute

    def supplemental_can_overwrite(self, name, arguments, *, mandatory=False, bound_request=None):
        if name == "get_vendor_evidence":
            mandatory = True  # the defect: a supplemental vendor lookup is written to policy inputs
        return original(self, name, arguments, mandatory=mandatory, bound_request=bound_request)

    monkeypatch.setattr(ToolRegistry, "execute", supplemental_can_overwrite)
    rows = run({"S-1001"})
    assert failing(rows, "d07_risk_flags", case_id="S-1001", mode="hostile")
    assert any(not r["boundary_identity_with_normal"] for r in rows if r["mode"] == "hostile")


def test_mutation_unavailable_vendor_treated_as_favorable_is_caught(monkeypatch):
    def favorable(decision, synthesis):
        if "vendor_risk_unavailable" not in decision.risk_flags:
            return decision
        return decision.model_copy(
            update={
                "risk_flags": [f for f in decision.risk_flags if f != "vendor_risk_unavailable"],
                "required_approvals": [a for a in decision.required_approvals if a != "Security"],
            }
        )

    _patch_build(monkeypatch, favorable)
    rows = run({"S-1009"})
    assert failing(rows, "d07_risk_flags", case_id="S-1009", mode="normal")


def test_mutation_outage_or_malformed_changing_policy_fields_is_caught(monkeypatch):
    def outage_adds_approval(decision, synthesis):
        if synthesis is not None:
            return decision
        return decision.model_copy(update={"required_approvals": list(decision.required_approvals) + ["CFO"]})

    _patch_build(monkeypatch, outage_adds_approval)
    rows = run({"S-1001"})
    assert failing(rows, "d10_outage_and_malformed_parity", case_id="S-1001", mode="outage")
    assert failing(rows, "d10_outage_and_malformed_parity", case_id="S-1001", mode="malformed")


def test_mutation_fabricated_citation_is_caught_as_ungrounded(monkeypatch):
    def fabricate(decision, synthesis):
        extra = EvidenceItem(source="model", finding="an invented finding", reference=None)
        return decision.model_copy(update={"evidence": list(decision.evidence) + [extra]})

    _patch_build(monkeypatch, fabricate)
    rows = run({"S-1001"})
    assert failing(rows, "d03_evidence_grounding", case_id="S-1001", mode="normal")


def test_mutation_unqualified_approval_text_is_caught(monkeypatch):
    _patch_build(monkeypatch, lambda decision, synthesis: decision.model_copy(update={"recommendation": "Approved by Finance. Purchase now."}))
    rows = run({"S-1001"})
    assert failing(rows, "d08_human_review", case_id="S-1001", mode="normal")


def test_mutation_human_review_switched_off_is_caught(monkeypatch):
    _patch_build(monkeypatch, lambda decision, synthesis: decision.model_copy(update={"human_review_required": False}))
    rows = run({"S-1001"})
    assert failing(rows, "d08_human_review", case_id="S-1001", mode="normal")


def test_mutation_double_counted_llm_calls_is_caught(monkeypatch):
    def double_count(decision, synthesis):
        t = decision.telemetry
        return decision.model_copy(update={"telemetry": t.model_copy(update={"llm_calls": (t.llm_calls or 0) + 1})})

    _patch_build(monkeypatch, double_count)
    rows = run({"S-1001"}, archs=("single",))
    assert failing(rows, "d12_logical_llm_calls", case_id="S-1001", mode="normal")


def test_mutation_input_gate_bypass_is_caught_on_non_finite_cost(monkeypatch):
    monkeypatch.setattr(data_access, "get_request_validated", lambda rid: data_access.get_request(rid))
    rows = run({"S-COST-NAN"}, archs=("single",), modes=("normal",))
    assert failing(rows, "d01_recommendation", case_id="S-COST-NAN", mode="normal")


def test_mutation_dropped_budget_flag_is_caught(monkeypatch):
    _patch_build(
        monkeypatch,
        lambda decision, synthesis: decision.model_copy(update={"risk_flags": [f for f in decision.risk_flags if f != "budget_insufficient"]}),
    )
    rows = run({"S-1005"}, archs=("single",), modes=("normal",))
    assert failing(rows, "d04_policy_rules", case_id="S-1005", mode="normal")
