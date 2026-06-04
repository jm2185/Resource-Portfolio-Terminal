#!/usr/bin/env python3
"""
commodityex_tui.py — the CommodityEx research cockpit (Pillar 3).

A keyboard-first Textual terminal you can live in for hours doing deep, high-conviction work on
silver/junior names (AGA.V, GMX.TO, GROY, URC.TO). It is a **pure consumer** of the engine: it
never computes valuation / what-if / regime / config itself. It reads ``/state``,
``/config/scenarios``, ``/config/pending`` and ``/decisions``; it POSTs ``/action/whatif``,
``/config/scenario``, ``/config/confirm`` and — so agents always know what you're looking at —
``/ui/state``. Agents steer it back via the ``ui_command`` stream on ``/state``.

Layout (a serious trading desk, not a dev tool)::

    ┌ Header (title · clock) ───────────────────────────────────────────────────────────┐
    │ STATUS  REGIME · MRI gauge · Ag/GSR · book HEALTH · ◆FOCUS · SCEN · LIVE           │
    │ TAPE    dense cross-asset macro strip, coloured by risk-on / risk-off bias         │
    ├──────────────┬─────────────────────────────────────────────┬──────────────────────┤
    │ WATCHLIST    │  Book · Live What-If · Regime · Dossier      │  SIGNALS             │
    │ health bars  │  (the work surface)                          │  agent stream /      │
    │ BOOK HEALTH  │                                              │  proposals / actions │
    ├──────────────┴─────────────────────────────────────────────┴──────────────────────┤
    │ › command bar  (/focus · /whatif · /scenario · /confirm · /dossier)                │
    │ Footer (keys)                                                                      │
    └───────────────────────────────────────────────────────────────────────────────────┘

Run (engine on :8000):  pip install textual && python commodityex_tui.py
Keys: q quit · r refresh · 1-4 tabs · w what-if · c confirm pending · / command bar
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                                  # health/score -> colour (shared visual language)
    from conviction_health import health_color, quality_color
except Exception:                                     # pragma: no cover - graceful if module moves
    def health_color(_): return "#C0C0C8"
    def quality_color(_): return "#C0C0C8"
try:                                                  # shared input parsing only (NOT business logic)
    from valuation_actions import parse_overrides
except Exception:                                     # pragma: no cover
    def parse_overrides(s): return {}

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Button, DataTable, Footer, Header, Input, Markdown,
                             Static, TabbedContent, TabPane)

ENGINE = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000")
SESSION = os.environ.get("CEX_SESSION", "commodityex")   # tmux session for one-key agent dispatch
REFRESH_SECONDS = 3.0

# ---- the amber / silver / gold palette (one source of truth) ---------------------------
AMBER  = "#FFB000"   # primary accent / focus
GOLD   = "#E6C200"   # headline values
SILVER = "#C0C0C8"   # body text
DIM    = "#8C8C92"   # secondary / hints
GREEN  = "#69F0AE"   # good / risk-on / agent-live
RED    = "#FF5252"   # bad / risk-off
ORANGE = "#FF9800"   # warn
BORDER = "#222226"

_ROLE_GLYPH = {"spear": "◆", "ballast": "●"}
_ARCH_SHORT = {                                       # compact archetype labels for the dense book
    "junior_explorer": "EXPLORER", "spear": "EXPLORER", "explorer": "EXPLORER",
    "asset_light_yield": "ROYALTY", "royalty": "ROYALTY",
    "producer": "PRODUCER", "developer": "DEVELOPER", "cyclical": "CYCLICAL",
    "passive_holdco": "HOLDCO", "_default": "—",
}


# ======================================================================================
#  Engine transport (tiny, resilient — the cockpit must never crash on a blip)
# ======================================================================================
def _get(path: str, timeout: float = 1.5):
    try:
        with urllib.request.urlopen(f"{ENGINE}{path}", timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _post(path: str, payload: dict, timeout: float = 6.0):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{ENGINE}{path}", data=data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"engine unreachable ({exc})"}


# ======================================================================================
#  Pure formatting helpers (rich only — no engine math, unit-testable on their own)
# ======================================================================================
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fmt(x, spec="{:.1f}"):
    v = _num(x)
    return spec.format(v) if v is not None else "—"


def _score(pillar):
    """A pillar may arrive as {'score': n, ...} or as a bare number."""
    if isinstance(pillar, dict):
        pillar = pillar.get("score")
    return _num(pillar)


def _bar(score, width=10):
    """A health-coloured 0-10 meter."""
    f = _num(score)
    if f is None:
        return Text("░" * width, style=DIM)
    f = max(0.0, min(1.0, f / 10.0))
    filled = round(f * width)
    return Text("▰" * filled + "▱" * (width - filled), style=health_color(score))


def _mri_gauge(mri, width=12):
    """0-100 MRI meter; green (deploy) <45, amber 45-65, red (preserve) >65."""
    v = _num(mri)
    if v is None:
        return Text("░" * width, style=DIM)
    style = GREEN if v < 45 else (AMBER if v < 65 else RED)
    filled = round(max(0.0, min(1.0, v / 100.0)) * width)
    return Text("▰" * filled + "▱" * (width - filled), style=style)


def bias_color(bias):
    return {"risk_on": GREEN, "risk_off": ORANGE, "neutral": SILVER}.get(bias, SILVER)


def _arch_short(archetype, code=None):
    a = str(archetype or "_default").lower()
    if a in _ARCH_SHORT:
        return _ARCH_SHORT[a]
    if code and len(str(code)) <= 8:
        return str(code).upper()
    return a.replace("_", " ").upper()[:9]


def _role_glyph(ticker, nodes):
    role = str((nodes.get(ticker, {}) or {}).get("role", "")).lower()
    for k, g in _ROLE_GLYPH.items():
        if k in role:
            return g
    return "·"


def _upside_text(basket):
    """The asymmetric-upside indicator from the V pillar (bull-vs-price for explorers,
    gap-to-fair-value for cash-flow names)."""
    v = basket.get("pillars", {}).get("V", {}) if isinstance(basket.get("pillars"), dict) else {}
    up = _num(v.get("upside_pct"))
    if up is None:
        return Text("—", style=DIM)
    style = GREEN if up >= 40 else (AMBER if up >= 0 else RED)
    return Text(f"{up:+.0f}%", style=style)


def _floor_edge(basket):
    """REP-floor margin of safety. BELOW = trading under liquidation (accumulate); otherwise the
    distance price would fall to reach the floor — small = well-protected (green)."""
    v = basket.get("pillars", {}).get("V", {}) if isinstance(basket.get("pillars"), dict) else {}
    phi = _num(v.get("floor_coverage"))
    dtf = _num(v.get("downside_to_floor_pct"))
    if phi is not None and phi >= 1.0:
        return Text("BELOW▼", style=GREEN)
    if dtf is None:
        return Text("—", style=DIM) if phi is None else Text(f"φ{phi:.2f}", style=SILVER)
    style = GREEN if dtf <= 15 else (AMBER if dtf <= 35 else ORANGE)
    return Text(f"-{dtf:.0f}%", style=style)


def _gate_text(basket, short=True):
    """Forensic gate: clean, or capped with the reason (red on a severe cap, amber when floor-relaxed)."""
    g = basket.get("gate", {}) if isinstance(basket.get("gate"), dict) else {}
    if not g.get("applied"):
        return Text("clean", style=GREEN)
    cap = _num(g.get("cap"))
    style = RED if (cap is not None and cap <= 5.0) else AMBER
    reason = str(g.get("reason", "capped"))
    return Text(("⚠ " + (reason if not short else reason.split(";")[0]))[: (13 if short else 60)], style=style)


def _delta_bar(pct, width=21):
    """A centred ± meter: green grows right for upside, red grows left for downside."""
    cells = ["·"] * width
    mid = width // 2
    cells[mid] = "│"
    out = Text()
    v = _num(pct)
    if v is None:
        return Text("".join(cells), style=DIM)
    frac = max(-1.0, min(1.0, v / 50.0))     # ±50% saturates the bar
    n = round(abs(frac) * (mid))
    style = GREEN if v >= 0 else RED
    if v >= 0:
        for i in range(mid + 1, min(width, mid + 1 + n)):
            cells[i] = "▰"
    else:
        for i in range(max(0, mid - n), mid):
            cells[i] = "▰"
    for i, ch in enumerate(cells):
        out.append(ch, style=(style if ch == "▰" else (AMBER if ch == "│" else DIM)))
    return out


def _ladder(points, width=34):
    """Place named price points on a single line (margin-of-safety at a glance).
    points: list of (glyph, value, style). Returns a (bar, legend) Text pair."""
    vals = [(g, _num(v), s) for g, v, s in points if _num(v) is not None]
    bar = Text("─" * width, style=BORDER)
    if len(vals) < 2:
        return bar, Text("insufficient price points", style=DIM)
    lo = min(v for _, v, _ in vals)
    hi = max(v for _, v, _ in vals)
    span = max(1e-9, hi - lo)
    chars = ["─"] * width
    styles = [BORDER] * width
    for g, v, s in vals:                              # earlier points yield to later on collision
        idx = int(round((v - lo) / span * (width - 1)))
        chars[idx] = g
        styles[idx] = s
    bar = Text()
    for ch, st in zip(chars, styles):
        bar.append(ch, style=st)
    legend = Text()
    for i, (g, v, s) in enumerate(vals):
        if i:
            legend.append("  ", style=DIM)
        legend.append(f"{g} {v:.2f}", style=s)
    return bar, legend


def _macro_tape(signals, limit=8):
    """A dense one-line cross-asset strip, each signal coloured by its regime bias."""
    t = Text()
    for i, s in enumerate(signals[:limit]):
        if i:
            t.append("  ", style=DIM)
        t.append(f"{s.get('label','?')} ", style=DIM)
        t.append(str(s.get("display", "—")), style=bias_color(s.get("bias")))
    return t if signals else Text("waiting for macro tape…", style=DIM)


def _rel_age(ts):
    if not ts:
        return ""
    secs = max(0, int(time.time() - float(ts)))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


# ======================================================================================
#  The cockpit
# ======================================================================================
class Cockpit(App):
    TITLE = "CommodityEx"
    SUB_TITLE = "research cockpit"

    CSS = """
    Screen { background: #08080A; color: #D0D0D5; layers: base overlay; }
    Header { background: #0E0E10; color: #E6C200; text-style: bold; }
    #statusband { height: 1; padding: 0 1; background: #0E0E10; color: #C0C0C8; }
    #tapeband   { height: 1; padding: 0 1; background: #0B0B0D; color: #C0C0C8; border-bottom: solid #222226; }

    #body { height: 1fr; }
    #watch   { width: 30; border-right: solid #222226; padding: 0 1; }
    #signals { width: 36; border-left: solid #222226; padding: 0 1; }
    #tabs { width: 1fr; }

    .railtitle  { color: #FFB000; text-style: bold; }
    .railsub    { color: #8C8C92; text-style: bold; margin-top: 1; }
    #healthmini { border-top: solid #222226; margin-top: 1; padding-top: 1; }

    DataTable { height: 1fr; background: #08080A;
                scrollbar-size-horizontal: 1; scrollbar-size-vertical: 1;
                scrollbar-background: #0B0B0D; scrollbar-color: #222226; scrollbar-color-hover: #FFB000; }
    DataTable > .datatable--cursor { background: #1A1A1F; }
    DataTable > .datatable--header { color: #FFB000; text-style: bold; }
    VerticalScroll { scrollbar-size-vertical: 1; scrollbar-background: #0B0B0D;
                     scrollbar-color: #222226; scrollbar-color-hover: #FFB000; }
    #book_detail { height: auto; min-height: 4; border-top: solid #222226; padding: 1; color: #C0C0C8; }

    Input  { border: tall #222226; background: #0E0E10; }
    Input:focus { border: tall #FFB000; }
    Button { background: #121214; color: #E6C200; border: tall #222226; height: 3; }
    Button:hover { border: tall #FFB000; }
    Button.knob { color: #C0C0C8; min-width: 9; }
    .row { height: auto; }

    #wf_result  { height: 1fr; border: round #222226; padding: 1; }
    #wf_history { height: auto; color: #8C8C92; }
    #wf_status  { height: auto; color: #C0C0C8; }
    #wf_hint    { height: auto; color: #8C8C92; }
    #regime  { padding: 0 1; }
    #dossier_list { width: 34; border-right: solid #222226; padding: 0 1; color: #C0C0C8; }
    #dossier_body { width: 1fr; padding: 0 1; }
    #dossier_open { width: 34; }

    #cmdbar { dock: bottom; height: 3; border: tall #222226; background: #0B0B0D; }
    #cmdbar:focus { border: tall #FFB000; }
    Footer { background: #0E0E10; }

    .glow { border: round #FF9800; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("1", "tab('book')", "Book"),
        ("2", "tab('whatif')", "What-If"),
        ("3", "tab('regime_tab')", "Regime"),
        ("4", "tab('dossier_tab')", "Dossier"),
        ("w", "whatif_focus", "What-If"),
        ("c", "confirm", "Confirm"),
        ("a", "ask('analyst')", "Ask analyst"),
        ("b", "ask('bear')", "Bear case"),
        ("x", "ask('dossier')", "Dossier"),
        ("slash", "cmd", "Command"),
        ("colon", "cmd", "Command"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._state: dict = {}
        self._scenarios: list = []
        self._pending: list = []
        self._decisions: list = []
        self._baskets_by_ticker: dict = {}
        self._row_index: dict = {}
        self._book_sig = None
        self._focus: str | None = None
        self._last_reported: tuple | None = None
        self._active_scenario: str | None = None
        self._wf_source = "you"
        self._wf_hist: list = []
        self._last_seq = 0
        self._act_seq = 0
        self._tick = 0
        self._suppress_report = False

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("connecting to engine…", id="statusband")
        yield Static("", id="tapeband")
        with Horizontal(id="body"):
            with VerticalScroll(id="watch"):
                yield Static("WATCHLIST", classes="railtitle")
                yield Static("…", id="watchbody")
                with Vertical(id="healthmini"):
                    yield Static("BOOK HEALTH", classes="railtitle")
                    yield Static("…", id="healthbody")
            with TabbedContent(id="tabs", initial="book"):
                with TabPane("Book", id="book"):
                    yield DataTable(id="booktbl", zebra_stripes=True, cursor_type="row")
                    yield Static("Select a name to ground agents and see its price ladder.",
                                 id="book_detail")
                with TabPane("Live What-If", id="whatif"):
                    with Horizontal(classes="row"):
                        yield Input(placeholder="ticker — blank uses the focused name", id="wf_ticker")
                        yield Input(placeholder="load a saved scenario by name…", id="wf_scenario")
                    yield Input(placeholder="overrides:  silver=+5 ry=-0.5 peer=+20%   (Enter to run)",
                                id="wf_overrides")
                    with Horizontal(classes="row"):
                        yield Button("Ag +5", id="k_ag_up", classes="knob")
                        yield Button("Ag -5", id="k_ag_dn", classes="knob")
                        yield Button("RY -0.5", id="k_ry", classes="knob")
                        yield Button("Vol +20%", id="k_vol", classes="knob")
                        yield Button("Peer +20%", id="k_peer", classes="knob")
                        yield Button("MRI -10", id="k_mri", classes="knob")
                        yield Button("Clear", id="k_clear", classes="knob")
                    with Horizontal(classes="row"):
                        yield Button("▶ Run What-If", id="wf_run", variant="warning")
                        yield Input(placeholder="save scenario as…", id="wf_name")
                        yield Button("Save", id="wf_save")
                    yield Static("Enter a ticker + overrides, then Run. Knobs append to the override line.",
                                 id="wf_result")
                    yield Static("", id="wf_history")
                    yield Static("", id="wf_status")
                    yield Static("", id="wf_hint")
                with TabPane("Regime", id="regime_tab"):
                    yield VerticalScroll(Static("…", id="regime"))
                with TabPane("Dossier", id="dossier_tab"):
                    with Horizontal():
                        with Vertical(id="dossier_list"):
                            yield Static("DOSSIERS", classes="railtitle")
                            yield Static("…", id="dossier_index")
                            yield Input(placeholder="open #  or  ticker", id="dossier_open")
                        yield VerticalScroll(Markdown("", id="dossier_body"))
            with VerticalScroll(id="signals"):
                yield Static("SIGNALS", classes="railtitle")
                yield Static("no agent activity yet", id="signalbody")
        yield Input(placeholder="/ command   —   /focus AGA.V · /whatif AGA.V silver=+5 · /scenario name · /confirm 3 · /dossier AGA.V",
                    id="cmdbar")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#booktbl", DataTable)
        for c, w in (("", 3), ("TICKER", 7), ("ARCH", 8), ("R", 4), ("BAND", 14),
                     ("T", 3), ("Q", 3), ("V", 3), ("UP%", 5), ("FLOOR", 6),
                     ("GATE", 13), ("DIRECTIVE", 22)):
            t.add_column(c, key=c or "role", width=w)
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.refresh_data()

    # ------------------------------------------------------------------ polling
    def action_refresh(self) -> None:
        self.refresh_data()

    @work(thread=True, exclusive=True, group="poll")
    def refresh_data(self) -> None:
        state = _get("/state")
        scenarios = _get("/config/scenarios")
        pending = _get("/config/pending")
        decisions = _get("/decisions") if (self._tick % 4 == 0 or not self._decisions) else None
        self._tick += 1
        self.call_from_thread(self._apply, state, scenarios, pending, decisions)

    def _status(self, text) -> None:
        """Transient feedback line in the What-If sandbox (never clobbered by the poll)."""
        self.query_one("#wf_status", Static).update(text)

    def _apply(self, state, scenarios, pending, decisions) -> None:
        if not state:
            self.query_one("#statusband", Static).update(
                Text("⚠ engine offline — start it (ops window · run_engine)  ", style=f"bold {ORANGE}"))
            return
        self._state = state
        if scenarios is not None:
            self._scenarios = (scenarios or {}).get("scenarios", []) or []
        if pending is not None:
            self._pending = (pending or {}).get("pending", []) or []
        if decisions is not None:
            self._decisions = (decisions or {}).get("decisions", []) or []

        conv = state.get("conviction_mode", {}) or {}
        baskets = conv.get("baskets", []) or []
        self._baskets_by_ticker = {b.get("ticker"): b for b in baskets}

        self._render_status(state, conv)
        self._render_tape(state)
        self._render_watch(state, baskets)
        self._render_health(state)
        self._render_book(state, baskets)
        self._render_regime(state)
        self._render_signals(state)
        self._render_dossier_index()
        self._handle_agent_command(state)

        names = [s.get("name") for s in self._scenarios]
        if names:
            self.query_one("#wf_hint", Static).update(
                Text("saved scenarios: ", style=DIM) + Text(" · ".join(names), style=SILVER))

    # ------------------------------------------------------------------ header
    def _render_status(self, state, conv) -> None:
        ctx = conv.get("context", {}) or {}
        metrics = state.get("metrics", {}) or {}
        hr = state.get("health_radar", {}) or {}
        regime = ctx.get("regime") or state.get("macro_tape", {}).get("net_tilt", "—")
        mri = state.get("mri")
        spot = (metrics.get("Spot_Ag", {}) or {}).get("value")
        gsr = (metrics.get("GSR", {}) or {}).get("value")
        dxy_mom = (metrics.get("DXY_MOMENTUM", {}) or {}).get("value")
        health = hr.get("health_rating")
        status = state.get("status", "—")
        focus = self._focus or "—"

        sep = Text("  │  ", style=BORDER)
        line = Text()
        line.append("REGIME ", style=DIM); line.append(str(regime), style=f"bold {bias_color('risk_off' if 'OFF' in str(regime).upper() else ('risk_on' if 'ON' in str(regime).upper() else 'neutral'))}")
        line.append_text(sep)
        line.append("MRI ", style=DIM); line.append(_fmt(mri, "{:.0f}"), style=GOLD); line.append(" "); line.append_text(_mri_gauge(mri))
        line.append_text(sep)
        line.append("Ag ", style=DIM); line.append(f"${_fmt(spot, '{:.2f}')}", style=SILVER)
        line.append("  GSR ", style=DIM); line.append(_fmt(gsr, "{:.0f}"), style=SILVER)
        if _num(dxy_mom) is not None:
            arrow = "▲" if _num(dxy_mom) > 0 else "▼"
            line.append(f"  DXY{arrow}", style=(ORANGE if _num(dxy_mom) > 0 else GREEN))
        line.append_text(sep)
        line.append("HEALTH ", style=DIM); line.append(f"{_fmt(health)}/10", style=health_color(health))
        line.append_text(sep)
        line.append("◆ ", style=AMBER); line.append(str(focus), style=f"bold {AMBER}")
        line.append_text(sep)
        line.append("SCEN ", style=DIM); line.append(self._active_scenario or "—", style=GOLD)
        line.append_text(sep)
        line.append(str(status), style=(GREEN if status == "LIVE" else ORANGE))
        self.query_one("#statusband", Static).update(line)

    def _render_tape(self, state) -> None:
        tape = state.get("macro_tape", {}) or {}
        sig = tape.get("signals", []) or []
        line = _macro_tape(sig)
        on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
        line.append("   ", style=DIM)
        line.append(f"on {on}", style=GREEN); line.append(" / ", style=DIM); line.append(f"off {off}", style=ORANGE)
        self.query_one("#tapeband", Static).update(line)

    # ------------------------------------------------------------------ watch rail
    def _render_watch(self, state, baskets) -> None:
        nodes = state.get("nodes", {}) or {}
        if not baskets:
            self.query_one("#watchbody", Static).update(Text("waiting for baskets…", style=DIM))
            return
        out = Text()
        for i, b in enumerate(baskets):
            tk = str(b.get("ticker", "?"))
            r = b.get("rating")
            if i:
                out.append("\n")
            mark = "▸" if tk == self._focus else " "
            out.append(f"{mark}", style=AMBER)
            out.append(f"{_role_glyph(tk, nodes)} ", style=health_color(r))
            out.append(f"{tk:<7}", style="bold white")
            out.append(f"{_fmt(r):>4} ", style=health_color(r))
            out.append_text(_bar(r, 8))
            out.append("\n     ", style=DIM)
            out.append(f"{str(b.get('band','—'))[:14]:<14} ", style=health_color(r))
            out.append_text(_floor_edge(b))
            cat = b.get("catalysts") or []
            if cat:
                sig = _num(b.get("catalyst_signal")) or 0.0
                out.append(f"  ↯{len(cat)}", style=(GREEN if sig >= 0 else ORANGE))
        self.query_one("#watchbody", Static).update(out)

    def _render_health(self, state) -> None:
        hr = state.get("health_radar", {}) or {}
        fr = state.get("forensics", {}) or {}
        ps = state.get("portfolio_stats", {}) or {}
        health = hr.get("health_rating")
        out = Text()
        out.append("Rating ", style=DIM); out.append(f"{_fmt(health)}/10  ", style=health_color(health))
        out.append_text(_bar(health, 8)); out.append("\n")
        out.append(str(hr.get("rating_desc", "")), style=health_color(health)); out.append("\n")
        jsf = _num(fr.get("jsf_score"))
        out.append("JSF ", style=DIM); out.append(f"{_fmt(jsf)}/4", style=health_color((jsf or 0) * 2.5))
        out.append("   runway ", style=DIM); out.append(f"{_fmt(fr.get('runway'))}mo", style=SILVER); out.append("\n")
        es = _num(ps.get("expected_shortfall_95"))
        out.append("ES95 ", style=DIM)
        out.append(f"{_fmt(es)}%", style=(GREEN if (es or 0) < 5 else (AMBER if (es or 0) < 10 else RED)))
        prio = hr.get("priorities") or []
        if prio:
            out.append("\n▸ ", style=AMBER); out.append(str(prio[0].get("title", ""))[:24], style=SILVER)
        self.query_one("#healthbody", Static).update(out)

    # ------------------------------------------------------------------ book
    def _book_signature(self, baskets):
        return tuple((b.get("ticker"), b.get("rating"), b.get("band"),
                      _score(b.get("pillars", {}).get("V")), (b.get("gate") or {}).get("cap"),
                      str(b.get("directive"))) for b in baskets)

    def _render_book(self, state, baskets) -> None:
        sig = self._book_signature(baskets)
        if sig == self._book_sig:
            return                                          # nothing material changed — keep cursor steady
        self._book_sig = sig
        tbl = self.query_one("#booktbl", DataTable)
        prev = self._focus
        self._suppress_report = True
        tbl.clear()
        self._row_index = {}
        nodes = state.get("nodes", {}) or {}
        for i, b in enumerate(baskets):
            tk = str(b.get("ticker", "?"))
            r = b.get("rating")
            pillars = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
            t, q, v = _score(pillars.get("T")), _score(pillars.get("Q")), _score(pillars.get("V"))
            focus_mark = "▸" if tk == prev else " "
            tbl.add_row(
                Text(f"{focus_mark}{_role_glyph(tk, nodes)}", style=AMBER if tk == prev else health_color(r)),
                Text(tk, style="bold white"),
                Text(_arch_short(b.get("archetype"), b.get("archetype_code")), style=DIM),
                Text(_fmt(r), style=f"bold {health_color(r)}"),
                Text(str(b.get("band", "—"))[:14], style=health_color(r)),
                Text(_fmt(t), style=health_color(t)),
                Text(_fmt(q), style=health_color(q)),
                Text(_fmt(v), style=health_color(v)),
                _upside_text(b),
                _floor_edge(b),
                _gate_text(b),
                Text(str(b.get("directive", "—"))[:22], style=SILVER),
                key=tk,
            )
            self._row_index[tk] = i
        if prev in self._row_index:
            try:
                tbl.move_cursor(row=self._row_index[prev], animate=False)
            except Exception:
                pass
        elif baskets:                                       # first load -> focus the top pick
            top = state.get("conviction_mode", {}).get("top_pick") or baskets[0].get("ticker")
            self._set_focus(top, move_cursor=True, report=True)
        self._suppress_report = False
        if self._focus:
            self._render_book_detail(self._focus)

    def _render_book_detail(self, ticker) -> None:
        b = self._baskets_by_ticker.get(ticker)
        det = self.query_one("#book_detail", Static)
        if not b:
            det.update(Text("no live data for this name", style=DIM))
            return
        L = b.get("ladder", {}) or {}
        V = b.get("pillars", {}).get("V", {}) if isinstance(b.get("pillars"), dict) else {}
        rib = b.get("confidence_ribbon", {}) or {}
        bar, legend = _ladder([("F", L.get("floor"), ORANGE), ("b", L.get("bear"), RED),
                               ("●", L.get("price"), "white"), ("◆", L.get("base"), GOLD),
                               ("▲", L.get("bull"), GREEN)])
        head = Text()
        head.append(f"{ticker}  ", style=f"bold {GOLD}")
        head.append(f"{_arch_short(b.get('archetype'), b.get('archetype_code'))}  ", style=DIM)
        head.append(f"{b.get('band','—')}  ", style=health_color(b.get("rating")))
        if _num(V.get("rho")) is not None:
            head.append(f"ρ {_fmt(V.get('rho'),'{:.2f}')}  ", style=SILVER)
        head.append(f"±{_fmt(rib.get('plus_minus'),'{:.2f}')} ", style=DIM)
        head.append(f"({rib.get('quality','?')})", style=quality_color(rib.get("quality")))
        gate_line = Text("gate: ", style=DIM) + _gate_text(b, short=False)
        cat = b.get("catalysts") or []
        cat_line = Text()
        if cat:
            cat_line.append("catalysts: ", style=DIM)
            cat_line.append(" · ".join(str(c.get("headline", c.get("type", "event")))[:34] for c in cat[:3]),
                            style=SILVER)
        parts = [head, bar, legend, gate_line]
        if cat:
            parts.append(cat_line)
        parts.append(Text("→ agents are grounded on this name (POSTed to /ui/state)", style=DIM))
        det.update(Group(*parts))

    # ------------------------------------------------------------------ regime
    def _render_regime(self, state) -> None:
        tape = state.get("macro_tape", {}) or {}
        ctx = (state.get("conviction_mode", {}) or {}).get("context", {}) or {}
        mri = state.get("mri")
        regime = ctx.get("regime") or tape.get("net_tilt", "—")
        head = Text()
        head.append("REGIME  ", style=f"bold {AMBER}")
        head.append(f"{regime}", style=f"bold {bias_color('risk_off' if 'OFF' in str(regime).upper() else 'risk_on')}")
        head.append("    MRI ", style=DIM); head.append(_fmt(mri, "{:.1f}"), style=GOLD)
        head.append(" "); head.append_text(_mri_gauge(mri, 16))
        head.append("    ·  top driver: ", style=DIM)
        head.append(str(tape.get("top_mri_driver", "—")), style=SILVER)

        on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
        total = max(1, on + off)
        tug = Text("\nrisk  ")
        tug.append("▰" * round(on / total * 18), style=GREEN)
        tug.append("▱" * round(off / total * 18), style=ORANGE)
        tug.append(f"  on {on} / off {off}\n", style=DIM)

        # cross-asset macro tape table
        tt = Table(expand=True, show_edge=False, pad_edge=False, box=None)
        for col in ("SIGNAL", "VALUE", "BIAS", "READ"):
            tt.add_column(col, style=DIM, no_wrap=(col != "READ"))
        for s in tape.get("signals", []) or []:
            tt.add_row(
                Text(str(s.get("label", "?")), style=SILVER),
                Text(str(s.get("display", "—")), style=bias_color(s.get("bias"))),
                Text(str(s.get("bias", "")).replace("_", "-"), style=bias_color(s.get("bias"))),
                Text(str(s.get("read", "")), style=DIM),
            )

        # MRI decomposition bars
        dec = state.get("mri_decomposition", {}) or {}
        comps = [(k, _num(v)) for k, v in dec.items() if _num(v) is not None and k != "top_driver"]
        decg = Text("\nMRI components\n", style=f"bold {AMBER}")
        if comps:
            mx = max(abs(v) for _, v in comps) or 1.0
            for k, v in comps[:10]:
                w = round(abs(v) / mx * 14)
                decg.append(f"  {str(k)[:18]:<18} ", style=DIM)
                decg.append("▰" * w + " " * (14 - w), style=(GREEN if v >= 0 else ORANGE))
                decg.append(f"  {v:+.2f}\n", style=SILVER)
        else:
            decg.append("  (no numeric decomposition)\n", style=DIM)

        # integrity / model-risk strip
        integ = state.get("integrity", {}) or {}
        ig = Text("\nintegrity  ", style=f"bold {AMBER}")
        if integ.get("any_stale"):
            ig.append(f"STALE: {', '.join(integ.get('stale_feeds', [])) or 'feed'}  ", style=ORANGE)
        if integ.get("forensic_override_count"):
            ig.append(f"{integ.get('forensic_override_count')} forensic waiver(s) active  ", style=ORANGE)
        if not integ.get("any_stale") and not integ.get("forensic_override_count"):
            ig.append("all feeds fresh · no waivers", style=GREEN)

        self.query_one("#regime", Static).update(Group(head, tug, tt, decg, ig))

    # ------------------------------------------------------------------ signals rail
    def _render_signals(self, state) -> None:
        parts = []
        # --- ambient agent activity: Claude Code hooks + dispatches POST /agent/activity ---
        acts = state.get("agent_activity", []) or []
        newest = acts[-1].get("seq", 0) if acts else 0
        if newest > self._act_seq:                       # a fresh agent event — flash the rail
            self._act_seq = newest
            try:
                sig = self.query_one("#signals"); sig.add_class("glow")
                self.set_timer(2.5, lambda: sig.remove_class("glow"))
            except Exception:
                pass
        parts.append(Text("AGENT STREAM", style="bold #8C8C92"))
        if acts:
            icons = {"prompt": "›", "tool": "⚙", "response": "✓", "note": "•",
                     "proposal": "↯", "alert": "⚠", "focus": "◎", "scenario": "↯"}
            for a in reversed(acts[-6:]):
                ag = str(a.get("agent", "")).lower()
                ag_style = GOLD if "claude" in ag else (GREEN if any(k in ag for k in ("anti", "gravity", "gemini")) else SILVER)
                ln = Text(f"{icons.get(a.get('kind'), '•')} ", style=ag_style)
                ln.append(f"{a.get('agent','agent')} ", style=f"bold {ag_style}")
                if a.get("ticker"):
                    ln.append(f"[{a['ticker']}] ", style=AMBER)
                ln.append(str(a.get("summary", ""))[:38], style=SILVER)
                ln.append(f"  {_rel_age(a.get('ts'))}", style=DIM)
                parts.append(ln)
        else:
            parts.append(Text("idle — work in the Claude/agy panes and it", style=DIM))
            parts.append(Text("streams here (hooks → /agent/activity)", style=DIM))

        parts.append(Text("\nAGENT PROPOSALS", style="bold #8C8C92"))
        if self._pending:
            for p in self._pending[:4]:
                pl = Text(f"#{p.get('id')} ", style=AMBER)
                pl.append(f"{p.get('key')}=", style=SILVER)
                pl.append(f"{p.get('value')}", style=GOLD)
                pl.append(f"  by {p.get('proposed_by','agent')}\n", style=DIM)
                pl.append(f"   {str(p.get('reason',''))[:60]}", style=DIM)
                parts.append(pl)
            parts.append(Text("→ /confirm <id> · /reject <id>  (c confirms next)", style=DIM))
        else:
            parts.append(Text("none pending", style=DIM))

        integ = state.get("integrity", {}) or {}
        if integ.get("any_stale") or integ.get("forensic_override_count"):
            parts.append(Text("\nINTEGRITY", style="bold #8C8C92"))
            if integ.get("any_stale"):
                parts.append(Text(f"⚠ stale: {', '.join(integ.get('stale_feeds', []))}", style=ORANGE))
            if integ.get("forensic_override_count"):
                parts.append(Text(f"⚠ {integ.get('forensic_override_count')} forensic waiver(s)", style=ORANGE))

        tk = self._focus or "<name>"
        parts.append(Text("\nASK AGENTS  ›  fires into the panes", style="bold #8C8C92"))
        for key, label in (("a", f"@conviction-analyst: why is {tk} rated this?"),
                           ("b", f"red-team {tk} — bear case (agy)"),
                           ("x", f"/dossier {tk}")):
            a = Text(f" {key} ", style=f"bold black on {AMBER}")
            a.append(f"  {label}", style=SILVER)
            parts.append(a)
        self.query_one("#signalbody", Static).update(Group(*parts))

    # ------------------------------------------------------------------ dossier
    def _render_dossier_index(self) -> None:
        idx = self.query_one("#dossier_index", Static)
        if not self._decisions:
            tk = self._focus or "<TICKER>"
            idx.update(Text(f"no dossiers yet.\nrun  /dossier {tk}  in the\nClaude pane to write one\n"
                            f"(grounded on the focused\nname + current scenario).", style=DIM))
            return
        out = Text()
        for i, d in enumerate(self._decisions[:20]):
            if i:
                out.append("\n")
            out.append(f"{i:>2} ", style=AMBER)
            out.append(f"{str(d.get('ticker') or '?'):<7}", style="bold white")
            out.append(f" {str(d.get('title',''))[:18]}\n", style=SILVER)
            out.append(f"    {d.get('age_minutes','?')}m ago", style=DIM)
        idx.update(out)

    @work(thread=True, group="dossier")
    def _open_dossier(self, name: str) -> None:
        res = _get(f"/decisions/item?name={quote(name)}")
        md = (res or {}).get("markdown") or f"*could not load {name}*"
        self.call_from_thread(self.query_one("#dossier_body", Markdown).update, md)

    # ------------------------------------------------------------------ agent pickup
    def _handle_agent_command(self, state) -> None:
        cmd = state.get("ui_command") or {}
        seq = cmd.get("seq", 0)
        if not seq or seq <= self._last_seq:
            return
        self._last_seq = seq
        args = cmd.get("args", {}) or {}
        action = cmd.get("action")
        if action == "focus" and args.get("ticker"):
            self._set_focus(args["ticker"], move_cursor=True, report=False)
        elif action == "scenario":
            ov = args.get("scenario") or args.get("overrides") or ""
            self.query_one("#wf_overrides", Input).value = str(ov)
            self._wf_source = "agent"
            self._status(Text(f"↯ scenario proposed by agent: {ov}", style=GREEN))
        # flash the signals rail so a fresh agent action is unmissable
        try:
            sig = self.query_one("#signals")
            sig.add_class("glow")
            self.set_timer(2.5, lambda: sig.remove_class("glow"))
        except Exception:
            pass

    # ------------------------------------------------------------------ focus plumbing
    def _set_focus(self, ticker, move_cursor=False, report=True) -> None:
        ticker = (ticker or "").strip()
        if not ticker:
            return
        self._focus = ticker
        if move_cursor and ticker in self._row_index:
            self._suppress_report = True
            try:
                self.query_one("#booktbl", DataTable).move_cursor(row=self._row_index[ticker], animate=False)
            except Exception:
                pass
            self._suppress_report = False
        if ticker in self._baskets_by_ticker:
            self._render_book_detail(ticker)
        if report:
            self._report_ui(ticker)

    @work(thread=True, group="ui")
    def _report_ui(self, ticker: str) -> None:
        view = "book"
        try:
            view = self.query_one("#tabs", TabbedContent).active
        except Exception:
            pass
        sig = (ticker, view)
        if sig == self._last_reported:
            return
        self._last_reported = sig
        _post("/ui/state", {"focused_ticker": ticker, "active_view": view, "source": "tui",
                            "current_scenario": self._active_scenario,
                            "visible_tickers": list(self._baskets_by_ticker)})

    # ------------------------------------------------------------------ events
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        tk = getattr(event.row_key, "value", event.row_key)
        if not tk:
            return
        self._focus = str(tk)
        self._render_book_detail(str(tk))
        if not self._suppress_report:
            self._report_ui(str(tk))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if self._focus:
            self._report_ui(self._focus)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id
        val = event.value.strip()
        if wid == "cmdbar":
            self._run_command(val)
            event.input.value = ""
            try:
                self.query_one("#booktbl", DataTable).focus()
            except Exception:
                pass
        elif wid in ("wf_ticker", "wf_overrides"):
            self._do_whatif()
        elif wid == "wf_scenario":
            self._load_scenario(val)
        elif wid == "wf_name":
            self._do_save(val)
        elif wid == "dossier_open":
            self._dossier_pick(val)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        knobs = {"k_ag_up": "silver=+5", "k_ag_dn": "silver=-5", "k_ry": "ry=-0.5",
                 "k_vol": "vol=+20%", "k_peer": "peer=+20%", "k_mri": "mri=-10"}
        if bid in knobs:
            box = self.query_one("#wf_overrides", Input)
            box.value = (box.value + " " + knobs[bid]).strip()
            self._wf_source = "you"
        elif bid == "k_clear":
            self.query_one("#wf_overrides", Input).value = ""
        elif bid == "wf_run":
            self._do_whatif()
        elif bid == "wf_save":
            self._do_save(self.query_one("#wf_name", Input).value.strip())

    # ------------------------------------------------------------------ actions
    def action_tab(self, tab_id: str) -> None:
        try:
            self.query_one("#tabs", TabbedContent).active = tab_id
        except Exception:
            pass

    def action_whatif_focus(self) -> None:
        self.action_tab("whatif")
        if self._focus:
            self.query_one("#wf_ticker", Input).value = self._focus
        self.query_one("#wf_overrides", Input).focus()

    def action_cmd(self) -> None:
        bar = self.query_one("#cmdbar", Input)
        bar.value = "/"
        bar.focus()

    def action_confirm(self) -> None:
        if self._pending:
            self._do_confirm(self._pending[0].get("id"))

    # ---- one-key grounded dispatch INTO the live agent panes -------------------
    def action_ask(self, which: str) -> None:
        """Fire a grounded prompt straight into a tmux agent pane (no copy-paste)."""
        tk = self._focus
        if not tk:
            self._status(Text("focus a name first", style=ORANGE)); return
        if which == "analyst":
            self._dispatch("CLAUDE", "claude",
                           f"@conviction-analyst why is {tk} rated this? Ground in the live engine state.")
        elif which == "bear":
            self._dispatch("ANTIGRAVITY", "antigravity",
                           f"Red-team the {tk} thesis — the strongest bear case, grounded in its live "
                           f"valuation, forensics and catalysts.")
        elif which == "dossier":
            self._dispatch("CLAUDE", "claude", f"/dossier {tk}")

    def _find_pane(self, keyword: str):
        """Resolve a tmux pane id by its border title (set by cockpit.sh). Cockpit-only."""
        if not os.environ.get("TMUX"):
            return None
        for scope in (["-s", "-t", SESSION], ["-a"]):
            try:
                r = subprocess.run(["tmux", "list-panes", *scope, "-F", "#{pane_id}\t#{pane_title}"],
                                   capture_output=True, text=True, timeout=1.0)
                for ln in r.stdout.splitlines():
                    pid, _, title = ln.partition("\t")
                    if keyword.lower() in title.lower():
                        return pid
            except Exception:
                pass
        return None

    @work(thread=True, group="dispatch")
    def _dispatch(self, keyword: str, agent_label: str, prompt: str) -> None:
        pane = self._find_pane(keyword)
        if not pane:
            self.call_from_thread(self._status,
                                  Text(f"no '{keyword}' pane — run inside the cockpit (./cockpit.sh)", style=ORANGE))
            return
        try:
            subprocess.run(["tmux", "send-keys", "-t", pane, prompt, "Enter"], timeout=1.0)
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"dispatch failed: {exc}", style=ORANGE)); return
        # Log the dispatch onto the bus so it shows in the stream even for agents without hooks.
        _post("/agent/activity", {"agent": agent_label, "kind": "prompt", "summary": prompt, "ticker": self._focus})
        self.call_from_thread(self._status, Text(f"→ sent to {agent_label}: {prompt[:44]}", style=GREEN))

    # ------------------------------------------------------------------ what-if
    def _do_whatif(self) -> None:
        ticker = self.query_one("#wf_ticker", Input).value.strip()
        overrides = self.query_one("#wf_overrides", Input).value.strip()
        if ticker:
            self._set_focus(ticker, move_cursor=True)
        self.query_one("#wf_result", Static).update(Text("running what-if…", style=AMBER))
        self._run_whatif(ticker, overrides)

    @work(thread=True, group="whatif")
    def _run_whatif(self, ticker: str, overrides: str) -> None:
        res = _post("/action/whatif", {"ticker": ticker, "overrides": overrides})
        self.call_from_thread(self._show_whatif, res, overrides)

    def _show_whatif(self, res: dict, overrides: str) -> None:
        out = self.query_one("#wf_result", Static)
        if not res or res.get("error"):
            out.update(Text(f"⚠ {res.get('error','no result') if res else 'no result'}", style=ORANGE))
            return
        base, scen, delta = res.get("base", {}), res.get("scenario", {}), res.get("delta", {})
        tk = res.get("ticker", "?")
        bi, si = _num(base.get("intrinsic")), _num(scen.get("intrinsic"))
        price = _num(res.get("price"))
        dp = _num(delta.get("intrinsic_pct"))

        head = Text()
        head.append(f"{tk}  ", style=f"bold {GOLD}")
        head.append(f"({res.get('archetype','—')})   ", style=DIM)
        head.append("source: ", style=DIM)
        head.append("agent ↯" if self._wf_source == "agent" else "you", style=(GREEN if self._wf_source == "agent" else SILVER))

        applied = Text("applied: ", style=DIM)
        ap = res.get("overrides_applied", {}) or {}
        applied.append(", ".join(f"{k} {v.get('from')}→{v.get('to')}" if isinstance(v, dict) else f"{k}={v}"
                                 for k, v in ap.items()) or "—", style=SILVER)

        cols = Text()
        cols.append(f"\n{'':10}{'BASE':>12}{'SCENARIO':>12}\n", style=AMBER)
        cols.append(f"{'intrinsic':10}{_fmt(bi):>12}{_fmt(si):>12}\n", style=SILVER)
        cols.append(f"{'upside %':10}{_fmt(base.get('upside_pct')):>12}{_fmt(scen.get('upside_pct')):>12}\n",
                    style=SILVER)

        dl = Text("\nΔ intrinsic ", style=DIM)
        dl.append(f"{_fmt(dp)}%  ", style=(GREEN if (dp or 0) >= 0 else RED))
        dl.append_text(_delta_bar(dp))
        dl.append(f"   Δ upside {_fmt(delta.get('upside_pp'))}pp", style=SILVER)

        bar, legend = _ladder([("F", (base.get("legs") or {}).get("cost"), ORANGE),
                               ("●", price, "white"),
                               ("◆", bi, GOLD),
                               ("✦", si, GREEN)])
        ladder = Group(Text("\nvalue ladder  (F floor · ● price · ◆ base intrinsic · ✦ scenario)", style=DIM),
                       bar, legend)

        out.update(Group(head, applied, cols, dl, ladder))
        self._push_history(tk, overrides, dp)
        self._wf_source = "you"

    def _push_history(self, tk, overrides, dp) -> None:
        line = Text("↳ ", style=AMBER)
        line.append(f"{tk} ", style="bold white")
        line.append(f"{overrides or '(none)'}  ", style=DIM)
        line.append(f"Δ{_fmt(dp)}%", style=(GREEN if (dp or 0) >= 0 else RED))
        self._wf_hist.insert(0, line)
        del self._wf_hist[5:]                          # keep a short, scannable iteration trail
        self.query_one("#wf_history", Static).update(Text("\n").join(self._wf_hist))

    def _load_scenario(self, name: str) -> None:
        name = (name or "").strip()
        match = next((s for s in self._scenarios if s.get("name") == name), None)
        box = self.query_one("#wf_overrides", Input)
        if not match:
            self._status(Text(f"no saved scenario '{name}'", style=ORANGE))
            return
        ov = match.get("overrides", {})
        box.value = " ".join(f"{k}={v}" for k, v in ov.items()) if isinstance(ov, dict) else str(ov)
        self._active_scenario = name
        self._status(Text(f"loaded scenario '{name}'", style=GREEN))

    @work(thread=True, group="scen")
    def _do_save(self, name: str) -> None:
        overrides = self.query_one("#wf_overrides", Input).value.strip()
        ov = parse_overrides(overrides)
        if not name or not ov:
            self.call_from_thread(self._status, Text("need a name and overrides to save", style=ORANGE))
            return
        res = _post("/config/scenario", {"name": name, "overrides": ov})
        ok = res.get("ok")
        self._active_scenario = name if ok else self._active_scenario
        msg = (f"saved scenario '{name}'" if ok else f"save failed: {res.get('error')}")
        self.call_from_thread(self._status, Text(msg, style=(GREEN if ok else ORANGE)))
        self.refresh_data()

    @work(thread=True, group="confirm")
    def _do_confirm(self, pid) -> None:
        res = _post("/config/confirm", {"id": pid, "source": "cockpit"})
        ok = res.get("ok")
        self.call_from_thread(self._status,
                              Text((f"confirmed #{pid}" if ok else f"confirm failed: {res.get('error')}"),
                                   style=(GREEN if ok else ORANGE)))
        self.refresh_data()

    @work(thread=True, group="reject")
    def _do_reject(self, pid) -> None:
        _post("/config/reject", {"id": pid})
        self.refresh_data()

    def _dossier_pick(self, val: str) -> None:
        val = (val or "").strip()
        if not self._decisions:
            return
        target = None
        if val.isdigit():
            i = int(val)
            target = self._decisions[i] if 0 <= i < len(self._decisions) else None
        else:
            target = next((d for d in self._decisions
                           if val.upper() in str(d.get("ticker", "")).upper()), None)
        if target:
            self._open_dossier(target.get("name"))

    # ------------------------------------------------------------------ slash commands
    def _run_command(self, text: str) -> None:
        text = text.strip()
        if text.startswith("/"):
            text = text[1:]
        if not text:
            return
        parts = text.split()
        verb, rest = parts[0].lower(), parts[1:]
        if verb in ("focus", "f") and rest:
            self.action_tab("book")
            self._set_focus(rest[0].upper(), move_cursor=True)
        elif verb in ("whatif", "wi") and rest:
            self.action_tab("whatif")
            self.query_one("#wf_ticker", Input).value = rest[0].upper()
            if len(rest) > 1:
                self.query_one("#wf_overrides", Input).value = " ".join(rest[1:])
            self._do_whatif()
        elif verb in ("scenario", "scen") and rest:
            self.action_tab("whatif")
            self._load_scenario(rest[0])
        elif verb == "save" and rest:
            self._do_save(rest[0])
        elif verb == "confirm" and rest and rest[0].isdigit():
            self._do_confirm(int(rest[0]))
        elif verb == "reject" and rest and rest[0].isdigit():
            self._do_reject(int(rest[0]))
        elif verb in ("dossier", "doss") and rest:
            self.action_tab("dossier_tab")
            self._set_focus(rest[0].upper())
            self._dossier_pick(rest[0].upper())
        elif verb == "tab" and rest:
            self.action_tab(rest[0])
        elif verb in ("refresh", "r"):
            self.refresh_data()
        else:
            self.action_tab("whatif")
            self._status(Text("commands: /focus TK · /whatif TK ov… · /scenario name · /save name · "
                              "/confirm id · /reject id · /dossier TK · /tab id · /refresh", style=DIM))


if __name__ == "__main__":
    Cockpit().run()
