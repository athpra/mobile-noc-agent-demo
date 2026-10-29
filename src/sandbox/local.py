"""
Local subprocess runner. Demo only: this limits accidents, it does not
contain hostile code (the process can still reach the network and read
files the app user can read).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from src.sandbox import SandboxResult

MEMORY_LIMIT_BYTES = 3 * 1024**3
CPU_LIMIT_S = 30

# Runs first in the child: set hard limits the analysis code cannot raise,
# then execute it as __main__.
_RUNNER = f"""
import runpy
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, ({CPU_LIMIT_S}, {CPU_LIMIT_S}))
    resource.setrlimit(resource.RLIMIT_AS, ({MEMORY_LIMIT_BYTES}, {MEMORY_LIMIT_BYTES}))
except (ImportError, ValueError, OSError):
    pass  # not supported on this OS (e.g. RLIMIT_AS on macOS)
runpy.run_path("main.py", run_name="__main__")
"""


class LocalSandbox:
    name = "local"
    isolated = False

    def run(self, code: str, files: dict[str, str], timeout_s: int = 30) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="noc-sbx-") as tmp:
            root = Path(tmp)
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            (root / "main.py").write_text(code)
            (root / "runner.py").write_text(_RUNNER)

            # Only what Python needs to start. HOME is kept because pip's
            # user site-packages (where Workbench installs pandas) hangs off it.
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", tmp),
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MPLBACKEND": "Agg",
            }
            try:
                proc = subprocess.run(
                    [sys.executable, "-E", "runner.py"],
                    cwd=root, env=env, capture_output=True, text=True, timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                return SandboxResult(out, "", f"timed out after {timeout_s}s")

            error = None
            if proc.returncode != 0:
                last = proc.stderr.strip().splitlines()[-1:] or [f"exit code {proc.returncode}"]
                error = last[0]
            return SandboxResult(proc.stdout, proc.stderr, error)
