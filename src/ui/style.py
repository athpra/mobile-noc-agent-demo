"""
Page styling and the small HTML panels Streamlit has no widget for: the
header, the investigation progress strip, the approval summary and the
alarm list. Every dynamic value is escaped before it goes into HTML.
"""

from __future__ import annotations

from html import escape

import streamlit as st

CSS = """
<style>
:root {
  --noc-bg: #0e161d;
  --noc-panel: #15212a;
  --noc-panel-2: #1a2833;
  --noc-line: #253744;
  --noc-ink: #e2eaef;
  --noc-muted: #8fa1ad;
  --noc-accent: #42c7a6;
  --noc-good: #0ca30c;
  --noc-warning: #fab219;
  --noc-serious: #ec835a;
  --noc-critical: #d03b3b;
}
.stApp {
  background:
    radial-gradient(1200px 500px at 85% -10%, rgba(66, 199, 166, 0.08), transparent 60%),
    radial-gradient(900px 400px at -10% 0%, rgba(57, 135, 229, 0.07), transparent 60%),
    var(--noc-bg);
}
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1600px; }
section[data-testid="stSidebar"] { background: #0b1218; border-right: 1px solid var(--noc-line); }

/* metric tiles */
div[data-testid="stMetric"] {
  background: linear-gradient(180deg, var(--noc-panel-2), var(--noc-panel));
  border: 1px solid var(--noc-line) !important;
  border-radius: 12px; padding: 12px 14px 8px;
}
div[data-testid="stMetricLabel"] p { color: var(--noc-muted); font-size: 0.78rem; letter-spacing: 0.04em; text-transform: uppercase; }
div[data-testid="stMetricValue"] { font-size: 1.65rem; font-weight: 600; font-variant-numeric: tabular-nums; }

/* bordered containers, expanders, tabs */
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; }
div[data-testid="stExpander"] details { border: 1px solid var(--noc-line); border-radius: 10px; background: rgba(21, 33, 42, 0.6); }
div[data-testid="stExpander"] summary p { font-family: "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: 0.82rem; }
button[data-baseweb="tab"] p { font-size: 0.9rem; font-weight: 500; }
div[data-testid="stChatMessage"] { background: transparent; padding: 0.4rem 0; }
.stButton button { border-radius: 10px; }
section[data-testid="stSidebar"] .stButton button { text-align: left; justify-content: flex-start; }

/* header */
.noc-hero { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 18px 22px; margin-bottom: 18px; border: 1px solid var(--noc-line); border-radius: 16px;
  background: linear-gradient(120deg, rgba(66, 199, 166, 0.10), rgba(21, 33, 42, 0.85) 45%, rgba(57, 135, 229, 0.10)); }
.noc-hero .brand { display: flex; align-items: center; gap: 14px; }
.noc-hero .logo { width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
  background: rgba(66, 199, 166, 0.14); border: 1px solid rgba(66, 199, 166, 0.35); color: var(--noc-accent); }
.noc-hero h1 { font-size: 1.45rem; font-weight: 650; margin: 0; padding: 0; color: var(--noc-ink); letter-spacing: -0.01em; }
.noc-hero .sub { color: var(--noc-muted); font-size: 0.88rem; margin-top: 2px; }
.noc-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.noc-pill { display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px;
  border: 1px solid var(--noc-line); background: rgba(14, 22, 29, 0.6); font-size: 0.78rem; color: var(--noc-ink); white-space: nowrap; }
.noc-pill .k { color: var(--noc-muted); }
.noc-pill code { background: none; color: var(--noc-ink); padding: 0; font-size: 0.76rem; }
.noc-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--noc-good); box-shadow: 0 0 0 3px rgba(12, 163, 12, 0.25);
  animation: noc-pulse 2s ease-in-out infinite; }
.noc-dot.off { background: var(--noc-muted); box-shadow: none; animation: none; }
@keyframes noc-pulse { 50% { box-shadow: 0 0 0 6px rgba(12, 163, 12, 0.05); } }

/* section titles */
.noc-h { display: flex; align-items: baseline; justify-content: space-between; margin: 4px 0 8px; }
.noc-h span { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--noc-muted); font-weight: 600; }
.noc-h small { color: var(--noc-muted); font-size: 0.78rem; }

/* investigation progress */
.noc-steps { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; margin: 0 0 14px; }
.noc-step { border: 1px solid var(--noc-line); border-radius: 10px; padding: 8px 9px 7px; background: rgba(21, 33, 42, 0.55); min-width: 0; }
.noc-step .n { font-size: 0.68rem; color: var(--noc-muted); letter-spacing: 0.06em; text-transform: uppercase; }
.noc-step .l { font-size: 0.8rem; color: var(--noc-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.noc-step .bar { height: 3px; border-radius: 2px; margin-top: 6px; background: var(--noc-line); }
.noc-step.done { border-color: rgba(66, 199, 166, 0.45); }
.noc-step.done .bar { background: var(--noc-accent); }
.noc-step.active { border-color: var(--noc-warning); background: rgba(250, 178, 25, 0.08); }
.noc-step.active .bar { background: var(--noc-warning); }
.noc-step.stopped { border-color: var(--noc-critical); }
.noc-step.stopped .bar { background: var(--noc-critical); }
@media (max-width: 900px) { .noc-steps { grid-template-columns: repeat(4, 1fr); } }

/* approval card */
.noc-approval { border: 1px solid rgba(250, 178, 25, 0.55); border-radius: 14px; padding: 16px 18px 6px;
  background: linear-gradient(180deg, rgba(250, 178, 25, 0.08), rgba(21, 33, 42, 0.9) 55%); }
.noc-approval .tag { display: inline-block; font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 700;
  color: #1b1405; background: var(--noc-warning); border-radius: 6px; padding: 2px 8px; }
.noc-approval h3 { margin: 8px 0 2px; padding: 0; font-size: 1.15rem; }
.noc-approval .mo { color: var(--noc-muted); font-family: ui-monospace, Menlo, monospace; font-size: 0.74rem; word-break: break-all; }
.noc-change { display: flex; align-items: center; gap: 12px; margin: 14px 0; flex-wrap: wrap; }
.noc-change .attr { font-family: ui-monospace, Menlo, monospace; color: var(--noc-muted); font-size: 0.85rem; }
.noc-change .v { font-family: ui-monospace, Menlo, monospace; font-size: 1.3rem; font-weight: 650; padding: 4px 12px; border-radius: 8px; }
.noc-change .old { background: rgba(208, 59, 59, 0.14); color: #f0a0a0; text-decoration: line-through; text-decoration-thickness: 1px; }
.noc-change .new { background: rgba(12, 163, 12, 0.16); color: #9be39b; }
.noc-change .arrow { color: var(--noc-muted); font-size: 1.2rem; }
.noc-reason { font-size: 0.9rem; color: var(--noc-ink); margin-bottom: 10px; }
.noc-checks { display: flex; flex-direction: column; gap: 6px; margin: 8px 0 10px; }
.noc-check { display: grid; grid-template-columns: 74px 1fr; gap: 10px; align-items: start; font-size: 0.85rem; }
.noc-badge { display: inline-flex; align-items: center; justify-content: center; gap: 4px; font-size: 0.68rem; font-weight: 700;
  letter-spacing: 0.05em; border-radius: 6px; padding: 2px 6px; border: 1px solid; white-space: nowrap; }
.noc-badge.pass { color: #8fdc8f; border-color: rgba(12, 163, 12, 0.6); background: rgba(12, 163, 12, 0.12); }
.noc-badge.warn { color: var(--noc-warning); border-color: rgba(250, 178, 25, 0.6); background: rgba(250, 178, 25, 0.10); }
.noc-badge.fail { color: #f19a9a; border-color: rgba(208, 59, 59, 0.7); background: rgba(208, 59, 59, 0.12); }
.noc-check b { color: var(--noc-ink); font-weight: 600; }
.noc-check span.d { color: var(--noc-muted); }

/* alarms */
.noc-alarms { display: flex; flex-direction: column; gap: 6px; }
.noc-alarm { display: grid; grid-template-columns: 78px 1fr auto; gap: 10px; align-items: center; padding: 8px 10px;
  border: 1px solid var(--noc-line); border-left-width: 3px; border-radius: 8px; background: rgba(21, 33, 42, 0.55); font-size: 0.84rem; }
.noc-alarm .sev { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.05em; }
.noc-alarm .mo { color: var(--noc-muted); font-family: ui-monospace, Menlo, monospace; font-size: 0.76rem; }
.noc-alarm .t { color: var(--noc-muted); font-variant-numeric: tabular-nums; font-size: 0.78rem; }
.noc-alarm.cleared { opacity: 0.55; }

/* empty state */
.noc-empty { border: 1px dashed var(--noc-line); border-radius: 14px; padding: 22px; text-align: center; color: var(--noc-muted); }
.noc-empty b { color: var(--noc-ink); display: block; font-size: 1.02rem; margin-bottom: 4px; }

/* audit */
.noc-audit { font-family: ui-monospace, Menlo, monospace; font-size: 0.76rem; color: var(--noc-muted); line-height: 1.6; }
.noc-audit b { color: var(--noc-ink); font-weight: 600; }
</style>
"""

