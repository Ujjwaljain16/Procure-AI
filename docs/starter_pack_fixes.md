# Starter pack: issues found and fixed

The starter pack was a scaffold, and the brief asks us to diagnose and fix its issues. This page lists each issue, where it was found, and what was done. Each fix is verified by the test suite or by a clean-machine check.

## Setup and runtime

| Issue | Where | Fix | Status |
|---|---|---|---|
| `pytest` was missing from the dependencies, so `python -m pytest tests/` failed after a clean install. | `requirements.txt` | Added `pytest>=8,<9`. The lock file pins the exact version. | Fixed |
| On a machine that had never run Streamlit, the first-run onboarding prompt stopped `python run_local.py`, which is the documented one-command start. | `run_local.py`, Streamlit first-run | Added `.streamlit/config.toml` with headless mode and loopback address. Verified on a clean configuration. | Fixed |
| The vendor-risk mock and the UI could be exposed beyond the local machine. | `run_local.py`, `mock_api/` | Both bind to `127.0.0.1` by default. External binding requires an explicit opt-in (`PROCUREAI_ALLOW_EXTERNAL=1`). | Fixed |

## Data quality

| Finding | Handling |
|---|---|
| `software_catalog.csv` `status` is free text. `SW009` (NeuralDesk Business) reads `Approved - limited use`, so a plain equality check would treat it as unrestricted. | The policy engine and the catalog tool match the limited-use wording explicitly, and never collapse it to `Approved`. The data is unchanged. |
| `vendors.csv` and `vendor_risk.json` disagree on SignalWatch (registry says Approved, live review is 2025-07-01). | Both sources are shown. `conflicting_vendor_evidence` is raised and the case routes to manual review. Neither source is chosen silently. |
| The `NimbusAI` entry in `vendor_risk.json` has only error fields, with none of the normal ones. | Code treats the entry as a service error, not as data. The result is `vendor_risk_unavailable`, never favourable. |
| `department_budgets.csv` is a static snapshot. | The reference date is fixed at 2026-09-30, and the snapshot is used as given. This is documented in the assumptions. |
| `purchase_history.csv` contains only approved purchases. | Documented as a limit of what the history can show. It is not treated as a defect. |

No duplicate keys, orphaned references, or arithmetic inconsistencies were found. The integrity tests in `tests/` check this.

## Security

- **Secrets:** none in the starter pack. The repository scanner (`scripts/preflight_secrets.py`) runs in CI and checks for key-shaped strings.
- **Mock service:** it has no authentication. It is local-only, and that is documented.
- **Injection exposure:** request text such as `REQ-1006.business_justification` contains instructions. The policy engine never reads free text, so injected text cannot change a policy field. A deterministic visibility flag, `prompt_injection_detected`, is raised for instruction-shaped text. It is a signal, not a complete defense.

## Verification

- The full test suite runs from a clean clone with no keys set.
- The docs checker and the secrets scanner run in CI.
- The one-command start (`python run_local.py`) starts the mock service and the UI, both on loopback.
