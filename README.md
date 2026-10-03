# ProcureAI — AI Procurement Request Copilot

An internal procurement decision-support tool: an employee submits a software or service request, the system gathers evidence with code the model cannot influence, applies deterministic company policy, and recommends a next action. Every approval stays with a human. Built for the FDE Assessment 3 brief.

> **Status of the evidence.** The deterministic authority boundary and policy behaviour are extensively tested offline. A pre-registered real-model sample of sixteen cases was run once against both architectures; it is descriptive, not statistically significant. Its result and limits are stated below.

## Navigation

```
CURRENT SUBMISSION
  ├── Architecture ............... docs/architecture.md  (and "Architecture" below)
  ├── Current evaluation ......... docs/final_evaluation.md  (and "Evaluation" below)
  ├── Architecture comparison .... "Architecture comparison" below
  ├── Final ship decision ........ docs/architecture_decision.md
  └── Starter pack fixes ......... docs/starter_pack_fixes.md

ARCHIVE
  ├── Results index .............. evaluation/results/INDEX.md (replay) and evaluation/correctness/results/INDEX.md (live)
  └── Archived runs .............. evaluation/results/archive/ and evaluation/correctness/results/archive/
```

## Problem

Employees request new software. Procurement has to check existing tools, team budget, vendor status, security and privacy requirements, and approval rules before anything is bought. Doing that by hand is slow and inconsistent. Letting an AI decide unilaterally is unsafe. This product does the evidence-gathering and interpretation with AI, enforces every hard rule in code, and keeps every approval and exception with a human.

## Product

```
request → validation → evidence (code) → policy (code) → recommendation (AI) → validator → human (approval)
```

The request is validated structurally. Evidence is gathered by deterministic code from the request's own fields: employee and budget, catalog overlap, purchase history, and vendor registry and risk. The policy engine evaluates that evidence against the company rules. The AI interprets the evidence and writes a recommendation and rationale. The final validator combines them, and the policy fields are always taken from the policy engine, never from the model.

## Screenshots

All screenshots below are from a live run on `REQ-1003`, a source-code-access request for CodeMate (annual cost $18,000, 30 users), using `google/gemini-3.7-flash` through CloseRouter.

**Live analysis enabled.** The sidebar confirms the model and endpoint in use:

![Sidebar showing live analysis enabled](docs/images/01_sidebar_live_status.png)

**Request intake, staged architecture.** The request is validated and shown before analysis:

![Request intake before analysis, staged architecture](docs/images/02_request_intake_staged.png)

**Recommendation, staged architecture (Architecture B).** The recommendation routes the request for human review and four approvals. The "Why?" panel cites evidence IDs for each claim:

![Staged recommendation with rationale and policy constraints](docs/images/03_recommendation_staged.png)

**Vendor security and policy checks.** The internal registry and the live vendor-risk service are shown side by side, and each policy rule is marked as passed or required:

![Vendor security panel and policy checks](docs/images/04_vendor_security_policy_checks.png)

**Evidence.** Every item has a stable ID and a reference to its source:

![Evidence panel with source references](docs/images/05_evidence_policy_checks.png)

**Human review and handoff.** The reason for review, the required reviewers, and a copy-ready handoff summary. The AI action line states that no approval was executed:

![Human review required with handoff summary](docs/images/06_human_review_handoff.png)

**Run details and audit trail, staged.** Five model calls (four analyst, one reviewer), nine tool calls, and 32.5 s latency:

![Staged run audit trail with tool calls and decision trace](docs/images/07_audit_trail_staged.png)

**Recommendation, single agent (Architecture A, the default).** The same request, analysed by one agent, reaches the same policy outcome: human review and multi-stakeholder approvals. The approvers themselves come from the deterministic policy engine:

![Single-agent recommendation](docs/images/08_recommendation_single.png)

**Run details and audit trail, single agent.** Three model calls, eight tool calls, and 35.7 s latency:

![Single-agent run audit trail](docs/images/09_audit_trail_single.png)

**Evidence panel with repeated lookups.** In this run the model re-requested some lookups, so E7 to E9 repeat E1 to E3. The policy result is unchanged. This is a known presentation issue, listed under Known Limitations:

![Evidence panel showing repeated items from supplemental lookups](docs/images/10_evidence_panel_repeated_lookups.png)

**Request intake, single agent.** The default architecture, before analysis:

![Request intake before analysis, single agent](docs/images/11_request_intake_single.png)

