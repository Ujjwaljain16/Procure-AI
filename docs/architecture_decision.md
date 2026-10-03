# Architecture decision

**Decision: Ship Architecture A as the default.** Keep Architecture B in the codebase as an evaluated alternative, selectable but not the default. The rule that decided this was written and committed before the final live run (`docs/preregistration_b_rule.md`).

**Why the decision rests on the evidence**

Both architectures share one authoritative path: a validated request, the deterministic evidence preflight, the deterministic policy engine, the validator, and human handoff. The model cannot choose the evidence the policy uses. The architectures differ only in orchestration: A is one agent; B is an analyst followed by a reviewer.

So the question is whether B's extra orchestration produces a measurable benefit that justifies its cost.

- **Offline correctness (26 cases, four fault modes).** Both architectures pass every scored dimension, and their deterministic outputs are identical across normal, hostile, malformed, and outage runs (104 of 104 runs per architecture). Offline evaluation cannot separate them on correctness, because the policy path is shared.
- **Live, final run (16 cases, one run, Gemini 3.7 Flash through CloseRouter).** All 16 cases were comparable, with no provider failures. A and B each matched the ground truth on recommendation and next action in 16 of 16 cases, and each grounded its evidence in 16 of 16 cases. B had no regressions against A in any deterministic or safety dimension.
- **Cost.** B's median latency was 24.4 s against 18.2 s for A. B made one more logical model call per case (median 4 against 3).

**Rule outcome.** The pre-registered rule required B to show at least two more successful cases, or ten percentage points more, on the primary or secondary metric, with no regression. B showed zero more successes and no regressions, so the rule selects A.

**What this does not show.** Sixteen cases and one run cannot establish statistical significance, and no significance claim is made. The live model also issued supplemental tool lookups in both architectures, which the offline contract did not predict. Recommendation text is not scored by the offline evaluator.

**Conditions to revisit.** Re-evaluate B if a larger live sample shows a repeatable gain on recommendation or evidence grounding, or if a future policy needs a separate reviewer stage that a single agent cannot provide cleanly.

**Limits to state with the result.** Prompt-injection visibility is a deterministic, pattern-based signal, and it is not a complete defense; paraphrased attacks may evade it.
