"""
Checks that the configured model endpoint can drive the agent: it answers,
and it returns a structured tool call (not just text that describes one).

Run in a Workbench Session after setting CAII_BASE_URL and CAII_MODEL_NAME:
    python scripts/check_endpoint.py

If it reports no tool call, the endpoint needs tool calling enabled (for an
NVIDIA NIM, that is set when the model endpoint is deployed), or use a model
that supports it.
"""

import sys
import time
from pathlib import Path

try:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
except NameError:  # CML runs task scripts in a kernel, where __file__ is undefined; cwd is the project root
    PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.tools import tool  # noqa: E402

from src.agent import strip_reasoning  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.llm import build_chat_model  # noqa: E402


@tool
def get_cell_config(cell_id: str) -> str:
    """Configuration of one NR cell."""
    return "{}"


def main() -> int:
    settings = load_settings()
    if not settings.llm_configured:
        print("Set CAII_BASE_URL and CAII_MODEL_NAME first.")
        return 1
    print(f"Endpoint: {settings.caii_base_url}\nModel:    {settings.caii_model_name}")
    model = build_chat_model(settings)

    start = time.perf_counter()
    reply = model.invoke("Reply with the single word: ready")
    print(f"\n1. Plain answer ({time.perf_counter() - start:.1f}s): {strip_reasoning(str(reply.content))[:200]!r}")
    if "<think>" in str(reply.content) or "</think>" in str(reply.content):
        print("   Reasoning arrives inline in the answer; the app strips it before display.")

    start = time.perf_counter()
    reply = model.bind_tools([get_cell_config]).invoke("Look up the configuration of cell GNB1042-C1.")
    elapsed = time.perf_counter() - start
    if reply.tool_calls:
        print(f"2. Tool call ({elapsed:.1f}s): {reply.tool_calls[0]['name']}({reply.tool_calls[0]['args']})")
        print("\nEndpoint is ready for the agent.")
        return 0
    print(f"2. NO tool call returned ({elapsed:.1f}s). Text was: {strip_reasoning(str(reply.content))[:300]!r}")
    print("\nThe agent needs tool calling. Enable it on the endpoint or choose another model.")
    return 2


if __name__ == "__main__":
    # Raise only on failure: in a CML kernel even SystemExit(0) is reported as an exception.
    status = main()
    if status:
        raise SystemExit(status)