**Degraded state (earlier build).** `REQ-1005` captured while the Gemini quota was exhausted. The product shows the documented safe state: `human_review_required`, deterministic policy fields, and every approval and risk flag still populated, not a crash or a fabricated recommendation:

![Degraded state with human review required](docs/images/screenshot_reliability_req1005.jpg)

## Quick Start

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

python -m pip install -r requirements.txt
python verify_setup.py       # no-LLM sanity check
```

Live analysis is optional. The application reads configuration from the **process environment only**; it never reads a `.env` file, so starting the app cannot silently enable live calls. To enable live analysis, set the variable in the shell you start the app from:

```bash
# Windows (PowerShell)
$env:GEMINI_API_KEY = "your-key-here"
# macOS / Linux
export GEMINI_API_KEY="your-key-here"

# optional
export GEMINI_MODEL=gemini-2.5-flash   # direct Gemini; the live CloseRouter run uses CLOSEROUTER_MODEL
```

For the live evaluation, the product also supports Gemini models through [CloseRouter](https://closerouter.dev), an OpenAI-compatible endpoint. Set `CLOSEROUTER_API_KEY` in the environment, and optionally `CLOSEROUTER_MODEL` (default `google/gemini-3.7-flash`). The live evaluator is run with `python evaluation/correctness/evaluator.py --real --provider closerouter`.

`.env.example` documents the variables. Copying it does nothing unless you set the same variables in the environment.

Then:

```bash
python run_local.py
```

The sidebar shows whether live analysis is enabled: `Live analysis: Enabled`, or `Live analysis: Disabled — GEMINI_API_KEY not configured`. Each analysis attempt, including failures, appends one line to `runs/audit.jsonl` (git-ignored; see below).

This starts the mock vendor-risk API on `http://127.0.0.1:8001` and the Streamlit UI on `http://127.0.0.1:8501`. Prerequisites: **Python 3.11+**. No key is needed to explore the UI or run the test suite. Without a key the product degrades to an explicit "automated analysis unavailable, manual review required" state rather than crashing or fabricating a result. Never commit a key.

## Read me first

- **Policy version and reference date.** Policy version 2026.09. Every policy result is computed against the fixed snapshot date 2026-09-30 (`data/procurement_policy.md`), never the system clock, so results do not change with the day you run them.
- **Two architectures, one boundary.** A (single agent) is the recommended default. B (analyst then reviewer) is retained as an evaluated alternative. Both use the same evidence preflight, policy engine, and validator. See `docs/architecture_decision.md`.
- **Vendor mock.** It has no authentication and must stay on `127.0.0.1`. The evaluation serves the same records in-process, so it does not depend on the mock running.
- **Stopping the app (Windows).** Ctrl+C in the `run_local.py` terminal stops both the mock and the UI.
- **Recommendation quality is not measured by the offline evaluation.** The live sample describes real-model behaviour on sixteen cases in one run only. See the evaluation section.

## Gemini keys and quota

The free tier limits requests per key per day. Several keys can be pooled: set `GEMINI_API_KEY_POOL` in your environment to a comma-separated list, and the app and the live evaluator rotate to the next key when one is exhausted or overloaded. Keys are never logged; only their index appears. Do not commit keys, and rotate any key that has been shared outside your own environment.

**Audit record.** Each analysis attempt appends one JSON line to `runs/audit.jsonl` (git-ignored; override with `PROCUREAI_AUDIT_LOG`): request identifier, a hash of the submitted request, evidence identifiers, the policy fields, architecture, model, git revision, and run status. It holds no request prose, no model prose, and no key.

## Checks before sharing or submitting

```bash
python scripts/preflight_secrets.py     # fails if a key-shaped string is in any non-ignored file
python -m pytest tests/ -q              # full suite, no key needed
python evaluation/run_comparison.py     # historical replay; no quota spent
python evaluation/correctness/evaluator.py   # independent correctness, offline; no key needed
```

## What AI Does

Interprets the request and the retrieved evidence, may request supplemental lookups for this request's own employee, product, and vendor, and writes a recommendation, rationale, and next step. It may also self-report prompt injection. It never sets required approvals, risk flags, missing-information items, or whether human review is required. Those fields are not on the model's output schema, and any lookup it requests is identity-bound and cannot change the evidence the policy uses.

## What Code Does

