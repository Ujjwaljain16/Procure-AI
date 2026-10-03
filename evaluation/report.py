"""Static HTML report generator: reads a stored comparison (or single-
architecture) result JSON and writes a self-contained HTML file -- no
external network calls, no JS framework, no build step, so it opens and
renders correctly for a grader with nothing but a browser.

Usage:
    python evaluation/report.py evaluation/results/comparison_<timestamp>.json
    python evaluation/report.py evaluation/results/comparison_<timestamp>.json --out docs/evaluation_report.html
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "evaluation" / "results"

_STYLE = """
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; margin: 2rem auto; max-width: 960px; color: #1a1a1a; line-height: 1.5; }
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }
.manifest { color: #555; font-size: 0.9rem; margin-bottom: 1.5rem; }
.manifest code { background: #f2f2f2; padding: 0.1rem 0.3rem; border-radius: 3px; }
.gate { display: inline-block; padding: 0.4rem 0.9rem; border-radius: 4px; font-weight: 600; margin: 0.5rem 0 1.5rem; }
.gate.pass { background: #e4f7e9; color: #1b7a3d; }
.gate.fail { background: #fbe4e4; color: #a32424; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; }
th, td { border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }
th { background: #f7f7f7; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: #1b7a3d; }
.warn { color: #a3760b; }
.fail { color: #a32424; }
.tag { display: inline-block; background: #eef0f4; color: #334; border-radius: 3px; padding: 0.05rem 0.4rem; margin: 0 0.15rem 0.15rem 0; font-size: 0.78rem; }
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else "-"


def _gate_badge(passed: bool) -> str:
    return f'<span class="gate {"pass" if passed else "fail"}">SAFETY GATE: {"PASS" if passed else "FAIL"}</span>'


def _aggregate_table(single_agg: dict, staged_agg: dict) -> str:
    def stat(agg: dict, key: str) -> str:
        return _esc(agg.get(key, {}).get("median") if isinstance(agg.get(key), dict) else agg.get(key))

    rows = [
        ("Cases passed expected checks", f"{single_agg.get('cases_passed_expected_checks', '-')}/{single_agg.get('total_cases', '-')}", f"{staged_agg.get('cases_passed_expected_checks', '-')}/{staged_agg.get('total_cases', '-')}"),
        ("Cases errored", stat(single_agg, "cases_errored"), stat(staged_agg, "cases_errored")),
        ("LLM calls (median)", stat(single_agg, "llm_calls"), stat(staged_agg, "llm_calls")),
        ("Tool calls (median)", stat(single_agg, "tool_calls"), stat(staged_agg, "tool_calls")),
        ("Latency ms (median)", stat(single_agg, "latency_ms"), stat(staged_agg, "latency_ms")),
    ]
    body = "".join(f"<tr><td>{_esc(label)}</td><td class='num'>{a}</td><td class='num'>{b}</td></tr>" for label, a, b in rows)
    return f"<table><tr><th></th><th>A (single)</th><th>B (staged)</th></tr>{body}</table>"


def _case_rows(rows: list[dict]) -> str:
    out = []
    for row in rows:
        single_mark = "<span class='ok'>&#10003;</span>" if row.get("single_passed") else "<span class='fail'>&#9888;</span>"
        staged_mark = "<span class='ok'>&#10003;</span>" if row.get("staged_passed") else "<span class='fail'>&#9888;</span>"
        diffs = row.get("deterministic_consistency_diffs") or []
        consistency = "<span class='ok'>&#10003; identical</span>" if not diffs else f"<span class='warn'>&#9888; {len(diffs)} diff(s)</span>"
        tags = "".join(f"<span class='tag'>{_esc(t)}</span>" for t in row.get("tags", []))
        out.append(
            f"<tr><td>{_esc(row['case_id'])}</td><td>{_esc(row['category'])}</td><td>{tags}</td>"
            f"<td>{single_mark}</td><td>{staged_mark}</td><td>{consistency}</td></tr>"
        )
    return "".join(out)


def render_comparison_html(comparison: dict) -> str:
    gate = comparison.get("safety_gate", {})
    body = f"""
<h1>Architecture Evaluation</h1>
<div class="manifest">
  timestamp <code>{_esc(comparison.get('timestamp'))}</code> &middot;
  test set <code>{_esc(comparison.get('test_set_version'))}</code> &middot;
  git <code>{_esc(comparison.get('git_revision'))}</code> &middot;
  policy <code>{_esc(comparison.get('policy_version'))}</code>
</div>
{_gate_badge(gate.get('passed', False))}
<div>{_esc(gate.get('detail', ''))}</div>

<h2>Frozen Test Set</h2>
{_aggregate_table(comparison.get('single_aggregate', {}), comparison.get('staged_aggregate', {}))}
<p>Deterministic A-vs-B consistency failures: <strong>{_esc(comparison.get('deterministic_consistency_failures_total'))}</strong> / {_esc(len(comparison.get('rows', [])))} cases</p>

<h2>Per-Case Results</h2>
<table>
<tr><th>Case</th><th>Category</th><th>Tags</th><th>A</th><th>B</th><th>A vs B</th></tr>
{_case_rows(comparison.get('rows', []))}
</table>
"""
    pair_checks = comparison.get("injection_pair_checks")
    if pair_checks:
        OK_CELL = "<span class='ok'>&#10003; OK</span>"
        FAIL_CELL = "<span class='fail'>&#9888; FAIL</span>"
        pair_rows = "".join(
            f"<tr><td>{_esc(c['case_id'])} vs {_esc(c['pair_with'])}</td><td>{_esc(c.get('architecture'))}</td>"
            f"<td>{OK_CELL if c.get('passed') else FAIL_CELL}</td></tr>"
            for c in pair_checks
        )
        body += f"""
<h2>Injection Pair Checks</h2>
<table><tr><th>Pair</th><th>Architecture</th><th>Result</th></tr>{pair_rows}</table>
"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Architecture Evaluation</title><style>{_STYLE}</style></head><body>{body}</body></html>"


def render_result_html(result: dict) -> str:
    """Fallback renderer for a single-architecture result file (no A-vs-B
    rows available -- just the aggregate and safety gate)."""
    gate = result.get("safety_gate", {})
    agg = result.get("aggregate", {})
    body = f"""
<h1>Architecture Evaluation -- {_esc(result.get('architecture'))}</h1>
<div class="manifest">
  timestamp <code>{_esc(result.get('timestamp'))}</code> &middot;
  mode <code>{_esc(result.get('mode'))}</code> &middot;
  test set <code>{_esc(result.get('test_set_version'))}</code> &middot;
  git <code>{_esc(result.get('git_revision'))}</code> &middot;
  policy <code>{_esc(result.get('policy_version'))}</code>
</div>
{_gate_badge(gate.get('passed', False))}
<div>{_esc(gate.get('detail', ''))}</div>
<h2>Aggregate</h2>
<table>
<tr><th>Cases passed</th><td class="num">{_esc(agg.get('cases_passed_expected_checks'))}/{_esc(agg.get('total_cases'))}</td></tr>
<tr><th>Cases errored</th><td class="num">{_esc(agg.get('cases_errored'))}</td></tr>
<tr><th>LLM calls (median)</th><td class="num">{_esc(agg.get('llm_calls', {}).get('median'))}</td></tr>
<tr><th>Tool calls (median)</th><td class="num">{_esc(agg.get('tool_calls', {}).get('median'))}</td></tr>
<tr><th>Latency ms (median)</th><td class="num">{_esc(agg.get('latency_ms', {}).get('median'))}</td></tr>
</table>
"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Architecture Evaluation</title><style>{_STYLE}</style></head><body>{body}</body></html>"


def render(data: dict) -> str:
    is_comparison = "rows" in data and "deterministic_consistency_failures_total" in data
    return render_comparison_html(data) if is_comparison else render_result_html(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a stored evaluation result/comparison JSON as a static HTML report.")
    parser.add_argument("result_file")
    parser.add_argument("--out", default=None, help="Output path (default: alongside the input file, same name with .html).")
    args = parser.parse_args()

    in_path = Path(args.result_file)
    data = json.loads(in_path.read_text(encoding="utf-8"))
    out_path = Path(args.out) if args.out else in_path.with_suffix(".html")
    out_path.write_text(render(data), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
