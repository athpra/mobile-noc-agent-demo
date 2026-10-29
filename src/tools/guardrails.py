"""
Checks every proposed configuration change must pass before a person is even
asked to approve it. A "fail" blocks the proposal; a "warn" is shown to the
approver.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from typing import Any

from src.network.oss import MockOSS

MAX_CHANGES_PER_SESSION = 3

# attribute: (type, min, max, step or allowed set, unit)
ALLOWED_ATTRIBUTES: dict[str, tuple[type, float, float, Any, str]] = {
    "nRPCI": (int, 0, 1007, 1, ""),
    "a3OffsetDb": (float, -15, 15, 0.5, "dB"),
    "hysteresisDb": (float, 0, 15, 0.5, "dB"),
    "timeToTriggerMs": (int, 0, 5120, {0, 40, 64, 80, 100, 128, 160, 256, 320, 480, 512, 640, 1024, 1280, 2560, 5120}, "ms"),
    "cellIndividualOffsetDb": (float, -24, 24, 1, "dB"),
}


class GuardrailError(ValueError):
    pass


@dataclass
class Check:
    name: str
    status: str   # "pass" | "warn" | "fail"
    detail: str


def parse_value(attribute: str, raw: Any) -> int | float:
    if attribute not in ALLOWED_ATTRIBUTES:
        raise GuardrailError(
            f"'{attribute}' cannot be changed by the agent. Allowed attributes: {', '.join(ALLOWED_ATTRIBUTES)}."
        )
    typ, lo, hi, step, unit = ALLOWED_ATTRIBUTES[attribute]
    try:
        value = typ(float(str(raw).strip().removesuffix(unit).strip()))
    except ValueError as exc:
        raise GuardrailError(f"{attribute} needs a number, got '{raw}'.") from exc
    if not lo <= value <= hi:
        raise GuardrailError(f"{attribute} must be between {lo} and {hi}{unit}, got {value}.")
    if isinstance(step, set):
        if value not in step:
            raise GuardrailError(f"{attribute} must be one of {sorted(step)}, got {value}.")
    elif round(value / step, 6) % 1:
        raise GuardrailError(f"{attribute} must be a multiple of {step}{unit}, got {value}.")
    return value


def check_change(oss: MockOSS, cell_id: str, attribute: str, value: int | float, changes_applied: int) -> list[Check]:
    current = oss.net.config_at(cell_id, oss.now).get(attribute)
    checks = [Check("Allowed attribute", "pass", f"{attribute} is on the change allowlist")]
    checks.append(
        Check("Value changes", "fail", f"{attribute} is already {current}")
        if current == value else Check("Value changes", "pass", f"{current} → {value}")
    )
    checks.append(
        Check("Change budget", "fail", f"{changes_applied} of {MAX_CHANGES_PER_SESSION} changes already used this session")
        if changes_applied >= MAX_CHANGES_PER_SESSION
        else Check("Change budget", "pass", f"{changes_applied} of {MAX_CHANGES_PER_SESSION} changes used")
    )

    if attribute == "nRPCI":
        within = oss.net.neighbors_within(cell_id, 2, oss.now)
        clashes = sorted(c for c in within if oss.net.pci_at(c, oss.now) == value)
        checks.append(
            Check("PCI unique within 2 hops", "fail", f"PCI {value} is already used by {', '.join(clashes)}")
            if clashes else Check("PCI unique within 2 hops", "pass", f"no cell within 2 hops uses PCI {value}")
        )
        direct = oss.net.neighbors(cell_id, oss.now)
        same_mod = sorted(c for c in direct if oss.net.pci_at(c, oss.now) % 3 == value % 3)
        checks.append(
            Check("PCI mod-3 vs direct neighbours", "warn",
                  f"PCI {value} has mod-3 = {value % 3}, same as {', '.join(same_mod)}; expect reference-signal interference")
            if same_mod else Check("PCI mod-3 vs direct neighbours", "pass", f"mod-3 = {value % 3} differs from all direct neighbours")
        )
    return checks


def config_diff(oss: MockOSS, cell_id: str, attribute: str, value: Any) -> str:
    before = oss.net.config_at(cell_id, oss.now)
    after = dict(before, **{attribute: value})
    mo = oss.get_cell(cell_id)["managed_object"]

    def render(attrs: dict[str, Any]) -> list[str]:
        return [f"{mo}\n"] + [f"  {k}: {v}\n" for k, v in attrs.items()]

    return "".join(difflib.unified_diff(render(before), render(after), "running", "candidate", n=2))


def checks_as_dicts(checks: list[Check]) -> list[dict[str, str]]:
    return [asdict(c) for c in checks]
