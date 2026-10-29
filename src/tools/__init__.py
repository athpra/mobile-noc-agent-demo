"""
The agent's tools, in three groups that match the architecture:

  read      query the (mock) OSS for alarms, KPIs, config and topology
  sandbox   run the agent's own analysis code away from credentials
  change    propose a config change; applied only after a person approves

Tools are built per session so they close over that session's DemoContext.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from src.context import DemoContext
from src.tools.change_tool import build_change_tools
from src.tools.read_tools import build_read_tools
from src.tools.sandbox_tool import build_sandbox_tools


def build_tools(ctx: DemoContext) -> list[BaseTool]:
    return [*build_read_tools(ctx), *build_sandbox_tools(ctx), *build_change_tools(ctx)]
