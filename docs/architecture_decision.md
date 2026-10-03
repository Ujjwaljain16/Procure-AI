# Architecture Decision

## Decision

**Ship Architecture A (single agent).** It matched Architecture B on every deterministic and safety check we can measure, uses fewer model calls, and is simpler to operate and test. We did not measure a quality difference between the two, so this decision does not claim one.

## Evidence

**Frozen replay set (25 cases, deterministic stand-in model).** Both architectures pass all expected checks (25/25), agree on every deterministic field (0 mismatches), and pass every recorded per-run invariant. Caveat: both use the same policy engine and the same stand-in model, so agreement on policy fields is expected by construction. This shows the wiring is correct, not that either architecture reasons well.

**Real-model sample (6 cases, one run each, gemini-2.5-flash, temperature 0).**
- B was slower in 5 of 6 cases (exact two-sided sign test, p ≈ 0.22). That is not statistically established at this sample size.
- Median latency: A 12.4 s (95% bootstrap CI 10.1–14.6); B 20.8 s (CI 13.2–27.0). The intervals overlap heavily. The earlier "+68%" headline is not supported.
- Each architecture had one transient 503 during a model call. Both degraded to a human-review decision with the reason recorded. B's failure was not evidence of weaker reasoning.

**Quality.** Not measured. B's analyst raised one useful clarification (whether a NeuralDesk request was a new product or a variant of an existing one). We observed it once and do not treat it as a measured advantage.

## Trade-off

B adds a reasoning stage, roughly one more model call per request, and a second failure point. Nothing we measured offsets that cost. The assignment asks for a simpler system when it performs as well, and on measured behavior A does.

## What would change this decision

Ship B only if a blinded, two-rater study on a sealed holdout of at least 30 cases shows B improving recommendation or missing-information quality, with a 95% interval above zero and reported inter-rater agreement. A failure-mode analysis showing a class of cases that A systematically misses would also justify revisiting.

## Limitations

- The real sample has six cases and one run each. It supports the safety and cost observations, not a quality verdict.
- Replay results cannot judge recommendation text, since the stand-in writes fixed text.
- The policy engine determines most deterministic outcomes, so agreement between architectures is largely structural.
- One model family and one prompt version were tested.
