"""ProcureAI -- AI Procurement Request Copilot product UI.

Extends the starter Streamlit shell rather than replacing it. This file is a
pure rendering layer: every approval, risk flag, missing-information item,
and policy-check result comes from `src/ui/view_model.py`'s
`ProcurementView`, which is itself built entirely from `ProcurementDecision`
and `PolicyEvaluation` -- no procurement rule is decided here.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.agent.single_agent import run_single_agent_with_trace
from src.agent.staged_agent import run_staged_agent_with_trace
from src.ui.view_model import ProcurementView, build_procurement_view

ROOT = Path(__file__).resolve().parent
REQUESTS = json.loads((ROOT / "data" / "requests.json").read_text(encoding="utf-8"))
BY_ID = {r["request_id"]: r for r in REQUESTS}

st.set_page_config(page_title="ProcureAI - Procurement Request Copilot", layout="wide")

if "results" not in st.session_state:
    st.session_state.results = {}  # (request_id, architecture) -> ProcurementView | error dict


# ---------------------------------------------------------------------------
# Sidebar: request selector
# ---------------------------------------------------------------------------

st.sidebar.title("ProcureAI")
st.sidebar.caption("AI Procurement Request Copilot")

request_id = st.sidebar.selectbox(
    "Request",
    list(BY_ID.keys()),
    format_func=lambda rid: f"{rid} - {BY_ID[rid]['product_name']}",
)
architecture = st.sidebar.radio("Architecture", ["single", "staged"], horizontal=True)

st.sidebar.divider()
st.sidebar.caption("Requests in this session")
for rid, req in BY_ID.items():
    cached = st.session_state.results.get((rid, "single"))
    badge = ""
    if isinstance(cached, ProcurementView):
        badge = f" -- {cached.list_status_badge}"
    elif isinstance(cached, dict):
        badge = " -- ERROR"
    marker = "▶" if rid == request_id else " "
    st.sidebar.text(f"{marker} {rid} {req['product_name'][:22]}{badge}")

selected_request = BY_ID[request_id]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("ProcureAI")
st.caption("AI Procurement Request Copilot")

cache_key = (request_id, architecture)

# The button widget must be created (and its click read) before the status
# metric below is computed, so a click updates session_state in this same
# script run and the header reflects the fresh result immediately -- not one
# rerun later.
header_cols = st.columns([1, 1, 1, 2])
with header_cols[3]:
    st.write("")
    run_clicked = st.button("Run analysis", type="primary", use_container_width=True)

if run_clicked:
    runner = run_staged_agent_with_trace if architecture == "staged" else run_single_agent_with_trace
    spinner_text = (
        "Analyst gathering evidence, reviewer synthesizing..." if architecture == "staged" else "Gathering evidence and evaluating policy..."
    )
    with st.spinner(spinner_text):
        try:
            result = runner(request_id)
            st.session_state.results[cache_key] = build_procurement_view(result)
        except KeyError as exc:
            st.session_state.results[cache_key] = {"kind": "invalid_request", "message": str(exc)}
        except Exception as exc:  # last-resort UI guard: never show a blank page
            st.session_state.results[cache_key] = {
                "kind": "unexpected_error",
                "message": f"{type(exc).__name__}: {exc}",
            }

result = st.session_state.results.get(cache_key)

header_cols[0].metric("Request", request_id)
header_cols[1].metric("Architecture", "Single agent" if architecture == "single" else "Staged (not yet available)")
status_text = "Not yet analyzed"
if isinstance(result, ProcurementView):
    status_text = result.analysis_status
elif isinstance(result, dict):
    status_text = "Error"
header_cols[2].metric("Analysis status", status_text)

st.divider()

# ---------------------------------------------------------------------------
# Request details (always shown -- these are just the raw submitted fields)
# ---------------------------------------------------------------------------

left, right = st.columns([1, 1.3], gap="large")

with left:
    st.subheader("Request details")
    if isinstance(result, ProcurementView):
        for field in result.request_details:
            if field.is_missing:
                st.markdown(f"**{field.label}:** :orange[{field.value}]")
            else:
                st.markdown(f"**{field.label}:** {field.value}")
    else:
        # nothing analyzed yet -- still show the raw request, never a blank page
        r = selected_request
        cost = r.get("annual_cost_usd")
        raw_fields = [
            ("Requester", r.get("requester_id")),
            ("Product", r.get("product_name")),
            ("Vendor", r.get("vendor_name")),
            ("Category", r.get("category")),
            ("Annual cost", f"${cost:,.2f}" if cost is not None else None),
            ("Users/licenses", r.get("user_count")),
            ("Data-access level", r.get("data_access_level")),
            ("Requested integrations", r.get("requested_integrations")),
            ("Urgency", r.get("urgency")),
            ("Business justification", r.get("business_justification")),
        ]
        for label, value in raw_fields:
            if value is None or value == "":
                st.markdown(f"**{label}:** :orange[Not provided]")
            else:
                st.markdown(f"**{label}:** {value}")
        st.caption("Click **Run analysis** to gather evidence and evaluate policy for this request.")

# ---------------------------------------------------------------------------
# Right column: status-dependent content
# ---------------------------------------------------------------------------

with right:
    if result is None:
        st.subheader("Copilot recommendation")
        st.info("No analysis has been run for this request yet.")

    elif isinstance(result, dict) and result.get("kind") == "not_implemented":
        st.subheader("Copilot recommendation")
        st.warning(result["message"])

    elif isinstance(result, dict) and result.get("kind") == "invalid_request":
        st.subheader("Copilot recommendation")
        st.error(f"Invalid request. Reason: {result['message']}. No procurement action was taken.")

    elif isinstance(result, dict) and result.get("kind") == "unexpected_error":
        st.subheader("Copilot recommendation")
        st.error(
            f"Something went wrong while analyzing this request. Reason: {result['message']}. "
            "No procurement action was taken. Next step: manual review."
        )

    elif isinstance(result, ProcurementView):
        view: ProcurementView = result

        if view.error_banner:
            st.error(view.error_banner)

        st.subheader("Recommendation")
        st.markdown(f"### {view.recommendation}")
        if view.rationale:
            with st.expander("Why?", expanded=True):
                st.write(view.rationale)
        st.markdown(f"**Next step:** {view.next_step}")

        approvals_col, flags_col = st.columns(2)
        with approvals_col:
            st.markdown("**Approvals required**")
            if view.required_approvals:
                for approval in view.required_approvals:
                    st.markdown(f"- ✓ {approval}")
            else:
                st.markdown("_None determined_")
        with flags_col:
            st.markdown("**Risk flags**")
            if view.risk_flags:
                for flag in view.risk_flags:
                    st.markdown(f"- ⚠ {flag.label}  \n  `{flag.raw}`")
            else:
                st.markdown("_None_")

        if view.missing_information:
            st.warning(
                "**Missing information**\n\n"
                + "\n".join(f"- ⚠ {m}" for m in view.missing_information)
                + "\n\nProcurement cannot proceed until this information is collected."
            )

# ---------------------------------------------------------------------------
# Evidence panel, policy checks, human handoff -- full width, below the fold
# ---------------------------------------------------------------------------

if isinstance(result, ProcurementView):
    view = result
    st.divider()

    ev_col, policy_col = st.columns([1.2, 1], gap="large")

    with ev_col:
        st.subheader("Evidence")
        if not view.evidence:
            st.caption("No evidence was retrieved for this request.")
        for item in view.evidence:
            with st.container(border=True):
                st.markdown(f"**{item.evidence_id}** &nbsp;·&nbsp; _{item.source}_")
                st.write(item.finding)
                if item.reference:
                    st.caption(f"Reference: `{item.reference}`")

    with policy_col:
        st.subheader("Policy checks")
        if not view.policy_checks:
            st.caption("No policy checks recorded.")
        status_icon = {"ok": "✅", "flagged": "🔶", "skipped": "⬜"}
        for check in view.policy_checks:
            icon = status_icon.get(check.status_kind, "•")
            st.markdown(f"{icon} **{check.rule_id}** — {check.status_label}")
            st.caption(check.detail)

    st.divider()

    # -- Human handoff --------------------------------------------------
    st.subheader("Human review required")
    with st.container(border=True):
        st.markdown("**Reason**")
        for line in view.human_handoff.reason_lines:
            st.markdown(f"- {line}")
        st.markdown("**Required reviewers**")
        st.markdown(", ".join(view.human_handoff.required_reviewers) or "_None determined_")
        st.markdown(f"**AI action:** {view.human_handoff.ai_action_note}")

    st.markdown("**Handoff summary** _(copy and paste into your review tool)_")
    st.code(view.handoff_summary_text, language=None)

    # -- Audit trail (collapsed by default) ------------------------------
    with st.expander("Run details / audit trail"):
        st.markdown(f"**Architecture:** {view.telemetry.architecture}")
        tcol1, tcol2, tcol3 = st.columns(3)
        tcol1.metric("LLM calls", view.telemetry.llm_calls if view.telemetry.llm_calls is not None else "-")
        tcol2.metric("Tool calls", view.telemetry.tool_calls if view.telemetry.tool_calls is not None else "-")
        tcol3.metric(
            "Latency", f"{view.telemetry.latency_seconds:.1f}s" if view.telemetry.latency_seconds is not None else "-"
        )
        if view.telemetry.analyst_llm_calls is not None:
            st.caption(
                f"Analyst LLM calls: {view.telemetry.analyst_llm_calls}  ·  "
                f"Reviewer LLM calls: {view.telemetry.reviewer_llm_calls}"
            )

        st.markdown("**Tool calls**")
        if view.tool_calls:
            for call in view.tool_calls:
                status = "✅" if call.success else "❌"
                st.markdown(f"{status} `{call.tool_name}` -- {call.summary}")
        else:
            st.caption("No tools were called.")

        st.markdown("**Audit timeline**")
        stage_icon = {"done": "✅", "skipped": "⬜", "failed": "❌"}
        st.markdown(" → ".join(f"{stage_icon.get(s.status, '•')} {s.label}" for s in view.audit_timeline))

st.divider()
st.caption("Important: recommendations are advisory. Human approval remains required for purchasing decisions.")
