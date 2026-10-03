# Independent correctness results: index

This folder holds the correctness layer (layer 2, offline) and the real-model sample (layer 3). Expectations come from `evaluation/correctness/ground_truth.json`, not from program output.

## Current

| File | What it is | Git revision | Live model? |
|---|---|---|---|
| `correctness_20261003T113526Z.json` | Offline reproduction: 26 cases, both architectures, four fault modes. Clean worktree. | `afb9cab` | No |
| `correctness_real_20261003T122905Z.json` | **Final real-model sample.** Eight cases, both architectures, interleaved per case, one key pool. Six cells lost to provider quota (HTTP 429), recorded as quota failures, not architecture failures. | `69e483d`, clean worktree | Yes (`gemini-2.5-flash`) |

## Archive

`archive/` holds superseded offline runs made while the ground truth and provenance fields were being finalised. They are kept for audit and are not cited as results.

- `correctness_real_20261003T121623Z.json` is a **partial** live run, recorded before the independent HTTP counter existed. Its attempt integrity check did not run. It is not a result. Do not cite it as the live A/B outcome.

## Failed live attempts (provider outage, not results)

- `archive/FAILED_closerouter_attempt_140551Z.json` and `archive/FAILED_closerouter_attempt_140625Z.json`: two copies of the same
  CloseRouter 16-case attempt at git revision `aa2fafe`. Only 3 of 32 cells completed. The rest failed with HTTP 503 (no available
  upstream for `google/gemini-3-flash`, circuit open at the provider), HTTP 429, and read timeouts. These are provider-availability
  failures, not architecture or model results. Do not cite them.

## Final pre-registered live run (CloseRouter, google/gemini-3.7-flash)

- `correctness_real_20261003T142144Z.json`: 16 cases, both architectures, interleaved per case. Git revision `07c5dd2`,
  clean worktree. All 16 cases comparable, no provider failures. Pre-registered rule (docs/preregistration_b_rule.md,
  with Amendment 1 for the model): A and B both 16/16 on recommendation and next action; both 16/16 on evidence grounding;
  no regression. Rule outcome: ship A. Median latency A 18.2 s, B 24.4 s; median logical calls A 3, B 4.
  n=16, one run: descriptive, no significance claim.
