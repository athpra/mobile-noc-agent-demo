"""
Mobile NOC Agent: Streamlit front end.

Top: network health at a glance. Left: the investigation, with a progress
strip, every tool call the agent made, and the approval card when it
proposes a change. Right: a clickable sector map coloured by handover
success, the selected cell's KPI trend, alarms, audit log and (in presenter
mode) the answer. Launched in Cloudera AI Workbench by launch_app.py.
"""

from __future__ import annotations

import json
import os
import uuid
from html import escape

import pandas as pd
import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from src.agent import build_agent, open_checkpointer, pending_interrupts, run_config, strip_reasoning
from src.config import TokenUnavailableError, load_settings
from src.context import DemoContext
from src.llm import build_chat_model
from src.network.scenarios import DEFAULT_SCENARIO, SCENARIOS, SERVING_CELL
from src.ui import charts, style

st.set_page_config(page_title="Mobile NOC Agent", page_icon=":material/cell_tower:", layout="wide")
style.inject_css()

SAMPLE_QUESTIONS = [
    "Handover success on GNB1042-C1 dropped this morning. Why?",
    "Which cells have degraded KPIs in the last hour?",
    "Is any active alarm affecting customers right now?",
]

# Shown instead of SAMPLE_QUESTIONS once the incident is resolved.
FOLLOW_UP_QUESTIONS = [
    "Write the ticket note for this incident.",
    "Are any cells below target right now?",
    "Check the PCIs within two hops of SC1188-C1 for any remaining conflicts.",
]

TOOL_ICONS = {
    "get_network_summary": ":material/lan:",
    "get_alarms": ":material/notifications_active:",
    "get_kpis": ":material/monitoring:",
    "get_ho_relations": ":material/swap_horiz:",
    "get_neighbors": ":material/hub:",
    "get_cell_config": ":material/tune:",
    "get_cm_changes": ":material/history:",
    "run_python": ":material/terminal:",
    "propose_cm_change": ":material/edit_note:",
}

# Investigation stages and the tools that show each one has happened.
STAGES = [
    ("Triage", {"get_network_summary", "get_alarms", "get_kpis"}),
    ("Evidence", {"get_ho_relations", "get_neighbors", "get_cell_config"}),
    ("Analysis", {"run_python"}),
    ("History", {"get_cm_changes"}),
    ("Proposal", {"propose_cm_change"}),
]


@st.cache_resource
def checkpointer():
    return open_checkpointer()


settings = load_settings()


def new_session() -> None:
    sid = uuid.uuid4().hex[:8]
    st.session_state.thread_id = f"noc-{sid}"
    st.session_state.ctx = DemoContext.create(settings, sid)
    st.session_state.last_error = None
    st.session_state.cell = SERVING_CELL
    st.session_state.last_pick = None


if "ctx" not in st.session_state:
    new_session()
ctx: DemoContext = st.session_state.ctx
cfg = run_config(st.session_state.thread_id)


def get_agent():
    """Returns (agent, setup_error). Built per rerun so the model client
    always carries the current workload token."""
    if not settings.llm_configured:
        return None, "Set CAII_BASE_URL and CAII_MODEL_NAME to connect a model endpoint."
    try:
        return build_agent(ctx, build_chat_model(settings), checkpointer()), None
    except TokenUnavailableError as exc:
        return None, str(exc)


def approver_name() -> str:
    try:
        headers = st.context.headers
        for key in ("Remote-User", "X-Forwarded-User", "X-Auth-Request-User"):
            if headers.get(key):
                return headers[key]
    except AttributeError:
        pass
    return os.environ.get("HADOOP_USER_NAME") or "operator"


