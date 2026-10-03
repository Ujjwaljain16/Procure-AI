# Architecture decision

**Decision (recommended):** Ship Architecture A as the default. Keep Architecture B in the codebase as an evaluated alternative, selectable but not the default.

**Why this decision rests on the evidence**

Both architectures now share one authoritative path: a validated request, the deterministic evidence preflight, the deterministic policy engine, the validator, and human handoff. The model cannot choose the evidence the policy uses. The architectures differ only in orchestration: A is one agent; B is an analyst followed by a reviewer.

So the question is whether B's extra orchestration produces a measurable benefit that justifies its cost.

- **Correctness, offline (26 cases, four fault modes).** Both architectures pass every scored dimension, and their deterministic outputs are identical across normal, hostile, malformed, and outage runs (104 of 104 runs for each architecture). Offline evaluation can't separate them on correctness, because the policy path is shared.
- **Correctness, live (8 cases, one run).** On the 10 cells that completed, both architectures matched the hand-authored recommendation class and kept every policy field identical to the normal run. No quality advantage for B appears.
- **Cost, live.** On the completed cells, B made about twice the logical LLM calls of A (about 5 against 2) and roughly three times the median latency (about 30 s against 9 s). B also issued four supplemental tool lookups where A issued none in most cases, which the offline contract did not predict.

**What this does not show.** The live sample has eight cases and one run. Six cells failed on provider quota (HTTP 429) for both architectures; that reflects the provider stopping service, not either architecture. No statistical significance is claimed, and a single run cannot rule out a quality difference that a larger sample would reveal.

**Why A is the default.** B adds two model stages, more calls, more latency, and more tool traffic, and in this evidence it buys no measurable quality. A reaches the same policy-compliant outcomes with fewer moving parts, so it is the simpler system to operate and to audit. A is also the path whose deterministic guarantees are tested most directly.

**Conditions to revisit.** Re-evaluate B if a larger live sample shows a repeatable quality gain on recommendation or evidence grounding, or if a future policy needs a reviewer stage that a single agent cannot provide cleanly. Until then, B stays as an evaluated alternative rather than a shipped default.

**Limits to state with the result.** Prompt-injection visibility is a deterministic, pattern-based signal, and it is not a complete defense; paraphrased attacks may evade it. Recommendation text is not scored by the offline evaluation. Live results are descriptive.
