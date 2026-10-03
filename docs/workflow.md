# Workflow / Architecture Notes

```text
Purchase Request
      |
      v
Understand request              validation: structure only (model not involved)
      |
      v
Gather evidence ----> Budget, catalog, purchase history, vendor registry and risk
      |                (deterministic preflight; model may add identity-bound lookups)
      v
Deterministic checks ----> POL-1 to POL-11: thresholds, budget, required fields
      |
      v
Reason about policy & risk      model interprets the evidence and policy result (A or B)
      |                         final validator keeps only retrieved evidence IDs
      v
Structured recommendation       ProcurementDecision
      |
      v
Human review / approval         always required; approvals stay pending
```

## Tools

| Tool | Deterministic | Used by | Retrieves |
|---|---|---|---|
| `get_employee_budget` | Yes | Preflight; model may re-request | Employee and department budget |
| `search_catalog` | Yes | Preflight; model may re-request | Catalog overlap |
| `search_purchase_history` | Yes | Preflight; model may re-request | Prior purchases |
| `get_vendor_evidence` | Yes | Preflight; model may re-request | Registry and live vendor-risk status, reported separately |
| `evaluate_policy` | Yes | Code only, never exposed to the model | Policy fields |

## Deterministic vs model-driven

| Deterministic (code) | Model-driven (AI) |
|---|---|
| Request validation | Interpreting the evidence and the request text |
| Evidence preflight | Choosing supplemental lookups, within the request's own identifiers |
| Policy engine (POL-1 to POL-11) | Writing the recommendation, rationale, and next step |
| Approvals, risk flags, missing information, human-review flag | Self-reporting prompt injection (visibility only) |
| Output validation and citation filtering | |

## Agent responsibilities

- **Architecture A (single agent).** One tool loop that may request supplemental lookups, then one structured synthesis.
- **Architecture B (staged).** An analyst may use tools and writes a structured report. A reviewer, with no tools, writes the recommendation from the report and the evidence.
- **Both.** Neither can set approvals, risk flags, missing information, or the human-review flag. Neither can approve, purchase, or change a budget.

## Handoff format

The handoff is a `ProcurementDecision`:

- `recommendation`
- `evidence`: each item has `source`, `finding`, and `reference`
- `required_approvals`
- `missing_information`
- `risk_flags`
- `next_step`
- `human_review_required`, always true
- `telemetry`: architecture, model, logical LLM calls, HTTP attempts, tool calls, latency

The UI renders this as a copyable handoff summary. The summary is built from the decision's own fields, with no second model call.

## Stop and escalation conditions

| Condition | System response |
|---|---|
| Missing information (cost, users, department) | Reported as "Missing". The recommendation asks for clarification and does not proceed |
| Existing tool already covers the need | `existing_tool_overlap` is raised. The existing entry is shown as evidence. This is not a rejection |
| Vendor registry and live service disagree | `conflicting_vendor_evidence` is raised. Both sources are shown. The case goes to manual verification |
| Vendor-risk service unavailable | `vendor_risk_unavailable` is raised. Never inferred as approved. Routed to manual review |
| Security, privacy, or legal trigger, or a cost tier | The specialist or tier approval is added deterministically |
| Prompt injection in business data | Treated as data. No policy rule reads free text. `prompt_injection_detected` is raised as a visibility flag only |
| Model failure, malformed output, or timeout | Policy fields are unchanged. The recommendation states the failure. Human review is still required |

## What I intentionally did not build

- **No autonomous action.** No code path approves, purchases, changes a budget, or accepts vendor terms.
- **No database or approval persistence.** Each analysis appends one audit line to `runs/audit.jsonl`. Decisions are not stored as records.
- **No authentication or access control.** The UI and the vendor-risk mock bind to loopback.
- **No real vendor, identity, or procurement integration.** The data is synthetic.
- **No third agent.** The brief recommends at most two, and the evidence did not justify B.
- **No automatic retry on model failure.** The system falls back to the human-review state.
