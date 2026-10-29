"""The run_python tool: the agent's analysis code runs in the sandbox."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from src.context import DemoContext


def build_sandbox_tools(ctx: DemoContext) -> list[BaseTool]:
    @tool
    def run_python(code: str, datasets: list[str] = []) -> str:  # noqa: B006 - never mutated; keeps the schema a plain array
        """Run Python 3 analysis code in an isolated sandbox with pandas available.
        The sandbox has no network access to the OSS and no credentials.
        Pass dataset names returned by the read tools in `datasets`; each is
        available as data/<name>.csv. print() everything you want to see."""
        missing = [d for d in datasets if d not in ctx.workspace.names()]
        if missing:
            return (f"Unknown dataset(s): {', '.join(missing)}. "
                    f"Available: {', '.join(ctx.workspace.names()) or 'none yet; call a read tool first'}.")
        files = {f"data/{d}.csv": ctx.workspace.csv(d) for d in datasets}
        result = ctx.sandbox.run(code, files)
        ctx.audit.log("tool_call", ctx.network_time, tool="run_python", args={"datasets": datasets},
                      code=code, sandbox=ctx.sandbox.name, error=result.error)
        return result.render()

    return [run_python]
