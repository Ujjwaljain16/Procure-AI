# Starter Pack Audit Report

**Scope:** `FDE Assessment 3 Starter Pack` as extracted into `FDE\Ass 3` on 2026-09-30. All findings below are OBSERVED FACT unless explicitly marked INFERENCE or PROPOSED. Reference/evaluation date for all date logic in this repo is fixed at **2026-09-30**.

---

## 1. Executive Summary

The starter pack is a genuinely minimal scaffold, not a partially-built product. It ships fully-working infrastructure — synthetic data, a mock vendor-risk microservice, a Pydantic output contract, a Streamlit UI shell, a public evaluation harness, and integrity tests — but contains **zero** agent, tool-orchestration, or policy-engine code. The single function the entire assessment hangs off, `src/solution.py::handle_request(request_id, architecture)`, is a one-line `raise NotImplementedError`. Everything described in the assignment brief (3+ tools, 1 deterministic tool, Architecture A/B, structured output, human handoff) has to be built from scratch on top of this scaffold.

What currently works, verified by actually running it: environment setup (`pip install -r requirements.txt`), the no-LLM-required preflight script (`verify_setup.py` → PRE-FLIGHT PASSED), the full starter test suite (10/10 passing via `pytest`, once `pytest` itself is installed — see BUG-001), the mock vendor-risk API standalone and through `run_local.py`, and the Streamlit UI (loads, shows the request selector/JSON panel/architecture radio, correctly reports "not implemented" when Run analysis is clicked).

The data is small (10 employees, 6 departments, 10 catalog items, 13 vendors, 8 purchase-history rows, 10 sample requests, 13 vendor-risk records) but deliberately booby-trapped for the required edge cases: a genuine registry-vs-API conflict on `SignalWatch`'s security status, a forced 503 on `NimbusAI`, a request (`REQ-1006`) with both missing required fields and an embedded prompt-injection attempt, and a non-enum `status` field in the software catalog (`"Approved - limited use"`) that will silently misclassify if compared with a naive `== "Approved"` check.

The main operational risk found is not in the business logic (there isn't any yet) but in the documented "one-command start path": on a machine with no prior Streamlit installation, `python run_local.py` fails on first run because Streamlit's interactive onboarding email prompt kills the subprocess (exit code 3) when stdin isn't a TTY. This directly threatens a graded submission requirement (reproducible one-command start on a grader's clean machine) and has a known one-line fix (see BUG-002).

Everything needed to start implementation is present and understood: the exact output schema, the exact policy thresholds/rules, the exact mock-API behavior, and a verified-passing baseline. There is no ambiguity blocking implementation start. Verdict is at the end of this report.

---

## 2. Repository Map

```
Ass 3/
├── .env.example              purpose: env var template (mock API URL + provider key placeholders)   status: present, unfilled   importance: required before any LLM call
├── .gitignore                 excludes .venv, __pycache__, .env, pytest cache, evals/results_*.csv   status: OK   importance: prevents committing secrets/build artifacts
├── README.md                  full setup/run/rules doc                                               status: accurate, verified   importance: primary reference
├── STUDENT_CHECKLIST.md        pre-submission checklist                                               status: reference only
├── app.py                     Streamlit starter UI, calls src.solution.handle_request                status: runs, UI confirmed live   importance: replace/extend for Product UI requirement
├── run_local.py                starts mock API (uvicorn) + Streamlit together, one-command entrypoint status: runs (see BUG-002)   importance: submission's "one-command start"
├── verify_setup.py             no-LLM preflight check                                                 status: PASSES   importance: fastest sanity check
├── requirements.txt            fastapi, uvicorn, pydantic, pandas, requests, python-dotenv, streamlit, httpx — NO LLM SDK, NO pytest   status: installs cleanly   importance: must add Gemini SDK + pytest before implementation
├── data/                       all business data + policy source of truth                             status: internally consistent (tests pass)   importance: CRITICAL — ground truth for every decision
│   ├── employees.csv, department_budgets.csv, software_catalog.csv, vendors.csv, purchase_history.csv, requests.json, vendor_risk.json, procurement_policy.md, README.md
├── mock_api/                   FastAPI app simulating an external vendor-risk service                 status: runs, verified live   importance: the one true "external tool" call
│   ├── __init__.py, app.py
├── src/                        contracts + low-level helpers ONLY — no agent code                     status: no business logic yet   importance: this is what implementation builds on
│   ├── contracts.py            ProcurementDecision / EvidenceItem / RunTelemetry / Architecture       status: final, do not change shape
│   ├── data_access.py          pandas loaders for every CSV/JSON/policy file                          status: reusable as-is
│   ├── vendor_client.py        thin requests-based client for the mock API                            status: reusable, but raises on non-2xx — caller must catch
│   ├── telemetry.py            optional RunTelemetryCounter dataclass                                 status: optional helper
│   ├── solution.py             THE required adapter — currently `raise NotImplementedError`          status: **must be implemented**
│   └── sample_output.json      example ProcurementDecision payload for reference                      status: reference only
├── evals/                      6 public eval cases + runner                                            status: runs, correctly halts on NotImplementedError   importance: dev-time smoke test, not the full grader
│   ├── public_cases.json, run_public_evals.py, README.md
├── templates/                  decision-memo, workflow-notes, results-CSV templates                    status: empty scaffolds to fill in
├── docs/                       assignment brief PDF (+ this report)                                    status: reference
├── tests/                      starter-pack integrity tests, unittest-based                            status: 10/10 PASS   importance: guards the data/contract assumptions
└── plan.md                     our own pre-recon planning doc (not part of starter pack)
```

---

## 3. Technology Stack

