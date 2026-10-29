"""
End-to-end graph test with a scripted chat model: the real tools, sandbox,
interrupt and resume run; only the LLM's choices are canned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command

from src.agent import build_agent, open_checkpointer, pending_interrupts, run_config
from src.config import Settings
from src.context import DemoContext
from src.network.scenarios import SERVING_CELL, SMALL_CELL


class ScriptedModel(BaseChatModel):
    script: Any  # Any, not list: pydantic would copy a list, and callers share one script

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{i}"}])


ANALYSIS = """
import pandas as pd
df = pd.read_csv('data/ho_relations_GNB1042-C1.csv')
df = df[df.rop_start >= '07:15']
g = df.groupby(['target_cell', 'target_pci'])[['ho_att', 'ho_succ']].sum()
g['fail'] = g.ho_att - g.ho_succ
print(g.sort_values('fail', ascending=False).head(3))
"""


def script(final_text: str) -> list:
    return [
        call("get_ho_relations", {"cell_id": SERVING_CELL}, 1),
        call("run_python", {"code": ANALYSIS, "datasets": [f"ho_relations_{SERVING_CELL}"]}, 2),
        call("propose_cm_change", {"cell_id": SMALL_CELL, "attribute": "nRPCI", "new_value": "401",
                                   "reason": "PCI 141 confusion with GNB1043-C1"}, 3),
        call("get_kpis", {"cell_id": SERVING_CELL, "last_n_rops": 1}, 4),
        AIMessage(content=final_text),
    ]


def make(tmp_path: Path, final_text: str):
    settings = Settings("http://unused", "scripted", 0.0, "local", 7, tmp_path / "audit.jsonl")
    ctx = DemoContext.create(settings, "test")
    agent = build_agent(ctx, ScriptedModel(script=script(final_text)), open_checkpointer())
    return ctx, agent, run_config("t1")


def test_change_waits_for_approval_then_applies(tmp_path):
    ctx, agent, cfg = make(tmp_path, "Symptom: ... Verification: recovered.")
    agent.invoke({"messages": [{"role": "user", "content": "Why did HO drop?"}]}, cfg)

    intr = pending_interrupts(agent, cfg)
    assert len(intr) == 1
    assert intr[0].value["proposed_value"] == 401
    assert "+  nRPCI: 401" in intr[0].value["diff"]
    assert ctx.oss.pci_conflicts(), "nothing may change before approval"

    sandbox_out = [m for m in agent.get_state(cfg).values["messages"]
                   if isinstance(m, ToolMessage) and m.name == "run_python"][0].content
    assert "GNB1043-C1" in sandbox_out

    agent.invoke(Command(resume={"approved": True, "approver": "tester"}), cfg)
    assert not pending_interrupts(agent, cfg)
    assert ctx.oss.pci_conflicts() == {}
    assert ctx.audit.entries[-1]["kind"] == "tool_call"  # get_kpis after the change
    assert any(e.get("decision") == "approved" for e in ctx.audit.entries)
    msgs = agent.get_state(cfg).values["messages"]
    assert msgs[-1].content.startswith("Symptom")


def test_rejection_changes_nothing(tmp_path):
    ctx, agent, cfg = make(tmp_path, "Rejected; no change made.")
    agent.invoke({"messages": [{"role": "user", "content": "Why did HO drop?"}]}, cfg)
    agent.invoke(Command(resume={"approved": False, "comment": "wait for planning"}), cfg)

    assert ctx.oss.pci_conflicts()
    tool_msgs = [m for m in agent.get_state(cfg).values["messages"]
                 if isinstance(m, ToolMessage) and m.name == "propose_cm_change"]
    assert "REJECTED" in tool_msgs[0].content
