# Historical frozen replay results: index

This folder holds the regression layer (layer 1 in `docs/final_evaluation.md`). Replay uses a deterministic stand-in model and spends no quota. Its expectations are historical, not a correctness oracle.

## Current

| File | What it is | Git revision |
|---|---|---|
| `comparison_20261003T111322Z.json` (+ `single_`, `staged_`) | Post-hardening replay: both architectures on the frozen 25-case set, after the authority boundary. This is the current regression result. | `7e0e598` |

## Baseline (frozen, pre-hardening)

`baseline/` holds the frozen pre-hardening replay, `comparison_20261003T100115Z.json` and its per-architecture files. It is the reference for detecting unexpected behaviour changes. It is not edited.

## Archive

`archive/` holds replay runs made during development, from 2026-09-30 to 2026-10-03. They are kept for audit and are superseded by the current result. Runs made before the authority boundary (2026-09-30 to early 2026-10-03) reflect the earlier model-driven evidence path, and are not comparable to the current result.

Filenames carry their UTC timestamps, so each run can be traced in the git history.