ANTENNA_SVG = (
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 12v9"/><path d="M8.5 21h7"/><circle cx="12" cy="10" r="1.6"/>'
    '<path d="M8.2 6.2a5.4 5.4 0 0 0 0 7.6"/><path d="M15.8 6.2a5.4 5.4 0 0 1 0 7.6"/>'
    '<path d="M5.4 3.4a9.4 9.4 0 0 0 0 13.2"/><path d="M18.6 3.4a9.4 9.4 0 0 1 0 13.2"/></svg>'
)

CHECK_BADGES = {"pass": "✓ PASS", "warn": "! WARN", "fail": "✕ FAIL"}
SEVERITY_COLORS = {"CRITICAL": "#d03b3b", "MAJOR": "#ec835a", "MINOR": "#fab219", "WARNING": "#8fa1ad"}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    html(f'<div class="noc-h"><span>{escape(title)}</span><small>{escape(note)}</small></div>')


def header(network_time: str, date_label: str, model: str | None, sandbox: str, live: bool) -> None:
    pills = [
        f'<span class="noc-pill"><span class="noc-dot{"" if live else " off"}"></span>'
        f'<span class="k">Network time</span> {escape(network_time)} · {escape(date_label)}</span>',
        f'<span class="noc-pill"><span class="k">Model</span> <code>{escape(model or "not set")}</code></span>',
        f'<span class="noc-pill"><span class="k">Sandbox</span> <code>{escape(sandbox)}</code></span>',
        '<span class="noc-pill"><span class="k">RAN</span> 5G SA · n78</span>',
    ]
    html(
        '<div class="noc-hero"><div class="brand">'
        f'<div class="logo">{ANTENNA_SVG}</div>'
        '<div><h1>Mobile NOC Agent</h1>'
        '<div class="sub">Agentic RAN troubleshooting · evidence from FM/PM/CM · every change approved by an engineer</div>'
        f'</div></div><div class="noc-pills">{"".join(pills)}</div></div>'
    )


