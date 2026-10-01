# Architecture Decision

## Decision

**Ship Architecture A (single-agent baseline).** The evaluation demonstrated equivalent deterministic/policy safety and correctness between the two architectures, while Architecture B introduced additional model latency and call overhead without a demonstrated compensating quality improvement.

## Context

Architecture A uses one reasoning agent: it gathers evidence via four allowlisted tools, then produces a recommendation validated against a deterministic policy engine. Architecture B splits reasoning into an analyst stage (gathers the same evidence, writes a structured report) and a reviewer stage (consumes that report plus the policy result, produces the final recommendation). Both share identical tools, policy engine, validator, and output contract — only orchestration differs. B was built to test whether a second reasoning stage measurably improves the product.

## Evaluation

Two evidence classes. A **frozen 25-case replay comparison** (deterministic stand-in model) found 25/25 expected-check passes for both architectures, 0/25 deterministic-field mismatches, 0 safety violations; B used a median 4 LLM calls to A's 3, tool calls identical (3 median, both). A **six-case real-Gemini sample** (`gemini-2.5-flash`, same cases, both architectures — representative, not statistically significant) found: median latency 12.4s (A) vs. 20.8s (B, +68%); median LLM calls 3.5 (A) vs. 4.0 (B); 5/6 cases with identical policy fields; 0 safety violations either architecture. The one differing case (SignalWatch conflict) was caused by a transient Gemini 503 interrupting B's analyst mid-retrieval — the policy engine responded safely, never fabricating a result. The divergence reflects B's larger failure surface, not incorrect reasoning.

## Trade-off

B adds a second reasoning stage, roughly one more real LLM call, and materially higher latency, plus more opportunities for a transient failure to interrupt a request (demonstrated by TC-10). It showed safe behavior under that failure, correct independent handling of a real prompt-injection attempt (matching A), and one genuine qualitative clarification (whether a requested product was new or a variant of an existing catalog entry) that A did not raise in that sample. It did **not** show a repeatable, measurable improvement in correctness, policy compliance, or escalation accuracy over A, on either evidence class.

## Decision Rationale

Policy correctness and safety were equivalent across both evidence classes. The only consistent, measured differences were operational: more LLM calls, higher latency, and greater exposure to transient failures for B, against one anecdotal quality observation. Per the assignment's own framing — a simpler system that performs as well or better is a stronger answer than unnecessary orchestration — the evidence supports shipping the architecture that achieves the same verified outcome at lower cost and complexity.

## Limitations

The real-model sample (n=6) is too small to rule out a quality difference either direction; it establishes cost and safety, not a definitive quality verdict. Replay results are exact but cannot assess recommendation quality, since its text is templated. Free-tier quota limited how much real-model evidence could be gathered.
