"""
Per-session state shared by the tools: the synthetic network, the datasets
the read tools have collected, the sandbox, and the audit log.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import Settings
from src.network.oss import MockOSS
from src.sandbox import Sandbox, get_sandbox


class Workspace:
    """Tool results kept by name, so the agent can hand them to the sandbox
    without copying rows through the model's context."""

    def __init__(self) -> None:
        self._data: dict[str, list[dict[str, Any]]] = {}

    def save(self, name: str, rows: list[dict[str, Any]]) -> str:
        self._data[name] = rows
        cols = ", ".join(rows[0].keys()) if rows else "no rows"
        return (
            f"Full data saved as dataset `{name}` ({len(rows)} rows; columns: {cols}). "
            f"To analyse it, call run_python with datasets=[\"{name}\"] and read "
            f"pandas.read_csv(\"data/{name}.csv\")."
        )

    def names(self) -> list[str]:
        return sorted(self._data)

    def csv(self, name: str) -> str:
        rows = self._data[name]
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return buf.getvalue()


class AuditLog:
    """Append-only record of every tool call and every change decision."""

    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.session_id = session_id
        self.entries: list[dict[str, Any]] = []

    def log(self, kind: str, network_time: str, **fields: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session": self.session_id,
            "network_time": network_time,
            "kind": kind,
            **fields,
        }
        self.entries.append(entry)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except OSError:
            pass  # the in-memory copy still feeds the UI


@dataclass
class DemoContext:
    settings: Settings
    oss: MockOSS
    sandbox: Sandbox
    audit: AuditLog
    workspace: Workspace = field(default_factory=Workspace)
    changes_applied: int = 0

    @classmethod
    def create(cls, settings: Settings, session_id: str) -> "DemoContext":
        return cls(
            settings=settings,
            oss=MockOSS(seed=settings.sim_seed),
            sandbox=get_sandbox(settings.sandbox_provider),
            audit=AuditLog(settings.audit_log_path, session_id),
        )

    @property
    def network_time(self) -> str:
        return self.oss.now.strftime("%H:%M")