- **Evidence preflight** (`src/evidence.py`): gathers budget, catalog, purchase history, and vendor evidence from the validated request before the model is called. A failed lookup is recorded as unavailable, never as favourable.
- **Policy engine** (`src/policy_engine.py`): deterministically enforces every numbered rule in `data/procurement_policy.md` (POL-1 through POL-11). It takes no model input and makes no network calls.
- **Final validator** (`src/agent/validation.py`): keeps only evidence citations that were actually retrieved, and appends notes where model prose reads as an approval that has not been granted.
- **Injection visibility** (`src/injection_visibility.py`): a deterministic signal for instruction-shaped text. It adds `prompt_injection_detected` and nothing else.

## What Humans Do

Final approval, exceptions, and every Security, Privacy, Legal, Finance, and CFO sign-off. The product is recommendation-only: no code path purchases, approves, changes a department budget, or accepts vendor legal terms. `human_review_required` is always true.

## Tools

| Tool | Source | Retrieves |
|---|---|---|
| `get_employee_budget` | `src/tools/employee_budget.py` | Employee identity and the department's available software budget |
| `search_catalog` | `src/tools/catalog.py` | Catalog entries that might overlap the request |
| `search_purchase_history` | `src/tools/purchase_history.py` | Prior purchase records |
| `get_vendor_evidence` | `src/tools/vendor_risk.py` | Internal vendor registry and live vendor-risk service, independently, so disagreement is surfaced rather than resolved silently |
| `evaluate_policy` | `src/policy_engine.py` | The deterministic policy engine; never exposed to the model |

## Evidence Provenance

Every retrieved fact is an `EvidenceItem(source, finding, reference)`, for example `source="vendor_risk_service"`, `finding="security_review_status=expired"`, `reference="GET /vendor-risk/SignalWatch"`. Evidence has stable IDs (`E1`, `E2`, …). A citation of a nonexistent ID is dropped before it reaches the decision.

## Reliability

- **Missing information** is reported explicitly (for example "annual cost", "department") and never fabricated.
- **Vendor conflict.** When the registry and the live service disagree, both are shown and `conflicting_vendor_evidence` is raised. Neither is preferred silently.
- **Vendor service unavailable.** Never inferred as approved. Flagged `vendor_risk_unavailable` and routed to human review.
- **Model failure.** Transport failures, malformed output, and outages leave the policy fields unchanged. The recommendation states the failure, and the decision still requires human review.
- **Prompt injection.** Business text is data, never instructions. No policy rule reads free text, so injected text cannot change a threshold, approval, or risk flag.
- **Human authority.** `human_review_required` is always true, and the model cannot set or downgrade approvals.

## Architecture

```
Request → Validation → Evidence preflight (code) → Policy engine (code) → Agent (A or B) → Validator → ProcurementDecision → Human
```

- **Architecture A — single agent (recommended default).** One model loop, then one structured synthesis. Implemented in `src/agent/single_agent.py`.
- **Architecture B — analyst then reviewer.** An analyst writes a structured report; a reviewer with no tools writes the recommendation. Implemented in `src/agent/staged_agent.py`. Selectable with `handle_request(request_id, architecture="staged")` and in the UI.

Both share the preflight, the policy engine, the validator, and human handoff. The full diagram is in `docs/architecture.md`.

## Evaluation

The evaluation has four layers, kept separate so that no layer is read as evidence for another. Details are in `docs/final_evaluation.md`.

1. **Historical frozen replay — regression only.** The frozen 25-case set (`evaluation/cases.json`), run through both architectures with a deterministic stand-in model. Used to detect unexpected behaviour changes. Its expectations are historical, not a correctness oracle.
2. **Independent correctness — offline.** Hand-authored ground truth for 26 cases (`evaluation/correctness/ground_truth.json`), scored on 13 dimensions across normal, hostile, malformed, and outage modes for both architectures. Self-checked against deliberately broken behaviour.
3. **Real-model sample.** Sixteen pre-registered cases, both architectures, interleaved per case, on Gemini 3.7 Flash through CloseRouter. The rule was committed before the run.
4. **Unit and integration tests.** The full suite under `tests/`.

## Results

| Evidence | Result |
|---|---|
| Automated test suite | 764 passed, 1 skipped, 8 expected failures (adapter branch) |
| Frozen replay, post-hardening (25 cases) | 25/25 expected checks for both architectures; zero deterministic differences between A and B |
| Offline correctness (26 cases × 4 modes × 2 architectures) | No failing dimensions; deterministic outputs identical to the normal run in 104 of 104 runs per architecture; 12/12 public checks |
| **Final live run, pre-registered (16 cases, Gemini 3.7 Flash via CloseRouter), `correctness_real_20261003T142144Z.json`** | 16 comparable cases, no provider failures. A and B both 16/16 on recommendation and next action; both 16/16 on evidence grounding; no regression in B. Median latency A 18.2 s, B 24.4 s; median logical calls A 3, B 4 |

