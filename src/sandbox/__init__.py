"""
Where the agent's own Python code runs.

The agent writes analysis code (parse counters, correlate, check a PCI
plan). That code is untrusted: it comes from a model that has read tool
output. It runs here, away from the OSS credentials and the network tools.

Providers:
  e2b    Remote microVM per run (needs E2B_API_KEY and outbound internet).
         Real isolation.
  local  A separate Python process with a time limit, a memory limit where
         the OS supports it, a scratch directory and no secrets in its
         environment. NOT a security boundary: fine for this synthetic demo,
         not for real network data or real credentials.
  auto   e2b when E2B_API_KEY is set, otherwise local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

MAX_OUTPUT_CHARS = 6000


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    error: str | None

    def render(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.error:
            parts.append(f"ERROR: {self.error}")
            if self.stderr.strip():
                parts.append(self.stderr.rstrip()[-2000:])
        text = "\n".join(parts) or "(no output: print() the results you need)"
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + f"\n... [truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
        return text


class Sandbox(Protocol):
    name: str
    isolated: bool

    def run(self, code: str, files: dict[str, str], timeout_s: int = 30) -> SandboxResult: ...


def get_sandbox(provider: str = "auto") -> Sandbox:
    provider = provider or "auto"
    if provider == "auto":
        provider = "e2b" if os.environ.get("E2B_API_KEY") else "local"
    if provider == "e2b":
        from src.sandbox.e2b import E2BSandbox

        return E2BSandbox()
    if provider == "local":
        from src.sandbox.local import LocalSandbox

        return LocalSandbox()
    raise ValueError(f"Unknown SANDBOX_PROVIDER '{provider}'. Use auto, e2b or local.")
