from datetime import date

import pytest

from src.network.oss import MockOSS, UnknownCellError
from src.network.scenarios import CONFLICTING_CELL, SERVING_CELL, SMALL_CELL
from src.tools.guardrails import GuardrailError, check_change, parse_value

DAY = date(2026, 10, 29)


def ho_sr(rows, start, end):
    sel = [r for r in rows if start <= r["rop_start"] < end]
    return sum(r["ho_succ"] for r in sel) / sum(r["ho_att"] for r in sel)


def test_fault_starts_with_first_rop_after_commissioning():
    oss = MockOSS(day=DAY)
    rows = oss.get_kpis(SERVING_CELL)
    assert ho_sr(rows, "00:00", "07:15") > 0.97
    assert ho_sr(rows, "07:15", "11:00") < 0.88


def test_neighbouring_cells_unaffected():
    rows = MockOSS(day=DAY).get_kpis("GNB1042-C2")
    assert ho_sr(rows, "07:15", "11:00") > 0.97


def test_failures_concentrate_on_confused_relation():
    oss = MockOSS(day=DAY)
    fails = {}
    for r in oss.get_ho_relations(SERVING_CELL):
        if r["rop_start"] >= "07:15":
            fails[r["target_cell"]] = fails.get(r["target_cell"], 0) + r["ho_att"] - r["ho_succ"]
    assert max(fails, key=fails.get) == CONFLICTING_CELL


def test_counters_are_deterministic():
    assert MockOSS(day=DAY).get_kpis(SERVING_CELL) == MockOSS(day=DAY).get_kpis(SERVING_CELL)


def test_correct_pci_clears_fault_and_wrong_one_does_not():
    oss = MockOSS(day=DAY)
    oss.patch_cell(SMALL_CELL, "nRPCI", 401, "test")
    oss.advance(15)
    assert oss.pci_conflicts() == {}
    assert oss.get_kpis(SERVING_CELL)[-1]["ho_sr_pct"] > 95

    oss = MockOSS(day=DAY)
    oss.patch_cell(SMALL_CELL, "nRPCI", 139, "test")  # GNB1042-C2's PCI
    oss.advance(15)
    assert SERVING_CELL in oss.pci_conflicts()


def test_guardrails():
    oss = MockOSS(day=DAY)
    with pytest.raises(GuardrailError):
        parse_value("administrativeState", "LOCKED")
    with pytest.raises(GuardrailError):
        parse_value("nRPCI", "1200")
    with pytest.raises(GuardrailError):
        parse_value("timeToTriggerMs", "300")
    assert parse_value("a3OffsetDb", "2.5 dB") == 2.5

    statuses = {c.name: c.status for c in check_change(oss, SMALL_CELL, "nRPCI", 143, 0)}
    assert statuses["PCI unique within 2 hops"] == "fail"
    statuses = {c.name: c.status for c in check_change(oss, SMALL_CELL, "nRPCI", 402, 0)}
    assert statuses["PCI unique within 2 hops"] == "pass"
    assert statuses["PCI mod-3 vs direct neighbours"] == "warn"   # 402 % 3 == 138 % 3
    statuses = {c.name: c.status for c in check_change(oss, SMALL_CELL, "nRPCI", 401, 3)}
    assert statuses["Change budget"] == "fail"


def test_unknown_cell():
    with pytest.raises(UnknownCellError):
        MockOSS(day=DAY).get_kpis("GNB9999-C1")
