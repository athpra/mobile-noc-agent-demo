"""
Fault management (FM) alarms for the synthetic network.

None of these explain the staged fault. They are the everyday background
noise a NOC sees, so the agent has to look past them instead of grabbing the
first alarm it finds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# (raised hh:mm, cleared hh:mm or None, severity, managed object, specific problem, probable cause)
_ALARMS = [
    ("02:14", "02:40", "MINOR", "GNB1039", "Fan speed below threshold", "equipmentMalfunction"),
    ("05:31", None, "WARNING", "GNB1046", "PTP clock accuracy degraded", "timingProblem"),
    ("06:48", "06:49", "MINOR", "GNB1047", "Ethernet port link down", "lossOfSignal"),
    ("08:47", None, "MINOR", "GNB1040-C2", "Antenna VSWR over threshold", "vswrOverThreshold"),
    ("09:58", "10:21", "WARNING", "GNB1045", "License capacity at 85%", "thresholdCrossed"),
]


def _at(day_start: datetime, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return day_start + timedelta(hours=h, minutes=m)


def alarms(day_start: datetime, now: datetime) -> list[dict[str, Any]]:
    out = []
    for i, (raised, cleared, sev, mo, problem, cause) in enumerate(_ALARMS, start=1):
        raised_at = _at(day_start, raised)
        if raised_at > now:
            continue
        cleared_at = _at(day_start, cleared) if cleared else None
        if cleared_at and cleared_at > now:
            cleared_at = None
        out.append({
            "alarm_id": f"A-{day_start:%m%d}-{i:03d}",
            "raised_at": raised_at,
            "cleared_at": cleared_at,
            "severity": sev,
            "managed_object": mo,
            "specific_problem": problem,
            "probable_cause": cause,
            "state": "CLEARED" if cleared_at else "ACTIVE",
        })
    return out
