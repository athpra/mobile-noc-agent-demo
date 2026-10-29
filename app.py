"""
Mobile NOC Agent: Streamlit front end.

Left: the conversation with the agent, every tool call it made, and the
approval card when it proposes a change. Right: the cell KPIs the audience
can watch drop and recover, active alarms, a presenter view and the audit
log. Launched in Cloudera AI Workbench by launch_app.py.
"""

from __future__ import annotations

import json
import os
import uuid

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

st.set_page_config(page_title="Mobile NOC Agent", layout="wide")

SAMPLE_QUESTIONS = [
    "Handover success on GNB1042-C1 dropped this morning. Why?",
    "Which cells have degraded KPIs in the last hour?",
    "Is any active alarm affecting customers right now?",
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
    shown = {k: v for k, v in args.items() if k != "code"}
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


def run(agent, payload) -> None:
    st.session_state.last_error = None
    with st.status("Agent working", expanded=True) as status:
        try:
            for update in agent.stream(payload, cfg, stream_mode="updates"):
                for node, data in update.items():
                    if node == "__interrupt__" or not isinstance(data, dict):
                        continue
                    for msg in data.get("messages", []):
                        label = step_label(msg)
                        if label:
                            status.write(label)
            status.update(label="Done", state="complete", expanded=False)
        except GraphRecursionError:
            st.session_state.last_error = "The agent used too many steps without finishing. Ask a narrower question."
        except Exception as exc:  # noqa: BLE001 - endpoint/auth errors belong in the UI
            st.session_state.last_error = f"{type(exc).__name__}: {exc}"
    st.rerun()


def render_tool_call(tc: dict, result: ToolMessage | None) -> None:
    label = f"{tc['name']}({short_args(tc['args'])})"
    with st.expander(label, expanded=False):
        if tc["name"] == "run_python":
            st.caption(f"Sandbox: {ctx.sandbox.name} · datasets: {', '.join(tc['args'].get('datasets') or []) or 'none'}")
            st.code(tc["args"].get("code", ""), language="python")
        if result is None:
            st.caption("Waiting for the engineer's decision.")
            return
        out = text_of(result.content)
        if tc["name"] == "run_python" or out.lstrip().startswith("{"):
            st.code(out, language="text")
        else:
            st.markdown(out)


def render_transcript(messages: list) -> None:
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    for m in messages:
        if isinstance(m, HumanMessage):
            with st.chat_message("user"):
                st.markdown(text_of(m.content))
        elif isinstance(m, AIMessage):
            text = strip_reasoning(text_of(m.content))
            if not text and not m.tool_calls:
                continue
            with st.chat_message("assistant"):
                if text:
                    st.markdown(text)
                for tc in m.tool_calls:
                    render_tool_call(tc, results.get(tc["id"]))


STATUS_STYLE = {"pass": ":green[PASS]", "warn": ":orange[WARN]", "fail": ":red[FAIL]"}


def render_approval(agent, intr) -> None:
    p = intr.value
    key = f"{p['cell_id']}-{p['attribute']}-{p['proposed_value']}-{p['network_time']}"
    with st.container(border=True):
        st.markdown(f"#### Approval needed: {p['cell_id']}")
        st.markdown(f"Change `{p['attribute']}` from **{p['current_value']}** to **{p['proposed_value']}**")
        st.caption(p["managed_object"])
        st.markdown(f"**Agent's reason.** {p['reason']}")
        for c in p["checks"]:
            st.markdown(f"{STATUS_STYLE.get(c['status'], c['status'])} **{c['name']}**: {c['detail']}")
        st.code(p["diff"], language="diff")
        comment = st.text_input("Comment (optional)", key=f"comment-{key}")
        approve, reject = st.columns(2)
        if approve.button("Approve and apply", type="primary", key=f"approve-{key}", width="stretch"):
            run(agent, Command(resume={"approved": True, "comment": comment, "approver": approver_name()}))
        if reject.button("Reject", key=f"reject-{key}", width="stretch"):
            run(agent, Command(resume={"approved": False, "comment": comment, "approver": approver_name()}))


# --- sidebar -------------------------------------------------------------

agent, setup_error = get_agent()

with st.sidebar:
    st.markdown("### Mobile NOC Agent")
    st.caption("Synthetic lab. No real network is connected.")
    st.markdown(f"**Scenario.** {SCENARIOS[DEFAULT_SCENARIO].title}")
    st.markdown(f"**Model.** `{settings.caii_model_name or 'not set'}`")
    if ctx.sandbox.isolated:
        st.markdown(f"**Sandbox.** `{ctx.sandbox.name}` (isolated)")
    else:
        st.markdown(f"**Sandbox.** `{ctx.sandbox.name}`")
        st.caption("Local subprocess: not a security boundary. Fine for synthetic data; "
                   "set E2B_API_KEY for an isolated sandbox.")
    if st.button("Reset scenario", width="stretch"):
        new_session()
        st.rerun()
    st.divider()
    st.markdown("**Try asking**")
    for q in SAMPLE_QUESTIONS:
        if st.button(q, width="stretch", disabled=agent is None):
            st.session_state.queued_question = q
            st.rerun()

# --- main ------------------------------------------------------------------

st.markdown("## Mobile NOC Agent")
st.caption(f"Network time {ctx.network_time} · {ctx.oss.day_start:%d %b %Y} · 5G SA, band n78 · "
           f"{len(ctx.oss.net.cells_at(ctx.oss.now))} cells")

chat_col, side_col = st.columns([3, 2], gap="large")

with chat_col:
    if setup_error:
        st.warning(f"Model endpoint not ready. {setup_error}")
    messages, interrupts = [], []
    if agent is not None:
        snap = agent.get_state(cfg)
        messages = snap.values.get("messages", []) if snap.values else []
        interrupts = pending_interrupts(agent, cfg)

    if not messages:
        st.info("Ask about the network, or pick a question on the left. "
                "The agent will gather evidence, analyse it and propose a fix for you to approve.")
    render_transcript(messages)

    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    for intr in interrupts[:1]:
        render_approval(agent, intr)

    queued = st.session_state.pop("queued_question", None)
    typed = st.chat_input(
        "Approve or reject the change first" if interrupts else "Ask the NOC agent",
        disabled=agent is None or bool(interrupts),
    )
    question = typed or queued
    if question and agent is not None and not interrupts:
        with st.chat_message("user"):
            st.markdown(question)
        run(agent, {"messages": [{"role": "user", "content": question}]})

with side_col:
    cells = ctx.oss.net.cells_at(ctx.oss.now)
    cell = st.selectbox("Cell", sorted(cells), index=sorted(cells).index(SERVING_CELL))
    kpis = pd.DataFrame(ctx.oss.get_kpis(cell))
    if not kpis.empty:
        latest = kpis.iloc[-1]
        night = kpis.loc[kpis["rop_start"] < "07:00", "ho_sr_pct"]
        m1, m2, m3 = st.columns(3)
        m1.metric("HO success", f"{latest['ho_sr_pct']:.1f}%",
                  f"{latest['ho_sr_pct'] - night.mean():+.1f} vs 00-07h" if not night.empty else None)
        m2.metric("Drop rate", f"{latest['drop_rate_pct']:.2f}%")
        m3.metric("PRB util DL", f"{latest['prb_util_dl_pct']:.0f}%")
        st.caption(f"Handover success rate (%) per 15-min ROP, latest ROP {latest['rop_start']}")
        st.line_chart(kpis.set_index("rop_start")[["ho_sr_pct"]], height=220)

    st.markdown("**Active alarms**")
    active = ctx.oss.get_alarms(active_only=True)
    if active:
        st.dataframe(pd.DataFrame(active)[["raised_at", "severity", "managed_object", "specific_problem"]],
                     hide_index=True, width="stretch")
    else:
        st.caption("None")

    with st.expander("Presenter view (shows the answer)"):
        st.markdown(SCENARIOS[DEFAULT_SCENARIO].summary)
        conflicts = ctx.oss.pci_conflicts()
        if conflicts:
            for cid, issues in conflicts.items():
                for i in issues:
                    st.markdown(f":red[PCI {i['type']}] seen from **{cid}**: PCI {i['pci']} on {', '.join(i['cells'])}")
        else:
            st.markdown(":green[No PCI conflicts in the network.]")
        st.markdown("**Configuration changes today**")
        changes = pd.DataFrame(ctx.oss.get_cm_changes()).astype(str)  # values mix ints and text
        st.dataframe(changes, hide_index=True, width="stretch")

    with st.expander(f"Audit log ({len(ctx.audit.entries)} entries)"):
        for e in reversed(ctx.audit.entries[-30:]):
            what = e.get("tool") or f"{e['kind']}: {e.get('decision')}"
            st.markdown(f"`{e['network_time']}` **{what}** {json.dumps(e.get('args', ''), default=str)}")
        st.download_button(
            "Download audit log (JSON lines)",
            "\n".join(json.dumps(e, default=str) for e in ctx.audit.entries),
            file_name=f"audit-{st.session_state.thread_id}.jsonl",
            width="stretch",
        )
