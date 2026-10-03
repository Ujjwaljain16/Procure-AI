# Final evaluation

The evaluation has four layers. Each answers a different question, and the layers are kept separate on purpose. Do not read one layer's results as evidence for another.

## 1. Historical frozen replay (regression only)

Question: did the redesign change behaviour that was already accepted?

- Case set: the frozen 25-case set in `evaluation/cases.json` (version `2026.09-tc1`). It is preserved unchanged; its expectations are historical, not an oracle for correctness.
- Method: both architectures run through the real tools, policy engine, and validator, with a deterministic stand-in model.
- Result: post-hardening replay (`evaluation/results/comparison_20261003T111322Z.json`) shows 25/25 expected checks for both architectures, zero deterministic-field differences between A and B, and zero differences from the earlier post-hardening replay except for one declared change: TC-12 (the injected request) now carries `prompt_injection_detected`.
- Declared intentional changes from the original baseline: replayed agent cases make one fewer model turn, because the preflight now gathers evidence in code, and TC-04 has an overlap expectation that was changed on purpose.

Historical baseline artifacts (`comparison_20261003T100115Z.json` and earlier) are unchanged.

## 2. Independent correctness, offline

Question: are the decisions correct, and does the architecture withstand controlled failures and adversarial outputs?

- Ground truth: `evaluation/correctness/ground_truth.json`, 26 cases, hand-derived from `data/procurement_policy.md`, the starter data, the public expectations, and explicit adversarial cases. Each case cites its policy basis. Ambiguous fields are excluded from scoring rather than guessed.
- Method: each case runs for both architectures under four modes: normal, hostile (the model substitutes the vendor and employee and claims approval), malformed output, and model outage. Scoring uses 13 dimensions.
- Results (run `correctness_20261003T113526Z.json`, clean worktree):
  - no failing dimensions for either architecture in any mode;
  - deterministic outputs identical to the normal run in 104 of 104 runs for each architecture (boundary identity);
  - 12 of 12 public checks pass.
- Self-checks: 24 evaluator tests, including eight deliberately broken behaviours, each caught in the dimension it breaks.
- Limits: the expectations were written after some outputs were visible, and dimensions 1 and 2 classify the same structured fields as dimension 7. Recommendation free text is not scored offline.
- One policy interpretation was adjudicated after the disagreement appeared (S-1007, `vendor_review_expired`). It is recorded in the case's `revision_log` and captured as an executable test, `test_conflicting_vendor_evidence_requires_security_but_not_expired_flag`.

## 3. Real-model sample

Question: does the actual Gemini model behave acceptably on representative cases under the final architecture?

- Cases (fixed in code as `REAL_SAMPLE`, each with a stated reason): normal request with catalog overlap (S-1001); conflicting vendor evidence with an expired live review (S-1007); unknown vendor (S-UNK); customer PII with cross-region storage (S-1004); prompt injection in request text (S-INJ-REQ); threshold edge above $25,000 (S-B06); unavailable vendor-risk service (S-1009); incomplete request with an injected instruction (S-1006).
- Setup: model `gemini-2.5-flash`; both architectures on the same eight cases; the same key pool for both; execution interleaved per case (A, then B), so both see the same quota conditions.
- Final run: `evaluation/correctness/results/correctness_real_20261003T122905Z.json`, git revision `69e483d`, clean worktree. A partial earlier run (`121623Z`) is kept for audit only and must not be cited as the result.

Results per architecture:

| | Architecture A | Architecture B |
|---|---|---|
| Cases completed | 5 of 8 | 5 of 8 |
| Cases failed from provider quota | 3 (S-UNK, S-INJ-REQ, S-B06) | 3 (the same three) |
| Recommendation class matches ground truth (completed cells) | 5 of 5 | 5 of 5 |
| Boundary identity (policy fields equal to normal run) | 8 of 8 cases | 8 of 8 cases |
| Logical LLM calls, completed cells | 2 typical | about 5 typical |
| Actual HTTP attempts, checked against the transport | 16 checked, 0 mismatches | (same check) |
| Tool calls, completed cells | 4 in four cells, 8 in one | 8 in all five cells |
| Median latency, completed cells | about 9 s | about 30 s |

Notes:

- **Quota.** The provider returned 19 HTTP 429 responses. Most were absorbed by key rotation, and the calls then succeeded. Six cells ended with no answer, all for both architectures. These are provider-quota failures, not architecture failures.
- **Tool-call behaviour.** The offline contract assumes four tool calls for a normal run. The live model issued supplemental lookups, mostly in B. Those lookups are identity-bound and cannot change the policy fields; boundary identity still held in every cell.
- **Public checks.** PUB-01, PUB-05, and PUB-06 pass for both architectures. PUB-02, PUB-03, and PUB-04 are not executed because their cases are outside the eight-case sample.
- **Statistics.** Eight cases, one run, no significance claim. These numbers are descriptive.

## 4. What each layer supports

- The deterministic authority boundary and policy behaviour are established by layers 1 and 2, offline and reproducibly.
- Real-model behaviour on representative cases is described by layer 3. Its cost and call-count findings are reported; its quality claims are limited to the cases that completed.
- Architecture B's additional orchestration showed no measurable quality benefit in this evidence and a measurable cost. The decision is in `docs/architecture_decision.md`.

Commands:

```bash
python evaluation/run_comparison.py                            # layer 1, replay, no quota
python evaluation/correctness/evaluator.py                     # layer 2, offline, no key
GEMINI_API_KEY_POOL=... python evaluation/correctness/evaluator.py --real   # layer 3, live, spends quota
```
