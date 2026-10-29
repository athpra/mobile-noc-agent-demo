"""
Staged faults for the demo.

A scenario only changes the network the way a real event would (a new cell,
a config change). It never touches the counters directly: the PM generator
derives the symptoms from the resulting configuration, so a correct fix
clears them and a wrong fix doesn't.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from src.network.model import CELL_CREATED, DEFAULT_ATTRS, Cell, CMChange, Network, Site

SMALL_SITE = "SC1188"
SMALL_CELL = "SC1188-C1"
SERVING_CELL = "GNB1042-C1"
CONFLICTING_CELL = "GNB1043-C1"   # macro PCI 141 under the plan in model.py
COLLIDING_PCI = 141


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    summary: str
    inject: Callable[[Network], None]


def _inject_pci_confusion(net: Network) -> None:
    """Commission a small cell at 07:02 inside GNB1042-C1's coverage with a
    PCI that GNB1043-C1 already uses. GNB1042-C1 then has two neighbours on
    PCI 141 and cannot tell which one a UE is reporting."""
    created = net.day_start + timedelta(hours=7, minutes=2)
    host = net.sites["GNB1042"]
    net.sites[SMALL_SITE] = Site(SMALL_SITE, "small", host.x_km + 0.35, host.y_km + 0.45)
    attrs = dict(
        DEFAULT_ATTRS,
        nRPCI=COLLIDING_PCI,
        bSChannelBwDL=40,
        a3OffsetDb=2.0,
    )
    net.cells[SMALL_CELL] = Cell(SMALL_CELL, SMALL_SITE, 1, 0, created, attrs)
    net.add_relation(SERVING_CELL, SMALL_CELL, created)
    net.changes.append(CMChange(
        created, SMALL_CELL, CELL_CREATED, None,
        f"NRCellDU {SMALL_CELL} (nRPCI={COLLIDING_PCI}, bSChannelBwDL=40)",
        "commissioning: SC1188 integration (planned work)",
    ))


SCENARIOS: dict[str, Scenario] = {
    "pci_confusion": Scenario(
        key="pci_confusion",
        title="Handover failures after small-cell commissioning",
        summary=(
            "A small cell switched on at 07:02 reuses PCI 141, which neighbour "
            "GNB1043-C1 already has. Handover success on GNB1042-C1 drops from "
            "the 07:15 ROP onward. No alarm fires."
        ),
        inject=_inject_pci_confusion,
    ),
}

DEFAULT_SCENARIO = "pci_confusion"