**Rule outcome.** The decision rule was committed before the final run and is in [`docs/preregistration_b_rule.md`](docs/preregistration_b_rule.md). B showed no improvement over A and no regression. The rule therefore selects Architecture A.

**Limits.** The live result is one run of 16 cases. It is descriptive and makes no significance claim. The live model issued supplemental tool lookups in both architectures, which the offline contract did not predict.

Earlier live runs are indexed in `evaluation/correctness/results/INDEX.md`. The Gemini sample `correctness_real_20261003T122905Z.json` is an earlier eight-case run on direct Gemini. Failed attempts are archived and are not results.

## Architecture comparison

Both architectures use the same evidence preflight, policy engine, validator, and human handoff, on the same test sets. They differ only in orchestration.

| | Architecture A (single agent) | Architecture B (analyst, then reviewer) |
|---|---|---|
| Offline correctness, 26 cases × 4 modes | No failing dimensions; identical deterministic outputs in 104 of 104 runs | Same |
| Frozen replay, 25 cases | 25/25 expected checks; zero deterministic differences from B | Same |
| Live run, 16 pre-registered cases | 16/16 recommendation and next action; 16/16 evidence grounding | 16/16 recommendation and next action; 16/16 evidence grounding; no regression |
| Median latency (live) | 18.2 s | 24.4 s |
| Median logical LLM calls (live) | 3 | 4 |
| Median tool calls (live) | 8 | 8 |

**Reading.** B showed no measured quality benefit over A on these cases, and it costs more time and one more model call per case. The pre-registered rule (`docs/preregistration_b_rule.md`) therefore selects A. This is one run of 16 cases, so it is descriptive and makes no significance claim.

## Edge Case Coverage

The brief's six required edge cases, with the cases that exercise them:

| Brief's edge case | Covered by | What happens |
|---|---|---|
| Incomplete or ambiguous request | Frozen `TC-12` (REQ-1006); ground truth `S-1006` | Missing fields are reported explicitly; the recommendation asks the requester to clarify |
| Existing tool already solves the need | Frozen `TC-03` (REQ-1008); ground truth `S-1001`, `S-1008` | `existing_tool_overlap` is raised; the request still goes through normal policy |
| Conflicting or expired vendor information | Frozen `TC-10` (REQ-1007); ground truth `S-1007`; policy test for the expired-plus-conflict interpretation | `conflicting_vendor_evidence` is raised; both sources are shown; the case goes to manual verification |
| Security-sensitive request or approval threshold | Frozen `TC-05`, `TC-06`, `TC-09`, `TC-16a`–`f`; ground truth `S-1003`, `S-1004`, `S-B01`–`S-B06` | Specialist and cost-tier approvals are added deterministically |
| Prompt injection in business data | Frozen `TC-12`, `TC-18a`/`b`; ground truth `S-INJ-REQ`, `S-INJ-TOOL` | Treated as data; the policy fields are unchanged; `prompt_injection_detected` is raised by a deterministic signal |
| Tool or API unavailable | Frozen `TC-11`; ground truth `S-1009`, `S-UNK` | Never inferred as favourable; flagged and routed to human review |

## Architecture Decision

**Ship Architecture A as the default.** Both architectures share the authoritative boundary, so the question is whether B's extra orchestration earns its cost. The pre-registered rule says it did not: in the final live run both matched the ground truth on every case, and B was slower and made one more call per case. The full reasoning and the conditions for revisiting B are in [`docs/architecture_decision.md`](docs/architecture_decision.md).

## Assumptions

