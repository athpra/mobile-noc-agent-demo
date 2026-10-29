"""E2B runner: a fresh remote microVM per call, destroyed afterwards."""

from __future__ import annotations

from src.sandbox import SandboxResult

WORKDIR = "/home/user"


class E2BSandbox:
    name = "e2b"
    isolated = True

    def run(self, code: str, files: dict[str, str], timeout_s: int = 30) -> SandboxResult:
        from e2b_code_interpreter import Sandbox  # imported lazily: optional dependency

        sbx = Sandbox.create() if hasattr(Sandbox, "create") else Sandbox()
        try:
            for rel, content in files.items():
                sbx.files.write(f"{WORKDIR}/{rel}", content)
            ex = sbx.run_code(f"import os; os.chdir({WORKDIR!r})\n{code}", timeout=timeout_s)
            stdout = "".join(ex.logs.stdout)
            stderr = "".join(ex.logs.stderr)
            if ex.text and ex.text not in stdout:
                stdout += ex.text
            error = f"{ex.error.name}: {ex.error.value}" if ex.error else None
            if ex.error and ex.error.traceback:
                stderr += ex.error.traceback
            return SandboxResult(stdout, stderr, error)
        finally:
            sbx.kill()
