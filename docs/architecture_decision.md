# Architecture Decision Memo

**Maximum length: 500 words**

## Decision
Which architecture would you ship today: **single agent** or **staged / 2-agent**?

**Ship Architecture A (single agent).** Both architectures share one authoritative path: deterministic evidence gathering, the deterministic policy engine, the validator, and human handoff. The model never chooses the evidence the policy uses. The architectures differ only in orchestration. The pre-registered rule (`docs/preregistration_b_rule.md`) was committed before the final live run and selects A.

## Evidence
Both architectures ran on the same test set: the 16 pre-registered live cases (`evaluation/correctness/results/correctness_real_20261003T142144Z.json`, Gemini 3.7 Flash through CloseRouter). Offline, both architectures also passed every scored dimension across 26 cases and four fault modes.

| Metric | Single agent | Staged / 2-agent |
|---|---:|---:|
| Cases passing your quality criteria | 16 / 16 on recommendation, next action, evidence grounding, policy, and human escalation | 16 / 16 on the same criteria |
| Avg latency | 18.1 s (median 18.2 s) | 26.0 s (median 24.4 s) |
| Avg LLM calls | 3.0 | 4.0 |
| Avg tool calls | 8.0 | 8.0 |
| Notable policy/grounding failures | None on policy or grounding | None on policy or grounding; no regression against A |

The live model made more calls than the offline contract allows, in every case, in both architectures. Call-count dimensions d12 and d13 therefore did not pass. The cause is supplemental tool lookups, which are identity-bound and cannot change a policy field.

## Trade-offs
Nothing measurable improved. Staged B matched A on all 16 cases and no deterministic or safety dimension regressed. It cost about 8 s more on average and one more model call per case. The reviewer stage added latency without changing any outcome on this set.

## Risks / limitations
- Sixteen cases from one run. The result is descriptive and makes no significance claim.
- The live model's supplemental lookups exceed the offline call-count contract.
- The UI can show a repeated evidence row when a lookup is repeated. Policy fields are unaffected.
- Prompt-injection visibility is pattern-based and is not a complete defence.
- Recommendation text is not scored offline.

Before production use, I would validate on a larger live sample, review recommendation text by people, set a per-request call budget, add authentication and persistence, and connect real vendor and approval systems.

## Why this is the right MVP
The single agent meets every quality criterion on this evidence, with fewer model calls and lower latency. The authority boundary sits in code under either architecture, so the second agent adds cost without adding safety. The product is recommendation-only, and every sensitive approval stays with a human, so the simpler system is sufficient for the client problem. I would revisit B if a larger live sample showed a repeatable gain on recommendation or evidence grounding, or if a future policy needed a reviewer stage that one agent cannot provide cleanly.
