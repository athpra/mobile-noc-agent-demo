"""
Altair charts for the app: the radio network map and the KPI trend.

The map draws every cell as a sector wedge at its site, coloured by the
handover success rate in the latest ROP, so the audience can see the fault
appear and clear. Clicking a wedge selects the cell (see app.py).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import altair as alt
import pandas as pd

from src.network import pm
from src.network.oss import MockOSS

# Status palette (fixed, never reused for series). Text ink stays neutral.
GOOD, WARNING, CRITICAL, NO_DATA = "#0ca30c", "#fab219", "#d03b3b", "#5b6b76"
SERIES = "#3987e5"
CHANGE = "#42c7a6"  # CM change markers, in the app accent colour
INK, INK_MUTED, GRID = "#e2eaef", "#8fa1ad", "#22323d"

STATUS_ORDER = ["Healthy", "Degraded", "Critical", "No data"]
STATUS_COLORS = [GOOD, WARNING, CRITICAL, NO_DATA]
# Healthy cells dip to ~93% in a quiet ROP; the staged fault sits near 82%.
HO_TARGET_PCT = 92.0
HO_CRITICAL_PCT = 85.0

SECTOR_HALF_WIDTH_DEG = 50
MACRO_RADIUS_PX = 30
SMALL_RADIUS_PX = 10
PICK = "cell_pick"


def status_of(ho_sr: float | None) -> str:
    if ho_sr is None or (isinstance(ho_sr, float) and math.isnan(ho_sr)):
        return "No data"
    if ho_sr >= HO_TARGET_PCT:
        return "Healthy"
    return "Degraded" if ho_sr >= HO_CRITICAL_PCT else "Critical"


def cell_health(oss: MockOSS) -> pd.DataFrame:
    """One row per cell in service: position, PCI and latest-ROP KPIs."""
    net = oss.net
    rops = pm.completed_rops(net, oss.now)
    rows = []
    for cid in net.cells_at(oss.now):
        cell = net.cells[cid]
        site = net.sites[cell.site_id]
        k = pm.cell_kpis_for_rop(net, cid, rops[-1], oss.seed) if rops and rops[-1] >= cell.created_at else {}
        rows.append({
            "cell_id": cid,
            "site_id": cell.site_id,
            "kind": site.kind,
            "x": site.x_km,
            "y": site.y_km,
            "azimuth": cell.azimuth,
            "pci": net.pci_at(cid, oss.now),
            "ho_sr_pct": k.get("ho_sr_pct"),
            "drop_rate_pct": k.get("drop_rate_pct"),
            "prb_util_dl_pct": k.get("prb_util_dl_pct"),
            "status": status_of(k.get("ho_sr_pct")),
        })
    return pd.DataFrame(rows)


def _at(day_start: datetime, hhmm: str) -> datetime:
    return day_start + timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:]))


def _sector_point(row, km: float = 0.17) -> tuple[float, float]:
    """A point a little way out along the cell's azimuth, for drawing links."""
    if row["kind"] == "small":
        return row["x"], row["y"]
    a = math.radians(row["azimuth"])
    return row["x"] + km * math.sin(a), row["y"] + km * math.cos(a)


def _base(chart: alt.Chart | alt.LayerChart) -> alt.LayerChart:
    # configure() replaces the whole config, so it has to come first.
    return chart.configure(background="transparent").configure_view(stroke=None).configure_axis(
        labelColor=INK_MUTED, titleColor=INK_MUTED, gridColor=GRID, domainColor=GRID, tickColor=GRID,
        labelFont="Inter, system-ui, sans-serif", titleFont="Inter, system-ui, sans-serif",
        labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
    ).configure_legend(
        labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11, orient="bottom", title=None,
        symbolType="circle", symbolSize=90,
    )


