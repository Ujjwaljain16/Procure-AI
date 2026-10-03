# Architecture A Baseline (frozen before Architecture B implementation)

Recorded before any Architecture B code was written. Architecture A must not
change until the A-vs-B comparison in this phase is complete; any change
required for fairness/safety will be documented explicitly with a re-freeze.

## Source control state

The repository has not been committed since the last user-requested commit
(policy engine + tests). `git status --short` at freeze time:

```
 M .env.example
 M app.py
 M requirements.txt
 M src/contracts.py
 M src/policy_engine.py
 M src/solution.py
 M tests/test_policy_engine.py
?? src/agent/
?? src/tools/
?? src/ui/
?? tests/agent_fakes.py, conftest.py, test_agent_single.py, test_agent_validation.py,
   test_catalog_tool.py, test_employee_budget_tool.py, test_gemini_adapter.py,
   test_purchase_history_tool.py, test_real_gemini_smoke.py, test_solution_single.py,
   test_tools_integration.py, test_ui.py, test_vendor_risk_tool.py
```

There is no git commit boundary to diff against for "what changed in Phase 6" --
the file hashes below are the actual baseline reference instead.

## Frozen file inventory (sha256, first 12 hex chars, + line count)

```
src/agent/single_agent.py     67ac73b6fdcc   195L
src/agent/validation.py       111d6d6ab30b   132L
src/agent/tools_registry.py   3941887e46a6   309L
src/agent/prompts.py          e7644e148466    90L
src/agent/gemini_adapter.py   7a76059717e2   158L
src/agent/schemas.py          24aaa5cdd518    37L
src/policy_engine.py          3c5ef5701a4a   736L
src/contracts.py              0c292870ce14    48L
src/solution.py               b4293c09b108    20L
```

Architecture B must not modify any of these files. If a Phase 6 correctness
finding requires a genuine fix to one of them, this document will record the
before/after hash and the reason, and the test/eval baseline below will be
re-run and re-frozen.

## Documented exceptions (re-freeze log)

**2026-10-03 — Tier 2 reliability pass.** Two frozen files changed, each a
narrow, mechanical edit; nothing about the deterministic pipeline changed.

| File | Before | After | Change and reason |
|---|---|---|---|
| `src/agent/single_agent.py` | `67ac73b6fdcc` | `015aff7ccf8b` | `data_access.get_request(...)` → `get_request_validated(...)`, so a structurally broken record fails before any model call. Staged (`staged_agent.py`, not frozen) got the same one-line swap. |
| `src/agent/validation.py` | `111d6d6ab30b` | `39f826cb730f` | The contract-level recommendation for a Gemini failure now uses the user-facing failure taxonomy (`src/agent/failure_taxonomy.py`) instead of embedding the raw exception class name (e.g. `ClientError`). The raw name still flows through `gemini_unavailable_reason` in logs and stored results. Also one new import. |

Re-verification after the change: the frozen 25-case replay re-run
(`evaluation/run_comparison.py`) gave 25/25 for both architectures, 0/25
deterministic-field mismatches, and PASS on `evaluation/regression.py`
against the prior run on every metric. Full suite: 343 passed.

Unchanged and still frozen: `tools_registry.py`, `prompts.py`,
`gemini_adapter.py`, `schemas.py`, `policy_engine.py`, `contracts.py`.

## Model / configuration

- SDK: `google-genai>=1.0,<2`
- Model: `gemini-2.5-flash` (`DEFAULT_MODEL` in `gemini_adapter.py`; overridable via `GEMINI_MODEL`). `gemini-3.8-flash` was tried in Phase 4 and returned two consecutive real `503` "high demand" errors on the free tier; not retried since.
- Function calling: manual (`automatic_function_calling.disable=True`), tool declarations from `tools_registry.TOOL_SPECS`.
- Structured output: `response_schema=AgentSynthesis` (Pydantic), `response_mime_type="application/json"`.
- `MAX_TOOL_TURNS = 6` (single_agent.py) -- up to 7 total LLM calls per request (6 tool turns + 1 synthesis).

## Prompt version

`SYSTEM_PROMPT` in `src/agent/prompts.py` -- 8 bullet points establishing: recommendation-only role, policy-engine authority, tool usage guidance, untrusted-data boundary, no-fabrication rules, uncertainty handling, no-autonomous-approval-claims rule, and (added Phase 4/5) the `prompt_injection_detected` field instruction. Unchanged since Phase 5.

## Tool set (unchanged since Phase 3/4)

`get_employee_budget`, `search_catalog`, `search_purchase_history`, `get_vendor_evidence` -- allowlisted in `src/agent/tools_registry.TOOL_SPECS`, each backed by `src/tools/*.py`.

## Policy engine version

`POLICY_VERSION = "2026.09"` (module constant in `src/policy_engine.py`), `REFERENCE_DATE = date(2026, 9, 30)`. Unchanged since the Phase 3 NaN-handling fix.

## Evaluation dataset version (starter pack)

`evals/public_cases.json` -- 6 cases, unchanged since the starter pack was extracted. Phase 6 additionally freezes a larger, independent set (`evaluation/cases.json`) for the A-vs-B comparison itself -- see `docs/architecture_comparison.md`.

## Test baseline (actual, run at freeze time)

Command: `python -m pytest tests/ --ignore=tests/test_real_gemini_smoke.py -q`

```
213 passed, 0 failed, 0 skipped, 1 warning, 7.21s
```

Breakdown (unchanged from the Phase 5 report): 10 starter + 81 policy engine + 45 tools + 4 tool-policy integration + 9 Gemini adapter + 21 agent validator + 25 agent orchestration + 5 solution routing + 13 UI view-model = 213.

`python verify_setup.py` → `PRE-FLIGHT PASSED`.

## Public evaluation baseline (real API, from Phase 5)

4/6 PASS (PUB-01, PUB-02, PUB-03, PUB-04), 2/6 FAIL (PUB-05, PUB-06) due to the real API's **daily** free-tier quota (20 requests/day) being exhausted mid-run, confirmed by the error payload's `GenerateRequestsPerDayPerProjectPerModel-FreeTier` quota ID -- not a logic defect. Quota resets on Google's schedule; not available again within this same day, so Phase 6's evaluation against A is run via the mocked/replay path (see `docs/architecture_comparison.md` for exactly which parts, if any, use the real API).

## Known limitations at freeze time (carried from Phase 5)

- No automatic retry on transient Gemini failures (deliberate simplicity choice).
- `search_catalog` matching is exact-normalized-string, not semantic.
- The autonomous-approval-claim guard is a word-boundary heuristic, not full NLU.
- Free-tier daily quota (20 req/day) is the binding constraint on real-API evaluation depth.

## Current telemetry behavior

`RunTelemetry.llm_calls` counts every attempted `generate_turn`/`generate_structured` call, including ones that fail (fixed in Phase 5 after a real 503 revealed the undercounting). `tool_calls` counts every `ToolRegistry.execute()` invocation, including rejected/unsupported ones. `latency_ms` is wall-clock from the start of `run_single_agent_with_trace` to just before return. `architecture` is always `"single"` for this path.
