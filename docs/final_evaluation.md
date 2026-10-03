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

## 3. Real-model sample (final, pre-registered)

Question: does the actual model behave acceptably on representative cases under the final architecture, and does B earn its cost?

- **Cases:** sixteen, fixed in code as `REAL_SAMPLE` before the run. They include all six public cases (PUB-01 to PUB-06), overlap, conflicting and expired vendor evidence, unknown vendor, security and privacy, prompt injection in request and vendor text, the threshold edges, the unavailable vendor path, and an incomplete request.
- **Model and provider:** Gemini 3.7 Flash (`google/gemini-3.7-flash`) through CloseRouter's OpenAI-compatible endpoint. The model was changed from `gemini-3-flash` by a dated amendment to the pre-registration, because the earlier route was unavailable at the provider.
- **Decision rule:** committed in `docs/preregistration_b_rule.md` before the final run, with Amendment 1 for the model. It was not changed afterwards.
- **Run:** `evaluation/correctness/results/correctness_real_20261003T142144Z.json`, git revision `07c5dd2`, clean worktree, provider `closerouter`. Both architectures ran on the same cases, interleaved per case.

Results:

| | Architecture A | Architecture B |
|---|---|---|
| Comparable cases (no provider failure) | 16 of 16 | 16 of 16 |
| Recommendation and next action correct (primary) | 16 of 16 | 16 of 16 |
| Evidence grounded (secondary) | 16 of 16 | 16 of 16 |
| Regressions against A (deterministic and safety) | not applicable | none |
| Median latency | 18.2 s | 24.4 s |
| Median logical LLM calls | 3 | 4 |
| Attempts checked against the HTTP count | 32 of 32 match, 0 mismatches | (same run) |

**Rule outcome.** B showed no improvement and no regression, so the rule selects Architecture A.

**Notes.**
- The live model issued supplemental tool lookups in both architectures, which the offline contract did not predict. Those lookups are identity-bound and cannot change any policy field.
- Sixteen cases and one run are descriptive. No significance claim is made.
- Earlier live attempts are indexed in `evaluation/correctness/results/INDEX.md`. The archived attempts that ended in provider outage are not results.
- An earlier eight-case run on direct Gemini (`correctness_real_20261003T122905Z.json`, revision `69e483d`) is kept as history. It is not the final result.

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