def network_map(health: pd.DataFrame, selected: str, conflicts: dict | None = None) -> alt.LayerChart:
    """Sector map of the network. `conflicts` (presenter view) draws the PCI clash."""
    # Derived columns are built as plain lists and added in one assign(): no
    # in-place column writes, which older pandas misreports on Python 3.14.
    rows = health.to_dict("records")
    small = [r["kind"] == "small" for r in rows]
    df = health.assign(
        t0=[0.0 if s else math.radians(r["azimuth"] - SECTOR_HALF_WIDTH_DEG) for r, s in zip(rows, small)],
        t1=[2 * math.pi if s else math.radians(r["azimuth"] + SECTOR_HALF_WIDTH_DEG) for r, s in zip(rows, small)],
        r=[SMALL_RADIUS_PX if s else MACRO_RADIUS_PX for s in small],
        selected=[r["cell_id"] == selected for r in rows],
        ho_label=["n/a" if pd.isna(r["ho_sr_pct"]) else f"{r['ho_sr_pct']:.1f}%" for r in rows],
    )
    is_small = df["kind"] == "small"

    xs = alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-0.6, df["x"].max() + 0.6]))
    ys = alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-0.6, df["y"].max() + 0.75]))

    pick = alt.selection_point(name=PICK, fields=["cell_id"], on="click", clear=False)
    wedges = alt.Chart(df).mark_arc(cursor="pointer", stroke="#0e161d", strokeWidth=1.5).encode(
        x=xs, y=ys,
        theta=alt.Theta("t0:Q", scale=None), theta2="t1:Q",
        radius=alt.Radius("r:Q", scale=None),
        color=alt.Color("status:N", scale=alt.Scale(domain=STATUS_ORDER, range=STATUS_COLORS),
                        legend=alt.Legend(values=STATUS_ORDER[:3])),
        opacity=alt.condition("datum.selected", alt.value(1.0), alt.value(0.8)),
        tooltip=[
            alt.Tooltip("cell_id:N", title="Cell"),
            alt.Tooltip("status:N", title="Status"),
            alt.Tooltip("ho_label:N", title="HO success"),
            alt.Tooltip("drop_rate_pct:Q", title="Drop rate %", format=".2f"),
            alt.Tooltip("prb_util_dl_pct:Q", title="PRB util DL %", format=".0f"),
            alt.Tooltip("pci:Q", title="PCI"),
        ],
    ).add_params(pick)

    ring = alt.Chart(df[df["selected"]]).mark_arc(filled=False, stroke=INK, strokeWidth=2.5).encode(
        x=xs, y=ys, theta=alt.Theta("t0:Q", scale=None), theta2="t1:Q",
        radius=alt.Radius("r:Q", scale=None),
    )

    sites = df[~is_small].drop_duplicates("site_id")
    site_dots = alt.Chart(sites).mark_circle(size=22, color=INK, opacity=0.9).encode(x=xs, y=ys)
    site_labels = alt.Chart(sites).mark_text(dy=-38, fontSize=10, color=INK_MUTED, font="Inter, system-ui").encode(
        x=xs, y=ys, text="site_id:N",
    )
    small_label = alt.Chart(df[is_small]).mark_text(dx=9, dy=-9, align="left", fontSize=10, color=INK).encode(
        x=xs, y=ys, text="cell_id:N",
    )

    layers = [site_dots, wedges, ring, site_labels, small_label]

    if conflicts:
        by_id = df.set_index("cell_id")
        links = []
        for seen_from, issues in conflicts.items():
            for issue in issues:
                for target in issue["cells"]:
                    if target == seen_from or target not in by_id.index or seen_from not in by_id.index:
                        continue
                    (x0, y0), (x1, y1) = _sector_point(by_id.loc[seen_from]), _sector_point(by_id.loc[target])
                    links.append({"pair": f"{seen_from}>{target}", "x": x0, "y": y0, "o": 0})
                    links.append({"pair": f"{seen_from}>{target}", "x": x1, "y": y1, "o": 1,
                                  "label": f"PCI {issue['pci']}"})
        if links:
            ldf = pd.DataFrame(links)
            layers.append(alt.Chart(ldf).mark_line(color=CRITICAL, strokeDash=[5, 4], strokeWidth=2).encode(
                x=xs, y=ys, detail="pair:N", order="o:Q"))
            layers.append(alt.Chart(ldf[ldf["o"] == 1]).mark_text(
                dy=14, fontSize=11, fontWeight="bold", color=CRITICAL).encode(x=xs, y=ys, text="label:N"))

    return _base(alt.layer(*layers).properties(height=400))