def text_of(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content or ""


def short_args(args: dict) -> str:
    shown = {k: v for k, v in args.items() if k not in ("code", "reason")}
    return ", ".join(f"{k}={v!r}" for k, v in shown.items())


def step_label(msg) -> str | None:
    if isinstance(msg, AIMessage):
        if msg.tool_calls:
            return " · ".join(f"Calling `{tc['name']}({short_args(tc['args'])})`" for tc in msg.tool_calls)
        if strip_reasoning(text_of(msg.content)):
            return "Writing the answer"
    if isinstance(msg, ToolMessage):
        return f"`{msg.name}` returned {len(text_of(msg.content))} characters"
    return None


def run(agent, payload, history: list, progress_slot, hide_while_running=None) -> None:
    """Streams one agent run, redrawing the progress strip as each message arrives."""
    st.session_state.last_error = None
    if hide_while_running is not None:
        hide_while_running.empty()
    live = list(history)
    with st.status("Agent working", expanded=True) as status:
        try:
            for update in agent.stream(payload, cfg, stream_mode="updates"):
                for node, data in update.items():
                    if node == "__interrupt__" or not isinstance(data, dict):
                        continue
                    for msg in data.get("messages", []):
                        live.append(msg)
                        label = step_label(msg)
                        if label:
                            status.write(label)
                    style.progress(investigation_steps(live, False), progress_slot)
            status.update(label="Done", state="complete", expanded=False)
        except GraphRecursionError:
            st.session_state.last_error = "The agent used too many steps without finishing. Ask a narrower question."
        except Exception as exc:  # noqa: BLE001 - endpoint/auth errors belong in the UI
            st.session_state.last_error = f"{type(exc).__name__}: {exc}"
    st.rerun()


def investigation_steps(messages: list, waiting_for_approval: bool) -> list[tuple[str, str]]:
    """Progress strip states, derived from the tools the agent has called."""
    calls = [tc["name"] for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls]
    called = set(calls)
    steps = [(label, "done" if called & tools else "todo") for label, tools in STAGES]

    decision = next((text_of(m.content) for m in reversed(messages)
                     if isinstance(m, ToolMessage) and m.name == "propose_cm_change"
                     and text_of(m.content).startswith(("APPLIED", "The engineer REJECTED"))), "")
    if waiting_for_approval:
        steps[-1] = ("Proposal", "done")
        steps.append(("Awaiting", "active"))
    elif decision.startswith("APPLIED"):
        steps.append(("Approved", "done"))
    elif decision:
        steps.append(("Rejected", "stopped"))
    else:
        steps.append(("Approval", "todo"))

    applied_at = max((i for i, m in enumerate(messages) if isinstance(m, ToolMessage)
                      and m.name == "propose_cm_change" and text_of(m.content).startswith("APPLIED")), default=None)
    verified = applied_at is not None and any(
        isinstance(m, AIMessage) and any(tc["name"] == "get_kpis" for tc in m.tool_calls)
        for m in messages[applied_at:])
    steps.append(("Verified", "done" if verified else "todo"))
    return steps


def render_tool_call(tc: dict, result: ToolMessage | None) -> None:
    label = f"{tc['name']}({short_args(tc['args'])})"
    pending = result is None
    with st.expander(label, expanded=False, icon=TOOL_ICONS.get(tc["name"], ":material/build:")):
        if tc["name"] == "run_python":
            st.caption(f"Sandbox: {ctx.sandbox.name} · datasets: {', '.join(tc['args'].get('datasets') or []) or 'none'}")
            st.code(tc["args"].get("code", ""), language="python")
        if pending:
            st.caption("Waiting for the engineer's decision.")
            return
        out = text_of(result.content)
        if tc["name"] == "run_python" or out.lstrip().startswith("{"):
            st.code(out, language="text")
        else:
            st.markdown(out)


def render_empty_answer(m: AIMessage, raw: str) -> None:
    """A reply with no visible answer: say why instead of showing nothing."""
    if (m.response_metadata or {}).get("finish_reason") == "length":
        why = (f"The model ran out of tokens (LLM_MAX_TOKENS={settings.llm_max_tokens}) before it answered. "
               "Raise LLM_MAX_TOKENS or ask a narrower question.")
    elif raw.strip():
        why = "The model only reasoned and gave no answer. Ask again or rephrase the question."
    else:
        why = "The model returned an empty reply. Ask again or rephrase the question."
    with st.chat_message("assistant", avatar=":material/support_agent:"):
        st.warning(why, icon=":material/report:")
        if raw.strip():
            with st.expander("Model reasoning", icon=":material/psychology:"):
                st.text(raw[-6000:])


def render_transcript(messages: list) -> None:
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    for m in messages:
        if isinstance(m, HumanMessage):
            with st.chat_message("user", avatar=":material/person:"):
                st.markdown(text_of(m.content))
        elif isinstance(m, AIMessage):
            raw = text_of(m.content)
            text = strip_reasoning(raw)
            if not text and not m.tool_calls:
                render_empty_answer(m, raw)
                continue
            with st.chat_message("assistant", avatar=":material/support_agent:"):
                if text:
                    st.markdown(text)
                for tc in m.tool_calls:
                    render_tool_call(tc, results.get(tc["id"]))


def render_approval(intr) -> dict | None:
    """Approval card. Returns the engineer's decision once they click."""
    p = intr.value
    key = f"{p['cell_id']}-{p['attribute']}-{p['proposed_value']}-{p['network_time']}"
    style.approval_summary(p)
    with st.expander("Configuration diff", expanded=True, icon=":material/difference:"):
        st.code(p["diff"], language="diff")
    comment = st.text_input("Comment (optional)", key=f"comment-{key}", placeholder="e.g. CR-4471, checked with RF planning")
    approve, reject = st.columns(2)
    if approve.button("Approve and apply", type="primary", key=f"approve-{key}", width="stretch",
                      icon=":material/check_circle:"):
        return {"approved": True, "comment": comment, "approver": approver_name()}
    if reject.button("Reject", key=f"reject-{key}", width="stretch", icon=":material/cancel:"):
        return {"approved": False, "comment": comment, "approver": approver_name()}
    return None


def render_resolution() -> None:
    """Closing card once the fix is verified: what changed, who approved it, the effect."""
    approved = [e for e in ctx.audit.entries if e.get("kind") == "cm_change" and e.get("decision") == "approved"]
    if not approved:
        return
    last = approved[-1]
    kpis = ctx.oss.get_kpis(SERVING_CELL)
    before = [r for r in kpis if r["rop_start"] < last["network_time"]]
    effect = (f"HO success on {SERVING_CELL}: {before[-1]['ho_sr_pct']:.1f}% → {kpis[-1]['ho_sr_pct']:.1f}%"
              if before else "")
    style.resolution(
        f"{last['cell_id']} {last['attribute']} {last['old']} → {last['new']}",
        f"approved by {last.get('approver', 'operator')} at {last['network_time']}",
        effect,
    )


def change_events(cell: str, presenter: bool) -> list[dict]:
    """CM changes on this cell or its neighbours, for markers on the KPI chart.
    Outside presenter mode only the agent's own changes are marked, so the
    chart doesn't give the root cause away."""
    nearby = {cell, *ctx.oss.net.neighbors(cell, ctx.oss.now)}
    events = []
    for c in ctx.oss.get_cm_changes():
        if c["cell_id"] not in nearby or not (presenter or str(c["source"]).startswith("noc-agent")):
            continue
        if c["change"] == "cell created":
            short = full = f"{c['cell_id']} created"
        else:
            short = f"{c['change']} {c['old_value']}→{c['new_value']}"
            full = f"{c['cell_id']} {short}"
        events.append({"time": c["time"], "short": short, "label": full})
    return events


# Changes smaller than this (percentage points) are ROP-to-ROP noise, so the
# metric tiles show them in grey instead of red or green.
NOISE_PTS = {"ho_sr_pct": 1.0, "drop_rate_pct": 0.1}


def vs_night(latest, night: pd.DataFrame, col: str, noise: float, color: str, decimals: int):
    """Delta text and colour for a metric tile, against the pre-fault night average."""
    if night.empty:
        return None, "off"
    diff = latest[col] - night[col].mean()
    return f"{diff:+.{decimals}f}", ("off" if abs(diff) < noise else color)


def picked_on_map() -> str | None:
    state = st.session_state.get("network_map")
    try:
        rows = state["selection"][charts.PICK]
    except (KeyError, TypeError):
        return None
    return rows[0].get("cell_id") if rows else None


# --- state ------------------------------------------------------------------

agent, setup_error = get_agent()
messages, interrupts = [], []
if agent is not None:
    snap = agent.get_state(cfg)
    messages = snap.values.get("messages", []) if snap.values else []
    interrupts = pending_interrupts(agent, cfg)

health = charts.cell_health(ctx.oss)
unhealthy = health[health["status"].isin(["Degraded", "Critical"])]
steps = investigation_steps(messages, bool(interrupts))
# Resolved: a change was approved, the agent re-checked the KPIs, and every cell is back on target.
resolved = ctx.changes_applied > 0 and steps[-1][1] == "done" and unhealthy.empty

# A run starts at the end of the script, after the network panels are drawn,
# so the map and KPIs stay on screen while the agent works.
pending_run = None

# --- sidebar -------------------------------------------------------------

with st.sidebar:
    st.markdown("#### :material/science: Scenario")
    with st.container(border=True):
        st.markdown(f"**{SCENARIOS[DEFAULT_SCENARIO].title}**")
        st.caption("Synthetic lab: 12 gNBs, 36 macro cells and one small cell. No real network is connected.")
    presenter = st.toggle("Presenter mode", key="presenter", help="Reveals the root cause on the map, the KPI chart and a Presenter tab.")
    if st.button("Reset scenario", width="stretch", icon=":material/restart_alt:"):
        new_session()
        st.rerun()

    st.markdown("#### :material/chat: " + ("Follow up" if resolved else "Try asking"))
    for q in FOLLOW_UP_QUESTIONS if resolved else SAMPLE_QUESTIONS:
        if st.button(q, width="stretch", disabled=agent is None or bool(interrupts)):
            st.session_state.queued_question = q
            st.rerun()

    st.markdown("#### :material/shield: Sandbox")
    if ctx.sandbox.isolated:
        st.caption(f"`{ctx.sandbox.name}`: isolated microVM per call.")
    else:
        st.caption(f"`{ctx.sandbox.name}`: subprocess with CPU and memory limits. Not a security boundary; "
                   "set E2B_API_KEY for an isolated sandbox.")

# --- header and network health ---------------------------------------------

style.header(ctx.network_time, f"{ctx.oss.day_start:%d %b %Y}", settings.caii_model_name,
             ctx.sandbox.name, live=agent is not None)

active_alarms = ctx.oss.get_alarms(active_only=True)
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Cells in service", len(health), border=True)
m2.metric("Network HO success", f"{health['ho_sr_pct'].mean():.1f}%", border=True,
          help="Mean across cells, latest complete 15-minute ROP")
m3.metric("Cells below target", len(unhealthy), border=True,
          help=f"Handover success under {charts.HO_TARGET_PCT:.0f}% in the latest ROP: "
               + (", ".join(unhealthy["cell_id"]) or "none"))
m4.metric("Active alarms", len(active_alarms), border=True)
m5.metric("Changes by agent", ctx.changes_applied, border=True,
          help="Configuration changes applied after an engineer approved them")

chat_col, side_col = st.columns([11, 9], gap="large")

# --- investigation ---------------------------------------------------------

with chat_col:
    style.section("Investigation", f"thread {st.session_state.thread_id}")
    progress_slot = st.empty()
    style.progress(steps, progress_slot)
    if setup_error:
        st.warning(f"Model endpoint not ready. {setup_error}", icon=":material/link_off:")

    intro_slot = st.empty()
    if not messages:
        with intro_slot:
            style.empty_state("Ask the agent about the network",
                              "Pick a question on the left or type one below. The agent gathers evidence, "
                              "analyses it in a sandbox and proposes a fix for you to approve.")
    render_transcript(messages)

    if st.session_state.last_error:
        st.error(st.session_state.last_error, icon=":material/error:")

    for intr in interrupts[:1]:
        decision = render_approval(intr)
        if decision is not None:
            pending_run = (Command(resume=decision), None)

    if resolved:
        render_resolution()

    run_area = st.container()
    queued = st.session_state.pop("queued_question", None)
    typed = st.chat_input(
        "Approve or reject the change first" if interrupts
        else "Ask a follow-up question" if resolved else "Ask the NOC agent",
        disabled=agent is None or bool(interrupts),
    )
    question = typed or queued
    if question and agent is not None and not interrupts:
        pending_run = ({"messages": [{"role": "user", "content": question}]}, question)

# --- network panels --------------------------------------------------------

with side_col:
    tab_names = ["Network", "Alarms", f"Audit ({len(ctx.audit.entries)})"] + (["Presenter"] if presenter else [])
    tabs = st.tabs(tab_names)

    with tabs[0]:
        picked = picked_on_map()
        if picked and picked != st.session_state.last_pick:
            st.session_state.last_pick = picked
            st.session_state.cell = picked

        style.section("Radio network", "click a sector to inspect it")
        st.altair_chart(
            charts.network_map(health, st.session_state.cell, ctx.oss.pci_conflicts() if presenter else None),
            on_select="rerun", selection_mode=charts.PICK, key="network_map", width="stretch", theme=None,
        )

        cells = sorted(health["cell_id"])
        cell = st.selectbox("Cell", cells, key="cell")
        kpis = pd.DataFrame(ctx.oss.get_kpis(cell))
        if not kpis.empty:
            latest = kpis.iloc[-1]
            night = kpis[kpis["rop_start"] < "07:00"]
            recent = kpis.tail(24)
            ho_delta, ho_color = vs_night(latest, night, "ho_sr_pct", NOISE_PTS["ho_sr_pct"], "normal", 1)
            drop_delta, drop_color = vs_night(latest, night, "drop_rate_pct", NOISE_PTS["drop_rate_pct"], "inverse", 2)
            k1, k2, k3 = st.columns(3)
            k1.metric("HO success", f"{latest['ho_sr_pct']:.1f}%", ho_delta, delta_color=ho_color,
                      chart_data=recent["ho_sr_pct"], chart_type="line", border=True)
            k2.metric("Drop rate", f"{latest['drop_rate_pct']:.2f}%", drop_delta, delta_color=drop_color,
                      chart_data=recent["drop_rate_pct"], chart_type="line", border=True)
            k3.metric("PRB util DL", f"{latest['prb_util_dl_pct']:.0f}%", delta_color="off",
                      chart_data=recent["prb_util_dl_pct"], chart_type="area", border=True)
            st.caption("Change in percentage points vs the 00:00-07:00 average, before the fault. "
                       "Grey means within normal ROP-to-ROP variation.")

            style.section(f"Handover success · {cell}", f"15-min ROPs · latest {latest['rop_start']}")
            st.altair_chart(charts.kpi_trend(kpis, ctx.oss.day_start, change_events(cell, presenter)),
                            width="stretch", theme=None)

    with tabs[1]:
        style.section("Fault management", f"{len(active_alarms)} active")
        style.alarm_list(ctx.oss.get_alarms())

    with tabs[2]:
        style.section("Audit log", "every tool call and change decision")
        if ctx.audit.entries:
            lines = []
            for e in reversed(ctx.audit.entries[-40:]):
                what = e.get("tool") or f"{e['kind']}: {e.get('decision')}"
                args = json.dumps(e.get("args", ""), default=str)
                lines.append(f"{escape(e['network_time'])} <b>{escape(what)}</b> {escape(args[:160])}")
            style.html(f'<div class="noc-audit">{"<br>".join(lines)}</div>')
        else:
            style.empty_state("Nothing yet", "Tool calls and approvals appear here as the agent works.")
        st.download_button(
            "Download audit log (JSON lines)",
            "\n".join(json.dumps(e, default=str) for e in ctx.audit.entries),
            file_name=f"audit-{st.session_state.thread_id}.jsonl",
            width="stretch", icon=":material/download:",
        )

    if presenter:
        with tabs[3]:
            style.section("Root cause", "hidden from the agent")
            st.markdown(SCENARIOS[DEFAULT_SCENARIO].summary)
            conflicts = ctx.oss.pci_conflicts()
            if conflicts:
                for cid, issues in conflicts.items():
                    for i in issues:
                        st.markdown(f":red-badge[PCI {i['type']}] seen from **{cid}**: PCI {i['pci']} on {', '.join(i['cells'])}")
            else:
                st.markdown(":green-badge[No PCI conflicts] in the network.")
            style.section("Configuration changes today")
            changes = pd.DataFrame(ctx.oss.get_cm_changes()).astype(str)  # values mix ints and text
            st.dataframe(changes, hide_index=True, width="stretch")

# --- agent run ---------------------------------------------------------------

if pending_run is not None:
    payload, question = pending_run
    with run_area:
        if question:
            with st.chat_message("user", avatar=":material/person:"):
                st.markdown(question)
        run(agent, payload, messages, progress_slot, intro_slot)
