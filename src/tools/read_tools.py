"""Read-only tools over the OSS northbound API (mocked for the demo)."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from langchain_core.tools import BaseTool, tool

from src.context import DemoContext
from src.network.oss import UnknownCellError


def md_table(rows: list[dict[str, Any]], cols: list[str]) -> str:
    if not rows:
        return "(no rows)"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
    return "\n".join(lines)


def build_read_tools(ctx: DemoContext) -> list[BaseTool]:
    oss, ws = ctx.oss, ctx.workspace

    def logged(name: str, args: dict[str, Any], result: str) -> str:
        ctx.audit.log("tool_call", ctx.network_time, tool=name, args=args, result_chars=len(result))
        return result

    @tool
    def get_network_summary() -> str:
        """Current network time, latest complete 15-minute ROP, and the list of sites. Call this first."""
        return logged("get_network_summary", {}, json.dumps(oss.summary(), indent=1))

    @tool
    def get_alarms(managed_object: str = "", active_only: bool = False) -> str:
        """Fault-management alarms raised today. Optionally filter by managed object
        prefix (a site like GNB1042 or a cell like GNB1042-C1) and/or only active alarms."""
        rows = oss.get_alarms(managed_object or None, active_only)
        cols = ["alarm_id", "raised_at", "cleared_at", "state", "severity", "managed_object", "specific_problem"]
        text = md_table(rows, cols) if rows else "No alarms match."
        return logged("get_alarms", {"managed_object": managed_object, "active_only": active_only}, text)

    @tool
    def get_kpis(cell_id: str, last_n_rops: int = 8) -> str:
        """Cell KPIs per 15-minute ROP: handover success rate, drop rate, RRC setup
        success, PRB utilisation, UE throughput. Shows the latest ROPs; the whole day
        is saved as a dataset for run_python."""
        try:
            rows = oss.get_kpis(cell_id)
        except UnknownCellError as exc:
            return logged("get_kpis", {"cell_id": cell_id}, str(exc))
        cid = cell_id.strip().upper()
        cols = ["rop_start", "ho_att", "ho_succ", "ho_sr_pct", "drop_rate_pct", "rrc_setup_sr_pct", "prb_util_dl_pct", "dl_ue_thp_mbps"]
        n = max(1, min(int(last_n_rops), 24))
        text = f"KPIs for {cid}, last {n} ROPs:\n{md_table(rows[-n:], cols)}\n\n{ws.save(f'kpis_{cid}', rows)}"
        return logged("get_kpis", {"cell_id": cid, "last_n_rops": n}, text)

    @tool
    def get_ho_relations(cell_id: str, last_n_rops: int = 4) -> str:
        """Outgoing handover counters from a cell to each neighbour (target cell and its
        PCI), summed over the latest ROPs and sorted by failures. Use this to see which
        target relation the handover failures are concentrated on."""
        try:
            rows = oss.get_ho_relations(cell_id)
        except UnknownCellError as exc:
            return logged("get_ho_relations", {"cell_id": cell_id}, str(exc))
        cid = cell_id.strip().upper()
        n = max(1, min(int(last_n_rops), 24))
        recent = sorted({r["rop_start"] for r in rows})[-n:]
        agg: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
        for r in rows:
            if r["rop_start"] in recent:
                agg[(r["target_cell"], r["target_pci"])][0] += r["ho_att"]
                agg[(r["target_cell"], r["target_pci"])][1] += r["ho_succ"]
        summary = [
            {"target_cell": t, "target_pci": p, "ho_att": a, "ho_succ": s, "ho_fail": a - s,
             "sr_pct": round(100 * s / a, 1) if a else None}
            for (t, p), (a, s) in agg.items()
        ]
        summary.sort(key=lambda r: (-r["ho_fail"], r["target_cell"]))
        window = f"{recent[0]}-{recent[-1]} ROPs" if recent else "no ROPs"
        text = (f"Handover relations from {cid}, summed over {window}:\n"
                f"{md_table(summary, ['target_cell', 'target_pci', 'ho_att', 'ho_succ', 'ho_fail', 'sr_pct'])}\n\n"
                f"{ws.save(f'ho_relations_{cid}', rows)}")
        return logged("get_ho_relations", {"cell_id": cid, "last_n_rops": n}, text)

    @tool
    def get_neighbors(cell_id: str, hops: int = 1) -> str:
        """Neighbour cells of a cell with their PCI, site and distance. hops=2 also
        returns neighbours of neighbours (needed for PCI planning)."""
        try:
            rows = oss.get_neighbors(cell_id, hops)
        except UnknownCellError as exc:
            return logged("get_neighbors", {"cell_id": cell_id}, str(exc))
        cid = cell_id.strip().upper()
        hops = max(1, min(int(hops), 2))
        cols = ["cell_id", "hops", "pci", "site_id", "site_type", "distance_km", "created_at"]
        text = (f"Neighbours of {cid} within {hops} hop(s) (own PCI {oss.net.pci_at(cid, oss.now)}):\n"
                f"{md_table(rows, cols)}\n\n{ws.save(f'neighbors_{cid}_{hops}hop', rows)}")
        return logged("get_neighbors", {"cell_id": cid, "hops": hops}, text)

    @tool
    def get_cell_config(cell_id: str) -> str:
        """Configuration (CM) of one NR cell: PCI, TAC, ARFCN, bandwidth and mobility parameters."""
        try:
            text = json.dumps(oss.get_cell(cell_id), indent=1)
        except UnknownCellError as exc:
            text = str(exc)
        return logged("get_cell_config", {"cell_id": cell_id}, text)

    @tool
    def get_cm_changes(since: str = "00:00") -> str:
        """Configuration changes and cell creations in the network since a time (HH:MM, today)."""
        try:
            rows = oss.get_cm_changes(since)
        except ValueError:
            return logged("get_cm_changes", {"since": since}, "Use since in HH:MM format, e.g. 06:00.")
        text = (md_table(rows, ["time", "cell_id", "change", "old_value", "new_value", "source"])
                if rows else f"No configuration changes since {since}.")
        return logged("get_cm_changes", {"since": since}, text)

    return [get_network_summary, get_alarms, get_kpis, get_ho_relations, get_neighbors, get_cell_config, get_cm_changes]
