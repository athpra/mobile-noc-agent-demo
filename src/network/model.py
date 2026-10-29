"""
Synthetic 5G RAN topology and configuration management (CM) data.

Twelve macro gNBs sit on a 4 x 3 grid, three NR cells each, and the staged
scenario (see src/network/scenarios.py) adds a small cell during the morning.
Configuration is stored as each cell's initial attributes plus a timeline of
changes, so the performance generator can ask "what was configured at 07:15?"
and produce counters that follow from that configuration rather than being
scripted per timestamp. Fixing the fault therefore really fixes it: any PCI
that removes the conflict brings the counters back, any PCI that doesn't,
doesn't.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

GRID_COLS = 4
GRID_ROWS = 3
SITE_SPACING_KM = 1.2
FIRST_SITE_NUMBER = 1037
SECTOR_AZIMUTHS = (0, 120, 240)

# Macro PCIs follow a simple plan: 3 * (base group + site index) + sector.
# Each site gets one PCI group, so co-sited sectors differ in mod-3 and no two
# macro cells share a PCI.
PCI_BASE_GROUP = 41

# Change-log attribute name for cell creation; not a configurable attribute.
CELL_CREATED = "cellCreated"

NR_ARFCN_DL = 636666  # n78, 3.55 GHz
TAC = 4101

# Default mobility parameters for every cell (3GPP-style attribute names).
DEFAULT_ATTRS: dict[str, Any] = {
    "nRTAC": TAC,
    "arfcnDL": NR_ARFCN_DL,
    "bSChannelBwDL": 100,
    "ssbPeriodicityMs": 20,
    "a3OffsetDb": 3.0,
    "hysteresisDb": 1.0,
    "timeToTriggerMs": 320,
    "cellIndividualOffsetDb": 0.0,
    "administrativeState": "UNLOCKED",
}


@dataclass(frozen=True)
class Site:
    id: str
    kind: str  # "macro" | "small"
    x_km: float
    y_km: float


@dataclass
class Cell:
    id: str
    site_id: str
    sector: int
    azimuth: int
    created_at: datetime
    initial_attrs: dict[str, Any]


@dataclass(frozen=True)
class CMChange:
    time: datetime
    cell_id: str
    attribute: str
    old_value: Any
    new_value: Any
    source: str


@dataclass
class Network:
    day_start: datetime
    sites: dict[str, Site] = field(default_factory=dict)
    cells: dict[str, Cell] = field(default_factory=dict)
    # Undirected neighbour relations, each with the time it was created.
    relations: dict[frozenset[str], datetime] = field(default_factory=dict)
    changes: list[CMChange] = field(default_factory=list)

    # --- topology -------------------------------------------------------

    def add_relation(self, a: str, b: str, created_at: datetime) -> None:
        self.relations.setdefault(frozenset((a, b)), created_at)

    def cell_exists(self, cell_id: str, at: datetime) -> bool:
        cell = self.cells.get(cell_id)
        return cell is not None and cell.created_at <= at

    def cells_at(self, at: datetime) -> list[str]:
        return [c for c in self.cells if self.cell_exists(c, at)]

    def neighbors(self, cell_id: str, at: datetime) -> list[str]:
        out = []
        for pair, created in self.relations.items():
            if cell_id in pair and created <= at:
                (other,) = pair - {cell_id}
                if self.cell_exists(other, at):
                    out.append(other)
        return sorted(out)

    def neighbors_within(self, cell_id: str, hops: int, at: datetime) -> dict[str, int]:
        """Cells reachable within `hops` neighbour relations, mapped to hop count."""
        seen = {cell_id: 0}
        frontier = [cell_id]
        for hop in range(1, hops + 1):
            nxt = []
            for c in frontier:
                for n in self.neighbors(c, at):
                    if n not in seen:
                        seen[n] = hop
                        nxt.append(n)
            frontier = nxt
        seen.pop(cell_id)
        return seen

    def distance_km(self, a: str, b: str) -> float:
        sa = self.sites[self.cells[a].site_id]
        sb = self.sites[self.cells[b].site_id]
        return round(math.hypot(sa.x_km - sb.x_km, sa.y_km - sb.y_km), 2)

    # --- configuration --------------------------------------------------

    def config_at(self, cell_id: str, at: datetime) -> dict[str, Any]:
        attrs = dict(self.cells[cell_id].initial_attrs)
        for ch in self.changes:
            if ch.cell_id == cell_id and ch.time <= at and ch.attribute != CELL_CREATED:
                attrs[ch.attribute] = ch.new_value
        return attrs

    def pci_at(self, cell_id: str, at: datetime) -> int:
        return int(self.config_at(cell_id, at)["nRPCI"])

    def apply_change(self, cell_id: str, attribute: str, value: Any, at: datetime, source: str) -> CMChange:
        old = self.config_at(cell_id, at).get(attribute)
        change = CMChange(at, cell_id, attribute, old, value, source)
        self.changes.append(change)
        return change

    # --- PCI conflicts ---------------------------------------------------

    def pci_conflicts(self, cell_id: str, at: datetime) -> list[dict[str, Any]]:
        """PCI collision (a neighbour shares this cell's PCI) and confusion
        (two neighbours share a PCI) seen from `cell_id` at time `at`."""
        own = self.pci_at(cell_id, at)
        by_pci: dict[int, list[str]] = {}
        for n in self.neighbors(cell_id, at):
            by_pci.setdefault(self.pci_at(n, at), []).append(n)
        issues = []
        for pci, cells in sorted(by_pci.items()):
            if pci == own:
                issues.append({"type": "collision", "pci": pci, "cells": [cell_id, *cells]})
            if len(cells) > 1:
                issues.append({"type": "confusion", "pci": pci, "cells": cells})
        return issues


def site_id(index: int) -> str:
    return f"GNB{FIRST_SITE_NUMBER + index}"


def build_macro_network(day_start: datetime) -> Network:
    net = Network(day_start=day_start)
    for i in range(GRID_COLS * GRID_ROWS):
        col, row = i % GRID_COLS, i // GRID_COLS
        sid = site_id(i)
        net.sites[sid] = Site(sid, "macro", col * SITE_SPACING_KM, row * SITE_SPACING_KM)
        for s, az in enumerate(SECTOR_AZIMUTHS):
            cid = f"{sid}-C{s + 1}"
            attrs = dict(DEFAULT_ATTRS, nRPCI=3 * (PCI_BASE_GROUP + i) + s)
            net.cells[cid] = Cell(cid, sid, s + 1, az, day_start, attrs)

    # Relations: co-sited sectors, and every cell of the sites directly
    # left/right/above/below.
    for a in net.cells.values():
        for b in net.cells.values():
            if a.id >= b.id:
                continue
            sa, sb = net.sites[a.site_id], net.sites[b.site_id]
            if math.isclose(math.hypot(sa.x_km - sb.x_km, sa.y_km - sb.y_km), 0) or math.isclose(
                math.hypot(sa.x_km - sb.x_km, sa.y_km - sb.y_km), SITE_SPACING_KM
            ):
                net.add_relation(a.id, b.id, day_start)
    return net