- **Reference date is fixed at 2026-09-30**, the snapshot in `data/procurement_policy.md`, so the 365-day vendor assessment window is reproducible.
- **Starter-suggested approval names and risk-flag names are treated as authoritative**, for a consistent output contract.
- **Hidden grading cases may exist beyond the six public ones.** Nothing in the agent, tools, or policy branches on a request ID; all logic is data-driven.
- **Two architectures is the ceiling**, per the brief.
- **The starter data is authoritative** except where it is internally inconsistent. A blank CSV cell is treated as missing, not as a bug.
- **Currency is USD; all cost fields are annual.**
- **A missing key is a valid product state.** The product degrades to a manual-review response rather than crashing.
- **No automatic retry on a transient model failure.** A deliberate simplicity choice: the system falls back to the same safe human-review state.
- **Policy interpretation for expired-plus-conflicting vendor evidence.** Policy 5 makes security review mandatory for an expired assessment and requires surfacing a registry or service conflict. The label `vendor_review_expired` is a suggested flag, so it is not required. This was adjudicated after it appeared in the correctness evaluation, and is recorded in the ground truth and in an executable test.

## Known Limitations

- **Live evidence is small.** The final live run is one run of 16 cases, descriptive only. The live model made supplemental tool lookups in both architectures.
- **Repeated evidence rows in the UI.** When the model re-requests a lookup, the evidence panel can show the same item twice (see the screenshot "Evidence panel with repeated lookups"). The policy fields and approvals are computed once and are unaffected, but the panel is not yet deduplicated.
- **Prompt-injection visibility is pattern-based.** It is a visibility signal, not a complete defense. Paraphrased attacks may evade it.
- **Recommendation text is not scored offline.** Offline dimensions classify structured fields; free text is checked only for unqualified approval claims.
- **Dimensions 1 and 2 overlap dimension 7.** They classify the same structured fields.
- **Ground-truth independence is partial.** Some expectations were written after outputs were visible, and one was revised after an observed disagreement (documented in its revision log).
- **Catalog matching is exact after normalisation,** not semantic; a differently worded product name could be missed as an overlap.
- **Model calls can exceed the offline contract.** The live model issued supplemental lookups, mostly in B; this is recorded as a finding.
- **An intermittent test failure is unresolved.** One full run failed `test_failure_contract::test_missing_api_key_recommendation_is_clean`. An environment dependence was fixed; the root cause was not established, and roughly eleven later full-suite runs passed.
- **Free-tier quota** limits how much real-model evaluation a single key pool can run in one sitting.

## Reproducibility

```bash
python -m pytest tests/ -q                                  # full suite, no key needed
python verify_setup.py                                      # no-LLM preflight check
python evaluation/run_comparison.py                         # historical replay, no quota
python evaluation/correctness/evaluator.py                  # offline correctness, no key
GEMINI_API_KEY_POOL=... python evaluation/correctness/evaluator.py --real   # live sample, spends quota
```

Each correctness result records the git revision, whether the worktree was clean, and the ground-truth digest, so a result can be traced to the exact code and expectations that produced it.

## Scoring Alignment

| Rubric area | Weight | Evidence |
|---|---:|---|
| Product & workflow | 15% | `docs/workflow.md`, Screenshots, Product section above |
| End-to-end product | 20% | `run_local.py` (one-command start), Streamlit UI (`app.py`), `python -m pytest tests/ -q` |
| Agent & tool design | 20% | `docs/architecture.md`, `src/evidence.py`, `src/agent/`, `src/tools/` |
| Reliability & human controls | 15% | Reliability section, Edge Case Coverage, `src/agent/validation.py`, `human_review_required` always true |
| Evaluation & comparison | 20% | `docs/final_evaluation.md`, `docs/architecture_decision.md`, `evaluation/` (replay, correctness, live sample) |
| Engineering & communication | 10% | This README, `docs/`, the automated test suite, the CI workflow |

## Project Structure

```
app.py                  Streamlit product UI
src/
  contracts.py          ProcurementDecision / EvidenceItem / RunTelemetry (output contract)
  evidence.py           Deterministic evidence preflight
  policy_engine.py      Deterministic policy engine (POL-1..11)
  injection_visibility.py   Deterministic injection visibility signal
  data_access.py, vendor_client.py   Low-level data and HTTP helpers
  solution.py           handle_request(request_id, architecture) adapter
  tools/                The retrieval tools
  agent/                Architecture A (single_agent.py), B (staged_agent.py), shared prompts, schemas, validation, telemetry
  ui/                   Presentation layer
data/                   Synthetic employees, budgets, catalog, vendors, history, requests, and the policy source of truth
mock_api/               Mock vendor-risk service
evals/                  The six public evaluation cases
evaluation/             Historical frozen replay (cases.json, run_comparison.py) and the correctness layer (correctness/)
tests/                  Automated test suite
docs/                   Architecture, decision memo, final evaluation, workflow, and historical comparison documents
```
