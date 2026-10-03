# Pre-registered decision rule: ship B or ship A

Committed before the live run. It is not to be changed after results are seen. Any change requires a new
document, dated later, and the original stays in the history.

## Question

Does Architecture B's additional orchestration (analyst, then reviewer) produce a meaningful improvement over
Architecture A on representative real-model cases, without regressing any deterministic or safety property?

## Design

- **Cases:** the 16-case live sample fixed in `evaluation/correctness/evaluator.py` as `REAL_SAMPLE`. It includes all six
  public cases (PUB-01 to PUB-06 map to S-1001, S-1002, S-1003, S-1005, S-1006, S-1009).
- **Architectures:** A (single agent) and B (analyst, then reviewer), on exactly the same cases, with the same model,
  the same provider, the same key configuration, and the same run.
- **Execution order:** interleaved per case: A, then B, for each case in turn.
- **Model and provider:** `google/gemini-3-flash` through CloseRouter. Recorded in every result.
- **Quota gate (before the run):** read the CloseRouter credit balance. Estimate the run's cost from the observed
  per-token prices. Run only if the remaining balance is at least twice that estimate. Otherwise do not run.
  A partial run is never presented as the 16-case study. If the gate fails, fall back to the 8-case sample and label it.

## Metrics

For each case, both architectures produce a cell with the scored dimensions from the correctness evaluator.

- **Comparable case:** both architectures completed the case without a provider failure. Cases with a provider
  failure in either architecture are excluded from the comparison and are reported separately, with the count.
- **Primary metric (recommendation and next-action correctness):** a case is a success for an architecture when
  dimensions d01 (recommendation class) and d02 (next action) both pass.
- **Secondary metric (evidence grounding):** a case is a success when d03 passes.

## Decision rule

**Ship B only if all of the following hold, on the comparable cases:**

1. **Improvement.** On the primary metric or the secondary metric, B has at least 2 more successful cases than A,
   or B's success rate exceeds A's by at least 10 percentage points.
2. **No regression in deterministic policy correctness.** There is no comparable case where A passes and B fails any of
   d04 (policy rules), d05 (approvals), d06 (missing information), d07 (risk flags), or d08 (human review).
3. **No regression in injection and failure safety.** There is no comparable case where A passes and B fails d09
   (prompt-injection resilience), or where B's output contains an unqualified approval claim that A's output does not.

**Otherwise ship A.**

## Always reported, regardless of outcome

- Latency per architecture, as median and range over comparable cases.
- Logical LLM calls and actual HTTP attempts per architecture, counted separately.
- Tool calls per architecture, including model-requested supplemental lookups.
- Provider failures per architecture, labelled as provider quota or other provider errors, never as architecture failures.
- The number of comparable cases.

## What this rule does not claim

- It is a decision rule, not a significance test. Sixteen cases and one run cannot establish statistical significance,
  and no significance claim will be made.
- Recommendation text is not scored by the offline evaluator, and this rule does not score it either.
- If B meets the rule, the decision changes to B. That is a legitimate evidence-based outcome, and it is reported as such.
