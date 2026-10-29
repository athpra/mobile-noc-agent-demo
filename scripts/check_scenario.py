"""
Pre-flight check, no LLM needed: confirms the staged fault shows up in the
counters, that the guardrails accept a correct fix and block a wrong one, that
the fix clears the fault, and that the sandbox can run pandas.

Run from the project root:  python scripts/check_scenario.py
"""

import sys
from pathlib import Path

try:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
except NameError:  # CML runs task scripts in a kernel, where __file__ is undefined; cwd is the project root
    PROJECT_ROOT = Path.cwd()
sys.path.insert(0, str(PROJECT_ROOT))

from src.network.oss import MockOSS  # noqa: E402
from src.network.scenarios import COLLIDING_PCI, SERVING_CELL, SMALL_CELL  # noqa: E402
from src.sandbox import get_sandbox  # noqa: E402
from src.tools.guardrails import check_change  # noqa: E402


def mean(xs):
    return sum(xs) / len(xs)


def main() -> int:
    oss = MockOSS()
    kpis = oss.get_kpis(SERVING_CELL)
    before = mean([r["ho_sr_pct"] for r in kpis if r["rop_start"] < "07:00"])
    during = mean([r["ho_sr_pct"] for r in kpis if r["rop_start"] >= "07:15"])
    print(f"{SERVING_CELL} HO success: {before:.1f}% before 07:00, {during:.1f}% from 07:15")
    assert during < before - 10, "fault not visible in the counters"

    bad = check_change(oss, SMALL_CELL, "nRPCI", 140, 0)
    assert any(c.status == "fail" for c in bad), "guardrails let a clashing PCI through"
    good = check_change(oss, SMALL_CELL, "nRPCI", 401, 0)
    assert not any(c.status == "fail" for c in good), "guardrails blocked a valid PCI"
    print(f"Guardrails: PCI 140 blocked, PCI 401 allowed (was {COLLIDING_PCI})")

    oss.patch_cell(SMALL_CELL, "nRPCI", 401, "check_scenario")
    oss.advance(15)
    after = oss.get_kpis(SERVING_CELL)[-1]["ho_sr_pct"]
    print(f"After fix, {SERVING_CELL} HO success in the next ROP: {after:.1f}%")
    assert after > 95 and not oss.pci_conflicts(), "fix did not clear the fault"

    sbx = get_sandbox()
    res = sbx.run(
        "import pandas as pd\ndf = pd.read_csv('data/x.csv')\nprint('sandbox ok, rows =', len(df))",
        {"data/x.csv": "a,b\n1,2\n3,4\n"},
    )
    print(f"Sandbox ({sbx.name}): {res.render()}")
    assert res.error is None, "sandbox failed"

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    # Raise only on failure: in a CML kernel even SystemExit(0) is reported as an exception.
    status = main()
    if status:
        raise SystemExit(status)
