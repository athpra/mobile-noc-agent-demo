"""
In-process stand-in for an OSS northbound API.

Each public method corresponds to one REST endpoint (noted in its docstring)
and returns plain JSON-able dicts, so the tool layer in src/tools can later be
pointed at a real OSS/EMS adapter with the same shape. The simulation clock
also lives here: the network "now" starts at 11:00 and only moves when a
change is applied (see advance()).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from src.network import fm, pm
from src.network.model import CELL_CREATED, Network, build_macro_network
from src.network.scenarios import DEFAULT_SCENARIO, SCENARIOS


class UnknownCellError(ValueError):
    pass


def hhmm(t: datetime | None) -> str | None:
    return t.strftime("%H:%M") if t else None


class MockOSS:
    def __init__(self, scenario: str = DEFAULT_SCENARIO, seed: int = 7, start: str = "11:00", day: date | None = None):
        self.scenario_key = scenario
        self.seed = seed
        self._start = start
        self._day = day
        self.reset()

    def reset(self) -> None:
        self.day_start = datetime.combine(self._day or date.today(), time(0))
        self.net: Network = build_macro_network(self.day_start)
        SCENARIOS[self.scenario_key].inject(self.net)
        h, m = map(int, self._start.split(":"))
        self.now = self.day_start + timedelta(hours=h, minutes=m)

    # --- helpers ----------------------------------------------------------

    def resolve_cell(self, cell_id: str) -> str:
        cid = (cell_id or "").strip().upper()
        if not self.net.cell_exists(cid, self.now):
            raise UnknownCellError(
                f"Unknown cell '{cell_id}'. Cell IDs look like GNB1042-C1 (macro, sectors C1-C3) "
                f"or SC1188-C1 (small cell). Sites: {', '.join(sorted(self.net.sites))}."
            )
        return cid

    def _rops(self) -> list[datetime]:
        return pm.completed_rops(self.net, self.now)

    def advance(self, minutes: int = 15) -> None:
        self.now += timedelta(minutes=minutes)

    # --- endpoints -------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """GET /network/summary"""
        rops = self._rops()
        cells = self.net.cells_at(self.now)
        return {
            "date": self.day_start.date().isoformat(),
            "network_time": hhmm(self.now),
            "latest_complete_rop": f"{hhmm(rops[-1])}-{hhmm(rops[-1] + pm.ROP)}" if rops else None,
            "rop_minutes": 15,
            "sites": {
                "macro": sorted(s for s, v in self.net.sites.items() if v.kind == "macro"),
                "small": sorted(s for s, v in self.net.sites.items() if v.kind == "small"),
            },
            "cell_count": len(cells),
            "rat": "5G NR SA, band n78",
        }

    def get_alarms(self, managed_object: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        """GET /alarms?managedObject=&state="""
        rows = fm.alarms(self.day_start, self.now)
        if managed_object:
            mo = managed_object.strip().upper()
            rows = [a for a in rows if a["managed_object"].startswith(mo) or mo.startswith(a["managed_object"])]
        if active_only:
            rows = [a for a in rows if a["state"] == "ACTIVE"]
        return [dict(a, raised_at=hhmm(a["raised_at"]), cleared_at=hhmm(a["cleared_at"])) for a in rows]

    def get_kpis(self, cell_id: str) -> list[dict[str, Any]]:
        """GET /pm/cells/{id}/kpis : every completed ROP today."""
        cid = self.resolve_cell(cell_id)
        created = self.net.cells[cid].created_at
        rows = [pm.cell_kpis_for_rop(self.net, cid, r, self.seed) for r in self._rops() if r >= created]
        return [dict(r, rop_start=hhmm(r["rop_start"])) for r in rows]

    def get_ho_relations(self, cell_id: str) -> list[dict[str, Any]]:
        """GET /pm/cells/{id}/handover-relations : per neighbour, per ROP."""
        cid = self.resolve_cell(cell_id)
        created = self.net.cells[cid].created_at
        rows = []
        for r in self._rops():
            if r >= created:
                rows.extend(pm.ho_relations_for_rop(self.net, cid, r, self.seed))
        return [dict(r, rop_start=hhmm(r["rop_start"])) for r in rows]

    def get_cell(self, cell_id: str) -> dict[str, Any]:
        """GET /cm/cells/{id}"""
        cid = self.resolve_cell(cell_id)
        cell = self.net.cells[cid]
        site = self.net.sites[cell.site_id]
        return {
            "cell_id": cid,
            "managed_object": f"ManagedElement={cell.site_id},GNBDUFunction=1,NRCellDU={cid}",
            "site_id": cell.site_id,
            "site_type": site.kind,
            "site_xy_km": [round(site.x_km, 2), round(site.y_km, 2)],
            "azimuth_deg": cell.azimuth,
            "created_at": hhmm(cell.created_at) if cell.created_at > self.day_start else "before today",
            "attributes": self.net.config_at(cid, self.now),
        }

    def get_neighbors(self, cell_id: str, hops: int = 1) -> list[dict[str, Any]]:
        """GET /cm/cells/{id}/neighbors?hops="""
        cid = self.resolve_cell(cell_id)
        hops = max(1, min(int(hops), 2))
        found = self.net.neighbors_within(cid, hops, self.now)
        rows = []
        for n, hop in sorted(found.items(), key=lambda kv: (kv[1], kv[0])):
            cell = self.net.cells[n]
            rows.append({
                "cell_id": n,
                "hops": hop,
                "pci": self.net.pci_at(n, self.now),
                "site_id": cell.site_id,
                "site_type": self.net.sites[cell.site_id].kind,
                "distance_km": self.net.distance_km(cid, n),
                "created_at": hhmm(cell.created_at) if cell.created_at > self.day_start else "before today",
            })
        return rows

    def get_cm_changes(self, since: str | None = None) -> list[dict[str, Any]]:
        """GET /cm/changes?since=HH:MM"""
        start = self.day_start
        if since:
            h, m = map(int, since.split(":"))
            start = self.day_start + timedelta(hours=h, minutes=m)
        return [
            {
                "time": hhmm(c.time),
                "cell_id": c.cell_id,
                "change": "cell created" if c.attribute == CELL_CREATED else c.attribute,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "source": c.source,
            }
            for c in self.net.changes
            if start <= c.time <= self.now
        ]

    def patch_cell(self, cell_id: str, attribute: str, value: Any, source: str) -> dict[str, Any]:
        """PATCH /cm/cells/{id}"""
        cid = self.resolve_cell(cell_id)
        ch = self.net.apply_change(cid, attribute, value, self.now, source)
        return {"time": hhmm(ch.time), "cell_id": cid, "attribute": attribute,
                "old_value": ch.old_value, "new_value": ch.new_value}

    # --- scenario status (for the UI, not an OSS endpoint) ----------------

    def pci_conflicts(self) -> dict[str, list[dict[str, Any]]]:
        out = {}
        for cid in self.net.cells_at(self.now):
            issues = self.net.pci_conflicts(cid, self.now)
            if issues:
                out[cid] = issues
        return out
