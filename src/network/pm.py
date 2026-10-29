"""
Performance management (PM) counters for the synthetic network.

Counters are produced per cell per 15-minute ROP (result output period) and
are a pure function of (seed, cell, ROP, configuration live at that ROP), so
the same question always gets the same numbers and nothing has to be stored.

How a PCI conflict shows up: when two neighbours of a serving cell share a
PCI, the gNB resolves a UE's measurement report for that PCI to the older
neighbour relation. UEs that were really near the newer cell get sent to the
wrong target and most of those handovers fail. The serving cell's handover
success rate drops and its drop rate rises, with no alarm raised.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from src.network.model import Network

ROP = timedelta(minutes=15)

# Relative traffic by hour of day (00..23); evening busy hour peaks at 1.0.
LOAD_PROFILE = [
    0.25, 0.18, 0.14, 0.12, 0.12, 0.16, 0.30, 0.55, 0.75, 0.80, 0.82, 0.85,
    0.88, 0.86, 0.84, 0.85, 0.90, 0.95, 1.00, 1.00, 0.92, 0.75, 0.55, 0.38,
]

# Handover attempts per ROP per relation at full load.
HO_BASE_COSITE = 18
HO_BASE_ADJACENT = 6
HO_BASE_SMALL_CELL = 26
HO_SUCCESS_MEAN = 0.987
MISROUTED_SUCCESS = 0.08     # UEs handed to a PCI-confused target mostly fail
COLLISION_SUCCESS = 0.30
BASE_DROP_PCT = 0.35


def _rng(*parts: Any) -> random.Random:
    # str seeds hash with SHA-512, so this is stable across processes.
    return random.Random(":".join(str(p) for p in parts))


def rop_index(net: Network, rop_start: datetime) -> int:
    return int((rop_start - net.day_start) / ROP)


def completed_rops(net: Network, now: datetime) -> list[datetime]:
    out, t = [], net.day_start
    while t + ROP <= now:
        out.append(t)
        t += ROP
    return out


def load_at(net: Network, t: datetime) -> float:
    hours = (t - net.day_start).total_seconds() / 3600 % 24
    h0 = int(hours)
    frac = hours - h0
    return LOAD_PROFILE[h0] * (1 - frac) + LOAD_PROFILE[(h0 + 1) % 24] * frac


def _successes(rng: random.Random, attempts: int, rate: float) -> int:
    """Binomial draw, so small relations still show the occasional failure."""
    return sum(rng.random() < rate for _ in range(attempts))


def _relation_base(net: Network, source: str, target: str) -> int:
    kinds = {net.sites[net.cells[c].site_id].kind for c in (source, target)}
    if "small" in kinds:
        return HO_BASE_SMALL_CELL
    if net.cells[source].site_id == net.cells[target].site_id:
        return HO_BASE_COSITE
    return HO_BASE_ADJACENT


def _relation_created(net: Network, a: str, b: str) -> datetime:
    return net.relations[frozenset((a, b))]


def ho_relations_for_rop(net: Network, cell_id: str, rop_start: datetime, seed: int) -> list[dict[str, Any]]:
    """Outgoing handover counters from `cell_id` to each neighbour for one ROP."""
    k = rop_index(net, rop_start)
    load = load_at(net, rop_start + ROP / 2)
    own_pci = net.pci_at(cell_id, rop_start)
    nbrs = net.neighbors(cell_id, rop_start)
    pci_of = {n: net.pci_at(n, rop_start) for n in nbrs}
    sharing: dict[int, list[str]] = {}
    for n, p in pci_of.items():
        sharing.setdefault(p, []).append(n)

    rows = []
    for target in nbrs:
        rng = _rng(seed, "ho", cell_id, target, k)
        pci = pci_of[target]
        att = round(_relation_base(net, cell_id, target) * load * rng.uniform(0.85, 1.15))
        rate = min(1.0, rng.gauss(HO_SUCCESS_MEAN, 0.004))
        succ = _successes(rng, att, rate)

        group = sharing[pci]
        if pci == own_pci:
            succ = _successes(rng, att, COLLISION_SUCCESS)
        elif len(group) > 1:
            resolved = min(group, key=lambda c: (_relation_created(net, cell_id, c), c))
            if target == resolved:
                # Reports for this PCI from UEs near the other cells land here.
                for other in group:
                    if other == target:
                        continue
                    orng = _rng(seed, "misrouted", cell_id, other, k)
                    extra = round(_relation_base(net, cell_id, other) * load * orng.uniform(0.85, 1.15))
                    att += extra
                    succ += _successes(orng, extra, max(0.0, orng.gauss(MISROUTED_SUCCESS, 0.02)))
            else:
                # Only the odd handover reaches the newer cell directly.
                att = round(att * 0.05)
                succ = _successes(rng, att, rate)

        rows.append({
            "rop_start": rop_start,
            "source_cell": cell_id,
            "target_cell": target,
            "target_pci": pci,
            "ho_att": att,
            "ho_succ": min(succ, att),
        })
    return rows


def cell_kpis_for_rop(net: Network, cell_id: str, rop_start: datetime, seed: int) -> dict[str, Any]:
    k = rop_index(net, rop_start)
    rng = _rng(seed, "kpi", cell_id, k)
    load = load_at(net, rop_start + ROP / 2)
    small = net.sites[net.cells[cell_id].site_id].kind == "small"

    rels = ho_relations_for_rop(net, cell_id, rop_start, seed)
    ho_att = sum(r["ho_att"] for r in rels)
    ho_succ = sum(r["ho_succ"] for r in rels)
    ho_fail_ratio = (ho_att - ho_succ) / ho_att if ho_att else 0.0

    ue = (12 if small else 38) * load * rng.uniform(0.9, 1.1)
    rrc_att = round(ue * 9 * rng.uniform(0.9, 1.1))
    rrc_succ = round(rrc_att * min(1.0, rng.gauss(0.996, 0.002)))
    prb = min(97.0, (45 if small else 72) * load * rng.uniform(0.9, 1.1) + 4)
    thp = max(12.0, (240 if small else 180) * (1 - prb / 110) * rng.uniform(0.92, 1.08))
    drop = BASE_DROP_PCT * rng.uniform(0.8, 1.2) + ho_fail_ratio * 4.0

    return {
        "rop_start": rop_start,
        "cell_id": cell_id,
        "ue_avg": round(ue, 1),
        "rrc_setup_att": rrc_att,
        "rrc_setup_succ": rrc_succ,
        "rrc_setup_sr_pct": round(100 * rrc_succ / rrc_att, 2) if rrc_att else None,
        "ho_att": ho_att,
        "ho_succ": ho_succ,
        "ho_sr_pct": round(100 * ho_succ / ho_att, 2) if ho_att else None,
        "drop_rate_pct": round(drop, 2),
        "prb_util_dl_pct": round(prb, 1),
        "dl_ue_thp_mbps": round(thp, 1),
    }