| Area | Technology | Evidence | Status |
|---|---|---|---|
| Mock external service | FastAPI + Uvicorn | `mock_api/app.py`; `requirements.txt` | Confirmed running |
| Output/data contracts | Pydantic v2 | `src/contracts.py` (`pydantic>=2.9,<3`) | Confirmed valid |
| Data access | pandas (CSV), stdlib `json` (JSON/requests.json) | `src/data_access.py` | Confirmed working |
| HTTP client (vendor tool) | `requests` | `src/vendor_client.py` | Confirmed working |
| Env loading | `python-dotenv` | `run_local.py` line 10-13 | Confirmed working |
| Starter UI | Streamlit | `app.py`, `run_local.py` | Confirmed running (see §4/§6) |
| Testing (starter) | `unittest` (run directly or via pytest) | `tests/*.py` | Confirmed 10/10 pass |
| Testing (assessment's own harness) | plain argparse + CSV export | `evals/run_public_evals.py` | Confirmed runs |
| LLM / agent framework | **None provided** | `requirements.txt` comment: "Add the SDK for the model/provider you choose" | To be added (Gemini — user decision) |
| Database | None — flat CSV/JSON files | `data/` directory | N/A by design |
| Containerization | None | no Dockerfile/compose file found | N/A |
| Package management | pip + `requirements.txt`, plain `venv` | README Quick Start | Confirmed working |
| CI | None found | no `.github/workflows`, no CI config | NOT VERIFIED further (out of scope) |

---

## 4. How to Run

**Confirmed working, in order, exactly as executed:**

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # clean install, no errors
./.venv/Scripts/python.exe verify_setup.py                       # -> PRE-FLIGHT PASSED
./.venv/Scripts/python.exe -m pip install pytest                 # not in requirements.txt — see BUG-001
./.venv/Scripts/python.exe -m pytest tests/ -v                   # -> 10 passed
./.venv/Scripts/python.exe -m uvicorn mock_api.app:app --host 127.0.0.1 --port 8001   # -> live, verified via curl
./.venv/Scripts/python.exe run_local.py                          # -> both services live (see BUG-002 for first-run caveat)
./.venv/Scripts/python.exe evals/run_public_evals.py --architecture single   # -> correctly STOPs on NotImplementedError
```

**Expected but unverified (blocked on missing LLM credentials, by design — this is implementation work, not audit work):**
- Any actual `handle_request(...)` call producing a real `ProcurementDecision` from an LLM.
- `.env` with a real Gemini key (`.env.example` only has placeholders; no `.env` exists in the repo, correctly gitignored).

**Broken on first run of a clean machine (root-caused, see BUG-002):**
- `python run_local.py` when Streamlit has never been run on that machine before and no `~/.streamlit/credentials.toml` exists — the Streamlit subprocess exits with code 3 before serving anything, and `run_local.py` surfaces only a generic "A local process exited with code 3", not the real cause.

---

## 5. Current Runtime Status

| Component | Status | Evidence | Problem |
|---|---|---|---|
| Python venv + deps | OK | Clean `pip install`, no conflicts | None |
| `verify_setup.py` | OK | `PRE-FLIGHT PASSED`, all 5 checks green | None |
| `pytest tests/` | OK (after manual install) | `10 passed, 1 warning in 0.41s` | `pytest` missing from `requirements.txt` (BUG-001) |
| Mock vendor-risk API (standalone) | OK | `/health`→200, `/vendor-risk/SignalWatch`→200 (expired), `/vendor-risk/NimbusAI`→503, `/vendor-risk/UnknownVendorXYZ`→404 | None |
| `run_local.py` (fresh machine, no streamlit config) | FAILS on first run | Streamlit subprocess exit code 3 immediately after "Starting starter UI..." | BUG-002 |
| `run_local.py` (after seeding empty streamlit credentials) | OK | Mock API `/health`→200; Streamlit `/`→200; UI screenshot + `get_page_text` confirm live request selector, JSON panel, "Run analysis" button wired to `handle_request` | Root cause is a Streamlit first-run UX quirk, not `run_local.py` logic itself |
| `evals/run_public_evals.py --architecture single` | OK (correct pre-implementation behavior) | Prints `STOP Implement handle_request(...)` and exits cleanly, no crash, no false pass | None — this is the desired behavior before implementation begins |
| `src/solution.py` | NOT IMPLEMENTED (expected) | `raise NotImplementedError(...)` | This is the entire remaining deliverable |

---

## 6. Test Baseline

Command: `./.venv/Scripts/python.exe -m pytest tests/ -v`

- **Passed:** 10
- **Failed:** 0
- **Skipped:** 0
- **Errors:** 0
- **Runtime:** 0.41s
- **Warnings:** 1 — `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` (harmless, upstream FastAPI/Starlette deprecation notice, not caused by this project's code)

Breakdown:
- `tests/test_data_integrity.py` (7 tests) — budget arithmetic, primary-key uniqueness across 4 CSVs, request-ID uniqueness, employee→manager FK integrity, request→employee/department/vendor/vendor-risk FK integrity, vendor review dates not in the future relative to the 2026-09-30 reference date, public-eval-case→request FK integrity. All passed — **the dataset is internally consistent**, there are no orphaned foreign keys or arithmetic errors in the provided data.
- `tests/test_mock_api.py` (3 tests) — health check, a known-vendor payload shape check, the forced-outage 503 check. All passed.

There were no failures to root-cause. The starter pack's own tests are a reliable, currently-green baseline.

---

## 7. Data Inventory

| Dataset | Format | Records | Fields | Key IDs | Relationships | Relevant Procurement Fields |
|---|---|---|---|---|---|---|
| `employees.csv` | CSV | 10 | employee_id, name, department, manager_id, level, country | `employee_id` (E001-E010) | `department` → `department_budgets.csv`; `manager_id` → self (employee_id); E010 has no manager (VP, root) | department (budget lookup), manager_id (approval chain) |
| `department_budgets.csv` | CSV | 6 | department, annual_software_budget_usd, committed_usd, available_usd | `department` (name, not coded) | referenced by employees.csv `department` | available_usd = annual - committed (static snapshot) |
| `software_catalog.csv` | CSV | 10 | software_id, product_name, category, vendor_name, status, annual_cost_usd, licensed_seats, scope, notes | `software_id` (SW001-SW010) | `vendor_name` → vendors.csv | status (free text, not enum — see §8), category (overlap detection), licensed_seats/scope (existing-capacity check) |
| `vendors.csv` | CSV | 13 | vendor_id, vendor_name, procurement_status, security_status, security_review_date, legal_terms_status, notes | `vendor_id` (V001-V013) | `vendor_name` → software_catalog.csv, requests.json, vendor_risk.json | security_status + security_review_date (compare against mock API — deliberately can disagree, see §8) |
| `purchase_history.csv` | CSV | 8 | purchase_id, purchase_date, department, vendor_name, product_name, annual_amount_usd, status, notes | `purchase_id` (PO-2401 etc.) | `department` → department_budgets.csv; `vendor_name`/`product_name` → catalog | all 8 rows have status="Approved" — no rejected/cancelled examples exist (INFERENCE: duplicate-rejected-request edge case is not pre-modeled in history data) |
| `requests.json` | JSON array | 10 | request_id, requester_id, product_name, vendor_name, category, annual_cost_usd (nullable), user_count (nullable), business_justification (free text, untrusted), data_access_level, requested_integrations (list), urgency | `request_id` (REQ-1001…1010) | `requester_id` → employees.csv; `vendor_name` → vendors.csv + vendor_risk.json | annual_cost_usd/user_count nullable (REQ-1006 only); business_justification is the prompt-injection attack surface |
| `vendor_risk.json` | JSON object, keyed by vendor_name | 13 | risk_level, security_review_status, last_review_date, processes_personal_data, stores_data_outside_region, notes — **except** `NimbusAI`, which only has `force_error`+`error_message` | vendor_name (matches vendors.csv exactly) | keyed to vendors.csv/requests.json vendor_name | security_review_status + last_review_date (365-day validity rule), force_error (outage simulation) |
| `procurement_policy.md` | Markdown | 11 numbered sections | n/a (prose policy) | referenced by all decision logic | full rule inventory in §9 below |

**Relationship diagram:**

```
employees.csv ──department──> department_budgets.csv
     │  ▲
     │  └── manager_id (self-referential)
     │
requester_id
     │
     ▼
requests.json ──vendor_name──> vendors.csv ──vendor_name──> vendor_risk.json (mock API)
     │                              │
     │                        vendor_name
     │                              ▼
     └──product_name/category──> software_catalog.csv ──vendor_name──> vendors.csv

purchase_history.csv ──department──> department_budgets.csv
purchase_history.csv ──vendor_name/product_name──> software_catalog.csv (loosely, by name)

evals/public_cases.json ──request_id──> requests.json
```

---

## 8. Data Quality Findings

Only issues actually observed:

- **Non-enum `status` field in `software_catalog.csv`.** 9 of 10 rows are exactly `"Approved"`; `SW009` (NeuralDesk Business) is `"Approved - limited use"`. A naive `status == "Approved"` check would treat NeuralDesk as unrestricted and miss the "sensitive data restrictions apply" caveat in its own `notes` field. This is a genuine implementation trap, not a data error.
- **Deliberate registry-vs-service conflict on SignalWatch.** `vendors.csv` row V005 says `security_status=Approved`, `security_review_date=2025-07-01`, with the note *"Registry has not yet been refreshed with latest review state"*. The mock API (`vendor_risk.json` → live-verified via curl) says `security_review_status=expired` for the same vendor and same date. Policy §5 explicitly requires surfacing this kind of disagreement rather than silently picking one side — this is clearly intentional test data, not an inconsistency to "fix".
- **Asymmetric schema on `vendor_risk.json`'s `NimbusAI` entry.** It has only `force_error`/`error_message`, none of the normal fields (`risk_level`, `security_review_status`, etc.). Code that reads `.get("security_review_status")` without first checking `.get("force_error")`, or that doesn't catch the exception `vendor_client.get_vendor_risk()` raises via `response.raise_for_status()` on the resulting 503, will crash. Intentional (tests the tool-unavailable edge case), but must be defensively handled.
- **`purchase_history.csv` has only "Approved" outcomes** — no rejected, cancelled, or pending purchase is modeled historically. Not a defect, just a boundary on what can be tested from purchase history alone (INFERENCE).
- **`department_budgets.csv`'s `available_usd` is a static snapshot**, not recomputed as hypothetical purchases are approved during an eval run. `data/README.md` explicitly says "in the provided snapshot", so treating it as static for the whole assessment is the documented intent, not an oversight — but it should be stated explicitly as an assumption in the submission's own assumptions doc.
- No duplicate primary keys, no orphaned foreign keys, no arithmetic inconsistencies — all confirmed by the passing `test_data_integrity.py` suite.

---

## 9. Policy Inventory

Source: `data/procurement_policy.md` (version 2026.09, reference date 2026-09-30). All rules below are transcribed, not paraphrased loosely.

| Rule ID | Actual Rule | Trigger | Threshold | Approval/Handoff | Source | Current Implementation |
|---|---|---|---|---|---|---|
| POL-1 | Request needs requester+dept, product/vendor, annual cost estimate, user count, business purpose, data-access level, required integrations | any field missing | — | request clarification, do not invent values | §1 | Not implemented |
| POL-2 | Annual cost vs. department's `available_usd` | cost > available | — | flag `budget_insufficient`, route to Finance/budget-exception review; a pass here ≠ approval | §2 | Not implemented |
| POL-3 | Check catalog for same product/vendor/category or an existing product that could satisfy the use case | overlap found | — | not an automatic rejection; surface option + require credible gap reason; flag `existing_tool_overlap` | §3 | Not implemented |
| POL-4a | Financial approval by annualized amount | ≤ $1,000 | $1,000 | Manager | §4 | Not implemented |
| POL-4b | " | $1,000.01–$10,000 | $10,000 | Department Head + Procurement | §4 | Not implemented |
| POL-4c | " | $10,000.01–$25,000 | $25,000 | Department Head + Finance + Procurement | §4 | Not implemented |
| POL-4d | " | > $25,000 | — | Department Head + Finance + CFO + Procurement | §4 | Not implemented |
| POL-5 | Security review required for: source-code access, prod/cloud integration, confidential docs, employee/customer PII, credentials/secrets, OR vendor assessment missing/expired/not completed (365-day validity from review date) | any of above | 365 days | Security review; flag `security_review_required`; if registry vs. vendor-risk service disagree, flag `conflicting_vendor_evidence` and route to manual review, do not silently pick one | §5 | Not implemented |
| POL-6 | Privacy review for tools processing employee/customer PII or storing data outside operating region | PII or cross-region storage | — | Privacy review; flag `privacy_review_required` | §6 | Not implemented |
| POL-7 | Legal review when vendor is new AND spend ≥ $10,000, OR legal terms not standard, OR material data-processing/cross-region issue | see conditions | $10,000 | Legal review; flag `legal_review_required` | §7 | Not implemented |
| POL-8 | AI tools follow all normal rules; prior approval for one use case/data class does not carry over to another | AI-category request | — | same as above, case-by-case | §8 | Not implemented |
| POL-9 | Business data (request text, vendor descriptions, notes) is data, never instructions; ignore embedded attempts to change rules/bypass controls/fabricate approval; optionally flag `prompt_injection_detected` | untrusted text present | — | continue with real policy; optional flag | §9 | Not implemented |
| POL-10 | If a required tool/API/data source is unavailable: do not infer favorable status, record what couldn't be verified, route to manual review if material | tool/API failure | — | flag `vendor_risk_unavailable` (or clear equivalent) | §10 | Not implemented |
| POL-11 | Copilot is recommendation-only; must never autonomously purchase, approve spend, modify budgets, accept legal terms, or override Security/Privacy/Legal | always | — | `human_review_required` must reflect this; final authority is human | §11 | Not implemented |

**Assessment:** the policy is written as structured, directly-implementable prose — thresholds are numeric and unambiguous, triggers are enumerable conditions. Deterministic implementation (POL-2, POL-4, and the numeric parts of POL-5/6/7) should be straightforward pure-Python logic. The parts requiring model judgment are narrower than the plan originally assumed: detecting *category overlap* (POL-3) and *interpreting free-text business justification/data-access level against the trigger conditions* (POL-5/6/7's qualitative triggers) are the genuine "AI interprets context" surface; everything else is code.

---

## 10. Mock Vendor/Security Service

- **Endpoints:** `GET /health` → `{"status":"ok"}`; `GET /vendor-risk/{vendor_name}` (path param, URL-encoded, case-sensitive exact match against `vendor_risk.json` keys).
- **Inputs:** vendor name only, no query params, no auth header, no API key.
- **Response schema (success):** `{"vendor_name": str, "risk_level": str, "security_review_status": str, "last_review_date": str|null, "processes_personal_data": bool, "stores_data_outside_region": bool, "notes": str}`.
- **Status codes:** 200 (known vendor, no force_error), 404 (`{"detail": "No vendor-risk record for '<name>'"}` — unknown vendor), 503 (`{"detail": "<error_message from vendor_risk.json>"}` — only `NimbusAI` currently has `force_error: true`).
- **Error behavior:** raised via FastAPI `HTTPException`; the provided `src/vendor_client.py` calls `response.raise_for_status()`, so both 404 and 503 surface as Python exceptions (`requests.HTTPError`) to the caller — **not** as a normal return value. Any tool wrapper built later must explicitly try/except around this call.
- **Freshness/expiry fields:** `last_review_date` + `security_review_status` (already pre-computed as `"approved"`/`"expired"`/`"not_completed"` in the mock data — the 365-day math is only needed for the *registry* CSV's `security_review_date`, since the mock service's status string is pre-resolved).
- **Latency simulation:** none observed — all responses returned in well under the 3-second client timeout, effectively instant.
- **Startup:** `uvicorn mock_api.app:app --host 127.0.0.1 --port 8001`, or via `run_local.py` which also waits on `/health` before proceeding (confirmed in `run_local.py` lines 20-36).
- **Current integration:** none yet — `src/vendor_client.py` exists but is not called from anywhere (no consumer code written).
- **Limitations:** data loaded once at process start from `vendor_risk.json` (module-level constant) — no hot reload; single vendor lookup per call (no batch endpoint).

---

## 11. Existing APIs / Services

| Item | Purpose | Input | Output | State | Reuse recommendation |
|---|---|---|---|---|---|
| `mock_api.app:app` (FastAPI) | Simulated external vendor-risk service | vendor name (path) | JSON risk record or HTTPException | Complete, tested | Reuse as-is, do not modify |
| `src.data_access.load_employees/load_budgets/load_software_catalog/load_vendors/load_purchase_history/load_requests/get_request/load_policy_text` | Typed loaders for every data file | none / request_id | DataFrame / list[dict] / str | Complete, reusable | Reuse as-is; consider light caching if called per-tool-invocation in a loop (not a correctness issue at this data size, only a style note) |
| `src.vendor_client.get_vendor_risk` | Low-level client to mock API | vendor_name, timeout | dict (raises on non-2xx) | Complete but unguarded | Wrap, don't modify — add try/except at the call site |
| `src.contracts.ProcurementDecision` / `EvidenceItem` / `RunTelemetry` | Required output schema | — | — | Final, authoritative | Must not change shape; this is what the grader validates against |
| `src.telemetry.RunTelemetryCounter` | Optional call-counting helper | — | — | Optional | Use it or replace; either is fine |
| `src.solution.handle_request` | **The** assessment adapter | request_id, architecture | `ProcurementDecision` | `raise NotImplementedError` | **This is the deliverable** |
| `evals.run_public_evals` | Dev-time smoke test harness | `--architecture single|staged` | console output + CSV | Complete, reusable | Reuse as-is; it is explicitly *not* the full grader |
| `app.py` (Streamlit) | Starter product UI | UI interaction | renders `handle_request` output | Functional shell, no styling beyond defaults | Extend or replace per product-UI requirement |

---

## 12. Existing Architecture

**Current (as shipped — no business logic yet):**

```
┌─────────────┐      ┌───────────────────┐
│ Streamlit UI │─────▶│ src.solution       │  (raises NotImplementedError)
│  (app.py)    │      │ .handle_request()  │
└─────────────┘      └───────────────────┘
       ▲                        │
       │                        ▼ (not yet wired)
┌─────────────┐      ┌───────────────────┐      ┌────────────────────┐
│ eval harness │      │ src.data_access    │      │ mock_api (FastAPI)  │
│ (run_public_ │      │ (CSV/JSON loaders) │      │ /vendor-risk/{name} │
│  evals.py)   │      └───────────────────┘      └────────────────────┘
└─────────────┘                                            ▲
                                                             │ (client exists,
                                                    src.vendor_client   unused)
```

**Future (PROPOSED — not yet built, see §19-20):** a tool layer (budget/catalog/history/vendor/policy) sitting behind `handle_request`, feeding a single-agent orchestrator for Architecture A and a two-stage analyst→reviewer pipeline for Architecture B, both terminating through one shared deterministic policy validator before returning `ProcurementDecision`. This is not implemented and must not be presented as if it exists.

---

## 13. Candidate Procurement Tools

| Tool | Inputs | Outputs | Data source | Deterministic? | Existing? | Needed work |
|---|---|---|---|---|---|---|
| Employee/budget lookup | employee_id | department, budget available | `data_access.load_employees`, `load_budgets` | Deterministic (lookup + subtraction, already true in data) | Loaders exist, no tool wrapper | Thin wrapper joining the two DataFrames by department |
| Software catalog / overlap search | product name/category | matching catalog rows | `data_access.load_software_catalog` | Deterministic lookup; overlap *judgment* is model-assisted | Loader exists, no wrapper/search logic | Wrapper + fuzzy/category match logic |
| Purchase history lookup | employee/department/vendor | prior purchases | `data_access.load_purchase_history` | Deterministic | Loader exists, no wrapper | Thin wrapper |
| Vendor registry + risk check | vendor_name | registry status (CSV) + live risk (mock API), including conflict detection | `data_access.load_vendors` + `vendor_client.get_vendor_risk` | Deterministic retrieval; conflict *handling* is a policy rule | Both pieces exist separately, not combined, no error handling wrapped | Wrapper that calls both, compares, and surfaces `conflicting_vendor_evidence`/`vendor_risk_unavailable`; must catch `requests.HTTPError` |
| Deterministic policy engine | full evidence bundle (cost, dept, catalog match, vendor status, data-access level) | required_approvals[], risk_flags[], missing_information[] | `data_access.load_policy_text` (source of truth) + hardcoded thresholds transcribed in §9 | **Fully deterministic — this is the required "at least 1 deterministic tool"** | Not implemented at all | New module (e.g. `src/policy_engine.py`) implementing POL-1..11 as pure functions, unit-testable without any LLM |

---

## 14. Reliability / Failure Analysis

| Scenario | Current Behavior | Risk | Desired Future Behavior |
|---|---|---|---|
| Incomplete request (REQ-1006: null cost/user_count) | Nothing consumes it yet — `handle_request` isn't implemented | N/A yet | Detect missing fields per POL-1, add to `missing_information`, do not fabricate values |
| Existing tool already covers need (e.g. REQ-1008 TaskFlow Pro vs. existing TaskFlow SW003) | Nothing consumes it yet | N/A yet | Catalog tool surfaces existing option; flag `existing_tool_overlap`; not an automatic rejection (POL-3) |
| Conflicting/expired vendor info (SignalWatch) | Nothing consumes it yet; confirmed both sources genuinely disagree | N/A yet | Compare registry vs. mock API; flag `conflicting_vendor_evidence`, route to manual review, never silently pick one (POL-5) |
| Security-sensitive request / approval threshold | Nothing consumes it yet; thresholds are unambiguous numbers in policy | N/A yet | Deterministic threshold table (POL-4) + trigger rules (POL-5/6/7) drive `required_approvals` |
| Prompt injection in business data (REQ-1006 justification text) | Nothing consumes it yet; confirmed the raw string is unprotected/unlabeled in `requests.json` | High if ignored during implementation — this is a graded edge case | Treat all free-text fields as data, never instructions (POL-9); optionally flag `prompt_injection_detected`; system prompt/tool boundary must clearly separate instructions from retrieved data |
| Tool/API unavailable (NimbusAI 503) | `vendor_client.get_vendor_risk` raises `requests.HTTPError` uncaught — would crash a naive caller | High if uncaught during implementation | Catch the exception at the tool boundary, record "could not verify", flag `vendor_risk_unavailable`, route to manual review (POL-10), never infer a favorable status |

---

## 15. Security Findings

- **Secrets:** none found. Repo-wide grep for API-key-shaped strings, `password=`, `secret=`, and common provider key prefixes across `.py`/`.json`/`.md`/`.csv`/`.env*` returned zero matches (excluding `.venv`). No `.env` file exists yet; `.gitignore` correctly excludes `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, and `evals/results_*.csv`.
- **Trust boundary:** the mock API has no authentication — acceptable, it's an explicitly local/mock service, not a real external dependency.
- **Injection exposure:** confirmed live attack surface in `requests.json` (`REQ-1006.business_justification`); currently unmitigated only because nothing reads it yet. Policy §9 explicitly mandates the mitigation, so this is an implementation requirement, not a currently-exploitable defect.
- **Unsafe defaults:** none observed in the scaffold itself. The one operational risk is BUG-002 (Streamlit onboarding prompt), which is a startup reliability issue, not a security issue.

---

## 16. Bugs Found in Starter Scaffold

### BUG-001
**Location:** `requirements.txt` (missing `pytest`), `tests/` directory (exists and is pytest-compatible).
**Observed behavior:** `python -m pytest tests/` fails with `No module named pytest` until manually installed; README's Quick Start never mentions running the test suite at all.
**Expected behavior:** either `pytest` is pinned so `tests/` is runnable from a clean `pip install -r requirements.txt`, or the README documents `python -m unittest discover tests` as the zero-extra-dependency alternative (it works, not separately verified in this report but is standard library behavior).
**Root cause:** dependency omission.
**Severity:** Low (doesn't block grading; `verify_setup.py` covers the no-LLM sanity check without pytest).
**Minimal fix:** add `pytest>=8,<9` to `requirements.txt` (or a `requirements-dev.txt`).
**Should fix now?** NO — cosmetic, will naturally get fixed when our own test suite is added.

### BUG-002
**Location:** `run_local.py` (spawns Streamlit via `subprocess.Popen`), interacting with Streamlit's own first-run onboarding flow.
**Observed behavior:** on a machine with no pre-existing `~/.streamlit/credentials.toml`, `python run_local.py` starts the mock API successfully, then the Streamlit subprocess prints its onboarding "Welcome to Streamlit! ... Email:" prompt and immediately exits with code 3 (stdin is not an interactive TTY under `subprocess.Popen`), which `run_local.py` reports only as the generic `RuntimeError: A local process exited with code 3` — no indication of the real cause. After pre-seeding an empty `~/.streamlit/credentials.toml`, the identical command starts both services cleanly and the UI is fully reachable.
**Expected behavior:** `python run_local.py` should succeed on a genuinely clean machine (this is the documented, graded "one-command start path").
**Root cause:** Streamlit's global (machine-level, not project-level) first-run telemetry/email opt-in prompt assumes an interactive terminal; it is unrelated to this project's code but breaks this project's one-command promise on a fresh environment (e.g., a grader's machine).
**Severity:** Medium — directly threatens a scored submission requirement (one-command local start) if the grader's machine has never run Streamlit before.
**Minimal fix:** ship a project-local `.streamlit/config.toml` with `[browser]\ngatherUsageStats = false`, which is the standard, well-documented way to suppress this prompt without touching any business logic.
**Should fix now?** YES recommended — it's exactly the kind of tiny, non-invasive setup fix needed to guarantee a runnable baseline.

**Status: FIXED AND VERIFIED.** `.streamlit/config.toml` (`server.headless = true`) was added and confirmed to resolve a genuinely clean-machine startup (no credentials file present anywhere on the test machine), with the mock API and Streamlit UI both reachable afterward and no change to existing UI behavior.

### BUG-003 (data-quality trap, not a defect)
**Location:** `data/software_catalog.csv`, `status` column.
**Observed behavior:** `status` is free text ("Approved" vs. "Approved - limited use" for SW009 NeuralDesk Business), not a clean enum.
**Expected behavior:** N/A — this is realistic, intentional test data, not a bug to fix.
**Root cause:** deliberate assessment design (forces careful parsing rather than a naive equality check).
**Severity:** Medium if missed during implementation (would cause a real policy miss on NeuralDesk-related requests).
**Minimal fix:** N/A — document the trap, handle it in policy-engine logic (substring/contains check or explicit status taxonomy), not in the data.
**Should fix now?** NO — this is data, not code; it's correct as shipped.

---

## 17. Assumptions Already Embedded in Scaffold

- Reference date for all date/staleness logic is 2026-09-30, not the system clock — **verified** (stated in `procurement_policy.md` §header, `data/README.md`, and enforced by `test_vendor_review_dates_not_in_future`).
- `vendor_name` is the universal join key across `requests.json`, `vendors.csv`, `software_catalog.csv`, `vendor_risk.json` — **verified** (enforced by `test_request_foreign_keys`).
- `department` (name string, not a code) is the join key between `employees.csv` and `department_budgets.csv` — **verified**.
- `requester_id` in `requests.json` maps 1:1 to `employee_id` in `employees.csv` — **verified**.
- All monetary fields are implicitly USD (every column is suffixed `_usd`) with no explicit currency field or multi-currency support — **likely** (INFERENCE from naming convention; never declared as an explicit rule anywhere).
- `available_usd` in `department_budgets.csv` is a static, already-computed snapshot, not meant to be live-decremented as requests are hypothetically approved within a single evaluation run — **likely** (INFERENCE from `data/README.md`'s "in the provided snapshot" phrasing; should be stated as an explicit assumption in the submission).
- The public eval harness matches approvals/risk-flags/missing-information via case-insensitive **substring** containment against expected token groups (`group_present` in `run_public_evals.py`), not exact string/enum equality — **verified** by reading the harness code. This means recommendation/approval wording should stay close to the policy's own vocabulary (Manager, Department Head, Procurement, Finance, CFO, Security, Privacy, Legal) but has some phrasing flexibility.

---

## 18. Important Unknowns

- **NOT VERIFIED:** whether the hidden grading harness uses the same substring-matching logic as `evals/run_public_evals.py`, or something stricter (exact enum matching, embedding-based grounding checks, etc.). The public README explicitly warns the public harness is not the full grading system.
- **NOT VERIFIED:** Gemini SDK specifics for structured/JSON-schema output and function-calling/tool-use — needs to be checked against current Gemini API docs before implementation before committing to an orchestration design.
- **NOT VERIFIED:** whether `python -m unittest discover tests` (stdlib, no pytest needed) behaves identically to the `pytest` run — logically it should (both files use `unittest.TestCase`), but this was not separately executed in this recon pass.
- **NOT VERIFIED:** exact behavior of `run_local.py` on macOS/Linux (all verification in this report was done on Windows/PowerShell + Git Bash, matching this user's actual environment); the Streamlit onboarding-prompt issue (BUG-002) is a Streamlit-level behavior and plausibly reproduces cross-platform, but this was not tested on another OS.
- **UNKNOWN:** whether the hidden evaluation cases include any edge case beyond the six categories explicitly named in the brief (incomplete request, existing tool, conflicting/expired vendor info, security threshold, prompt injection, tool unavailable) — the brief and starter pack only confirm these six.

---

## 19. Recommended Canonical Domain Model

Not implemented yet — this is the shape implementation should target, built directly from what's OBSERVED in `src/contracts.py` and the data files. Fields marked PROPOSED are not present anywhere yet and would be introduced during implementation.

- **ProcurementRequest** — request_id, requester_id, product_name, vendor_name, category, annual_cost_usd, user_count, business_justification, data_access_level, requested_integrations, urgency *(all fields OBSERVED, directly from `requests.json`)*.
- **Employee** — employee_id, name, department, manager_id, level, country *(OBSERVED, from `employees.csv`)*.
- **Budget** — department, annual_software_budget_usd, committed_usd, available_usd *(OBSERVED, from `department_budgets.csv`)*.
- **CatalogEntry** — software_id, product_name, category, vendor_name, status, annual_cost_usd, licensed_seats, scope, notes *(OBSERVED, from `software_catalog.csv`)*.
- **VendorRecord** — vendor_id, vendor_name, procurement_status, security_status, security_review_date, legal_terms_status, notes *(OBSERVED, registry side, from `vendors.csv`)*.
- **VendorRiskRecord** — vendor_name, risk_level, security_review_status, last_review_date, processes_personal_data, stores_data_outside_region, notes, *(nullable)* force_error, error_message *(OBSERVED, live-service side, from `vendor_risk.json`/mock API)*.
- **PurchaseRecord** — purchase_id, purchase_date, department, vendor_name, product_name, annual_amount_usd, status, notes *(OBSERVED, from `purchase_history.csv`)*.
- **Evidence** — source, finding, reference *(OBSERVED — this is literally `EvidenceItem` in `src/contracts.py`, already final)*.
- **PolicyCheck** — rule_id, status (pass/required/flagged), actual value, threshold, reason *(PROPOSED — not present anywhere; needed internally by the policy engine to make its reasoning inspectable, but does not have to appear in the final `ProcurementDecision` output unless folded into `evidence`)*.
- **ProcurementDecision** — request_id, recommendation, evidence[], required_approvals[], missing_information[], risk_flags[], next_step, human_review_required, telemetry *(OBSERVED, final and authoritative — `src/contracts.py`)*.
- **HumanHandoff** — *(PROPOSED — the brief requires "human handoff" but the contract doesn't define a separate object for it; simplest approach is that `human_review_required=True` + populated `required_approvals`/`risk_flags`/`next_step` already constitute the handoff, with the UI rendering that state distinctly. No new contract type is required unless the product UI wants a richer object.)*

---

## 20. Implementation Plan

1. **Wire the Gemini SDK.** Add `google-genai` (or `google-generativeai`, confirm current recommended package name against Gemini docs — NOT VERIFIED which is current) to `requirements.txt`; add `GEMINI_API_KEY`/`MODEL_NAME` to `.env.example`; create local `.env` (never committed). Risk: Gemini's structured-output/function-calling API shape is not yet verified against this project's needs.
2. **Build the deterministic policy engine first, with unit tests, no LLM involved.** New module `src/policy_engine.py` implementing POL-1 through POL-11 from §9 as pure functions over already-loaded data (using `src/data_access.py` as-is). New `tests/test_policy_engine.py` covering every threshold boundary (exactly $1,000, $10,000, $25,000), the SignalWatch conflict, the NimbusAI outage (mocked), and the NeuralDesk "limited use" status trap. This satisfies "at least 1 deterministic tool" independent of any LLM work and gives Architecture A/B a shared, trustworthy foundation.
3. **Build the remaining tool wrappers** (employee/budget, catalog/overlap, purchase history, vendor registry+risk-with-conflict-detection) as thin, testable functions around the existing loaders/client, each returning `EvidenceItem`-shaped data.
4. **Implement Architecture A in `src/solution.py`** (or a new `src/agents/single_agent.py` imported from there): request → tool calls (via Gemini function-calling) → evidence pack → policy_engine validation (always authoritative, can override the model) → `ProcurementDecision`, with `RunTelemetry` populated from real call counts. Keep `handle_request(request_id, architecture="single")` as the stable public entrypoint.
5. **Run `evals/run_public_evals.py --architecture single` continuously during development** against all 6 public cases, and manually exercise the 4 non-public requests (REQ-1004, 1007, 1008, 1010) plus the SignalWatch/NimbusAI/REQ-1006 traps explicitly.
6. **Decide and build the Product UI.** Given the starter Streamlit UI already works end-to-end (confirmed live in this report) and the deadline is 8 Oct 2026, extending `app.py` with an evidence panel + structured recommendation view is lower-risk than a full Next.js rewrite from the earlier plan — recommend deciding this explicitly with you before starting.
7. **Implement Architecture B** (`architecture="staged"`) reusing the exact same tools and policy engine — analyst stage gathers evidence, reviewer stage consumes only that evidence pack (no independent tool calls) and applies risk/policy judgment, per the brief's "maximum 2 agents" guidance.
8. **Run both architectures over an identical, frozen test set** (all 10 sample requests plus a handful of hand-authored hidden-style variants) and populate `templates/evaluation_results_template.csv` / a custom comparison script with latency, LLM-call count, tool-call count, and manual pass/fail against policy correctness.
9. **Fix BUG-002** (`.streamlit/config.toml`) before final submission so the one-command start is reproducible on a clean grader machine.
10. **Write `templates/architecture_decision.md` (≤500 words)**, update `README.md` with real setup/architecture/results sections, and produce the workflow/architecture diagrams, using the actual measured numbers from step 8 — never invented ones.

**New tests to add:** `tests/test_policy_engine.py`, `tests/test_solution_single.py`, `tests/test_solution_staged.py`, plus explicit edge-case tests for the SignalWatch conflict, NimbusAI outage, and REQ-1006 injection/missing-info case.

**New dependencies needed:** Gemini SDK (name TBD, NOT VERIFIED), `pytest` (BUG-001).

**Key risks carried forward:** Gemini function-calling/structured-output specifics unverified; hidden grading criteria stricter than the public harness (NOT VERIFIED, so build for the *policy document*, not just the 6 public cases); BUG-002 must be fixed before final submission, not just noted.

---

## 21. Score-Oriented Gap Analysis

### Product + workflow — 15%
**Current:** Streamlit shell with request selector + raw JSON panel exists and runs; no evidence panel or structured recommendation view yet.
**Missing:** evidence panel, recommendation+action panel, human-handoff presentation.
**Future work:** extend `app.py` (or replace) once `handle_request` returns real data — this is mostly a rendering layer over an already-correct contract.

### End-to-end product — 20%
**Current:** every piece up to the business logic works (data, mock service, contract, UI shell, harness) — verified by actually running all of it.
**Missing:** the entire request→evidence→recommendation→handoff pipeline; nothing produces a real `ProcurementDecision` yet.
**Future work:** items 2-7 in §20.

### Agent + tool design — 20%
**Current:** zero agent/tool code; only low-level data/HTTP helpers exist.
**Missing:** tool wrappers, Architecture A, Architecture B, Gemini integration.
**Future work:** items 1-4, 7 in §20.

### Reliability + human controls — 15%
**Current:** `human_review_required` field exists in the contract (defaults `True`); no logic sets it meaningfully yet; the policy document (§9-11) already specifies exactly the required behavior for injection, tool failure, and human authority.
**Missing:** actual enforcement of POL-9/10/11 in code; defensive handling of the vendor-client's raised exceptions.
**Future work:** policy engine (§20 item 2) plus explicit try/except around every external call.

### Evaluation + comparison — 20%
**Current:** the public harness runs and correctly reports "not implemented"; 6 public cases with clear pass/fail expectations exist; a results-template CSV exists but is empty.
**Missing:** any actual results, any comparison across both architectures, any latency/call-count telemetry.
**Future work:** §20 items 5, 8, 10.

### Engineering + communication — 10%
**Current:** starter pack itself is well-engineered (passing tests, clean contracts, working mock service) — good foundation to build on; our own `plan.md` and this recon report exist.
**Missing:** real README sections (architecture, results, decision), architecture diagrams reflecting the actual built system, the decision memo.
**Future work:** §20 item 10.

Be honest: **nothing product-facing exists yet.** Everything scored is currently 0% delivered except the "readiness of the foundation to build on," which is high.

---

## 22. Final Verdict

**READY FOR IMPLEMENTATION**

Every ambiguity that could block starting implementation has been resolved by direct inspection and live execution: the output contract is final and unambiguous, the policy rules are numeric and directly implementable, the data is internally consistent (tests pass) with its intentional traps identified and understood, the mock service's exact behavior (including its one failure mode) is confirmed live, and the full local stack runs end-to-end. The only real blocker found — BUG-002, the Streamlit onboarding prompt breaking a truly clean first run — has since been fixed and verified (`.streamlit/config.toml`, `server.headless = true`) and no longer blocks anything. There is nothing here that is READY WITH BLOCKERS or NOT READY.

---

# Summary and Next Steps

### What we know
- The exact, final output contract (`ProcurementDecision`), the complete policy rulebook with numeric thresholds, the exact data schemas and their join keys, the mock API's exact success/404/503 behavior, and a fully green baseline (10/10 tests, preflight pass, live end-to-end run of mock API + Streamlit UI).
- The data contains deliberate, now-identified traps for every required edge case: SignalWatch (conflicting vendor evidence), NimbusAI (tool unavailable), REQ-1006 (missing info + prompt injection), NeuralDesk's non-enum "limited use" status (silent-misclassification trap).

### What is broken
- BUG-002: `python run_local.py` failed on a genuinely clean machine (Streamlit onboarding prompt) — fixed and verified via `.streamlit/config.toml` (`server.headless = true`).
- BUG-001: `pytest` isn't pinned in `requirements.txt` despite a pytest-compatible `tests/` directory — cosmetic.
- BUG-003: `software_catalog.csv.status` is a non-enum trap in the data (not a defect to fix, a design detail to implement around correctly).

### What we must build
- The deterministic policy engine (§20 item 2) — this is the highest-leverage, lowest-risk first build: no LLM dependency, directly testable, satisfies the "≥1 deterministic tool" requirement, and becomes the shared safety net for both architectures.
- Tool wrappers around the already-working data/HTTP helpers.
- Architecture A (single agent), then Architecture B (staged 2-agent), both terminating through the same policy engine.
- A real evidence panel + recommendation UI (extending the working Streamlit shell, pending your decision in §20 item 6).
- A genuine architecture comparison over an identical, frozen test set, and the resulting decision memo.

### What we must NOT build
- Any database, vector store, RAG pipeline, third+ agent, Docker/Kubernetes infra, or new UI framework beyond what the starter already provides — none of this is needed and the brief explicitly penalizes unnecessary orchestration.
- A rewrite of `src/contracts.py`, `src/data_access.py`, `mock_api/app.py`, or the data files themselves — all are correct and final as shipped.

### Top 10 implementation priorities
1. Confirm Gemini SDK package name + structured-output/function-calling approach (resolves the one open NOT VERIFIED item that blocks writing any agent code).
2. Build `src/policy_engine.py` + its unit tests (no LLM needed).
3. Build the 4 remaining tool wrappers (budget, catalog/overlap, purchase history, vendor registry+risk with conflict/outage handling).
4. Implement `handle_request(..., architecture="single")` — Architecture A.
5. Validate Architecture A against all 6 public cases + the 4 remaining sample requests + the SignalWatch/NimbusAI/REQ-1006 traps.
6. Decide UI approach (extend Streamlit vs. rewrite) and build the evidence/recommendation panel.
7. Implement `handle_request(..., architecture="staged")` — Architecture B, reusing the same tools/policy engine.
8. Run both architectures over the identical frozen test set; capture latency/call-count/pass-fail.
9. Fix BUG-002 (`.streamlit/config.toml`) so the one-command start is reproducible on a clean machine.
10. Write the architecture decision memo, README, and diagrams from the real measured results.

### Recommended first implementation task
Build `src/policy_engine.py` with its unit tests. It has zero external dependencies (no LLM key needed to develop or test it), directly implements the assignment's explicit "CODE: thresholds + deterministic checks" pillar, satisfies the mandatory deterministic-tool requirement on its own, and becomes the one component both Architecture A and Architecture B will share — building it first de-risks everything downstream.