def kpi_trend(kpis: pd.DataFrame, day_start: datetime, events: list[dict]) -> alt.LayerChart:
    """Handover success per ROP with the target line, change markers and a hover readout."""
    df = kpis[["rop_start", "ho_sr_pct", "drop_rate_pct"]].assign(t=lambda d: [_at(day_start, s) for s in d["rop_start"]])
    lo = min(HO_CRITICAL_PCT - 5, math.floor(df["ho_sr_pct"].min()) - 3)
    x = alt.X("t:T", title=None, axis=alt.Axis(format="%H:%M", tickCount=8, grid=False))
    # Every layer shares this scale; otherwise Vega-Lite unions in a zero-based default.
    y_scale = alt.Scale(domain=[lo, 100.5], nice=False, clamp=True, zero=False)
    y = alt.Y("ho_sr_pct:Q", title="HO success %", scale=y_scale, axis=alt.Axis(tickCount=5))

    target = alt.Chart(pd.DataFrame({"y": [HO_TARGET_PCT]})).mark_rule(
        color=INK_MUTED, strokeDash=[3, 3], strokeWidth=1).encode(y=alt.Y("y:Q", scale=y_scale))
    target_label = alt.Chart(pd.DataFrame({"y": [HO_TARGET_PCT], "t": [df["t"].min()]})).mark_text(
        align="left", baseline="top", dx=2, dy=4, fontSize=10, color=INK_MUTED, text=f"target {HO_TARGET_PCT:.0f}%").encode(
        x="t:T", y=alt.Y("y:Q", scale=y_scale))

    line = alt.Chart(df).mark_line(color=SERIES, strokeWidth=2, interpolate="monotone").encode(x=x, y=y)

    hover = alt.selection_point(fields=["t"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    hits = alt.Chart(df).mark_point(opacity=0, size=400).encode(
        x=x, y=y,
        tooltip=[alt.Tooltip("rop_start:N", title="ROP"),
                 alt.Tooltip("ho_sr_pct:Q", title="HO success %", format=".1f"),
                 alt.Tooltip("drop_rate_pct:Q", title="Drop rate %", format=".2f")],
    ).add_params(hover)
    cross = alt.Chart(df).mark_rule(color=INK_MUTED, strokeWidth=1).encode(x=x).transform_filter(hover)
    dot = alt.Chart(df).mark_circle(size=70, color=SERIES, stroke="#0e161d", strokeWidth=2).encode(
        x=x, y=y).transform_filter(hover)

    layers = [target, target_label, line, hits, cross, dot]
    if events:
        edf = pd.DataFrame([dict(e, t=_at(day_start, e["time"])) for e in events])
        layers.append(alt.Chart(edf).mark_rule(color=CHANGE, strokeWidth=1.5, strokeDash=[2, 2]).encode(
            x="t:T", tooltip=[alt.Tooltip("time:N", title="Time"), alt.Tooltip("label:N", title="Change")]))
        # Labels near the right edge go on the left of their marker so they stay inside the plot.
        late = edf["t"] > df["t"].min() + (df["t"].max() - df["t"].min()) * 0.6
        for subset, align, dx in ((edf[~late], "left", 4), (edf[late], "right", -4)):
            if not subset.empty:
                layers.append(alt.Chart(subset).mark_text(
                    align=align, baseline="top", dx=dx, fontSize=10, color=INK, y=4).encode(x="t:T", text="label:N"))

    return _base(alt.layer(*layers).properties(height=240))
