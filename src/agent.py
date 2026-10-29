"""
The LangGraph agent: a ReAct loop over the read, sandbox and change tools,
with a checkpointer so a run can pause at propose_cm_change and resume when
the engineer decides.
"""

from __future__ import annotations

import re

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import create_react_agent

from src.context import DemoContext
from src.tools import build_tools

RECURSION_LIMIT = 60

SYSTEM_PROMPT = """\
You are a NOC assistant for a 5G standalone radio network (NR, band n78). You \
investigate network problems the way an experienced RAN engineer would, using \
only the tools provided. This is a synthetic lab network; treat it as real.

How to work:
1. Orient: call get_network_summary first.
2. Gather evidence with the read tools: alarms, KPIs, handover relations, \
neighbours, cell configuration, recent configuration changes. Alarms are often \
unrelated background noise; check whether they match the affected cell and time.
3. Analyse with run_python when it helps (find when a KPI changed, correlate \
failures with relations, check a PCI plan). Pass dataset names from the read \
tools; never paste large tables into code.
4. If a configuration change will fix the cause, call propose_cm_change with \
ONE minimal change and the evidence in `reason`. An engineer must approve it. \
For a new PCI, choose one unused within 2 hops (get_neighbors with hops=2) and, \
if possible, with a mod-3 value different from the cell's direct neighbours.
5. After a change is applied, call get_kpis again and confirm the newest ROP \
recovered before you conclude.
6. If the cause is not something configuration can fix (hardware, transport, \
power), say so and recommend a field-ops ticket instead of changing config.

Rules:
- Quote numbers exactly as the tools returned them. Never invent counters, \
cells or times.
- If guardrails block a change or the engineer rejects it, do not resubmit the \
same change.
- Keep messages short. When you finish, write a ticket note with the headings: \
Symptom, Evidence, Root cause, Action, Verification.
"""

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Remove inline reasoning that some models (e.g. Nemotron) put in the
    answer: whole <think> blocks, or everything before a lone </think> when
    the server dropped the opening tag."""
    text = _THINK_RE.sub("", text or "")
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


def build_agent(ctx: DemoContext, model: BaseChatModel, checkpointer: BaseCheckpointSaver):
    return create_react_agent(model, build_tools(ctx), prompt=SYSTEM_PROMPT, checkpointer=checkpointer)


def open_checkpointer() -> BaseCheckpointSaver:
    """In-memory checkpointer: holds conversations and paused approvals for as
    long as the Application runs, which matches the in-memory synthetic
    network. In production use a persistent saver (e.g. Postgres) so a paused
    approval survives restarts."""
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def run_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}


def pending_interrupts(agent, config: dict) -> list:
    snap = agent.get_state(config)
    return [i for task in snap.tasks for i in getattr(task, "interrupts", ())]