def progress(steps: list[tuple[str, str]], target=None) -> None:
    """steps: (label, state) with state in todo | done | active | stopped.
    `target` is a placeholder (st.empty()) to redraw in place while the agent runs."""
    cells = "".join(
        f'<div class="noc-step {state}"><div class="n">Step {i}</div>'
        f'<div class="l" title="{escape(label)}">{escape(label)}</div><div class="bar"></div></div>'
        for i, (label, state) in enumerate(steps, start=1)
    )
    (target or st).markdown(f'<div class="noc-steps" role="list" aria-label="Investigation progress">{cells}</div>',
                            unsafe_allow_html=True)


def approval_summary(p: dict) -> None:
    checks = "".join(
        f'<div class="noc-check"><span class="noc-badge {escape(c["status"])}">'
        f'{CHECK_BADGES.get(c["status"], escape(c["status"]))}</span>'
        f'<div><b>{escape(c["name"])}</b> <span class="d">{escape(str(c["detail"]))}</span></div></div>'
        for c in p["checks"]
    )
    html(
        '<div class="noc-approval">'
        '<span class="tag">Approval needed</span>'
        f'<h3>Change request on {escape(p["cell_id"])}</h3>'
        f'<div class="mo">{escape(p["managed_object"])}</div>'
        '<div class="noc-change">'
        f'<span class="attr">{escape(p["attribute"])}</span>'
        f'<span class="v old">{escape(str(p["current_value"]))}</span><span class="arrow">→</span>'
        f'<span class="v new">{escape(str(p["proposed_value"]))}</span></div>'
        f'<div class="noc-reason"><b>Agent\'s reason.</b> {escape(p["reason"])}</div>'
        f'<div class="noc-checks">{checks}</div></div>'
    )


def alarm_list(alarms: list[dict]) -> None:
    if not alarms:
        html('<div class="noc-empty">No alarms.</div>')
        return
    rows = []
    for a in sorted(alarms, key=lambda a: (a["state"] != "ACTIVE", a["raised_at"]), reverse=False):
        color = SEVERITY_COLORS.get(a["severity"], "#8fa1ad")
        cleared = a["state"] != "ACTIVE"
        when = f'{a["raised_at"]}–{a["cleared_at"]}' if cleared else f'since {a["raised_at"]}'
        rows.append(
            f'<div class="noc-alarm{" cleared" if cleared else ""}" style="border-left-color:{color}">'
            f'<span class="sev" style="color:{color}">● {escape(a["severity"])}</span>'
            f'<div>{escape(a["specific_problem"])}<div class="mo">{escape(a["managed_object"])}</div></div>'
            f'<span class="t">{escape(when)}</span></div>'
        )
    html(f'<div class="noc-alarms">{"".join(rows)}</div>')


def empty_state(title: str, body: str) -> None:
    html(f'<div class="noc-empty"><b>{escape(title)}</b>{escape(body)}</div>')
