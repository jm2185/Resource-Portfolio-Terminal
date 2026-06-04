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
from collections import deque
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
# Muted on purpose: a low-glare "desk at night" amber, not a blinding hi-vis orange.
AMBER  = "#D6A24A"   # primary accent / focus (soft brass)
GOLD   = "#D9C27E"   # headline values (soft gold)
SILVER = "#B6B6BE"   # body text
DIM    = "#74747C"   # secondary / hints
GREEN  = "#7FC8A0"   # good / risk-on / agent-live (soft mint)
RED    = "#D87A7A"   # bad / risk-off (soft)
ORANGE = "#CF9A5C"   # warn (muted)
TEAL   = "#6FA8A6"   # research / Antigravity accent
BORDER = "#26262C"

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


def _rel_age(ts):
    if not ts:
        return ""
    secs = max(0, int(time.time() - float(ts)))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


_SPARK = "▁▂▃▄▅▆▇█"
def _spark(vals) -> str:
    """A tiny inline sparkline from a rolling buffer — the desk's own little memory of a series."""
    vals = [v for v in vals if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    return "".join(_SPARK[min(7, int((v - lo) / rng * 7))] for v in vals[-12:])


_TAPE_SHORT = {"Gold/Silver": "GSR", "Copper/Gold ×1k": "Cu/Au", "DXY/Gold ×1k": "DXY/Au",
               "Real Yield": "RealY", "SOFR Spread": "SOFR", "HY Spread": "HY", "30Y–10Y": "30-10",
               "VIX": "VIX", "CFTC Net %ile": "CFTC", "VIX Term (3M/1M)": "VIXt"}
def _tape_short(label) -> str:
    return _TAPE_SHORT.get(label, str(label)[:6])


_LEVEL_COLOR = {"info": "#D6A24A", "good": "#7FC8A0", "warn": "#CF9A5C", "risk": "#D87A7A"}
def _level_color(level) -> str:
    return _LEVEL_COLOR.get(str(level or "info"), "#D6A24A")


# ======================================================================================
#  The cockpit
# ======================================================================================
class Cockpit(App):
    TITLE = "CommodityEx"
    SUB_TITLE = "research cockpit"

    CSS = """
    Screen { background: #08080A; color: #CBCBD2; layers: base overlay; }
    Header { background: #0E0E10; color: #D9C27E; text-style: bold; }
    #statusband { height: 1; padding: 0 1; background: #0E0E10; color: #B6B6BE; }

    #body { height: 1fr; }
    #watch   { width: 30; border-right: solid #26262C; padding: 0 1; }
    #signals { width: 36; border-left: solid #26262C; padding: 0 1; }
    #tabs { width: 1fr; }

    .railtitle  { color: #D6A24A; text-style: bold; }
    .railsub    { color: #74747C; text-style: bold; margin-top: 1; }
    #healthmini { border-top: solid #26262C; margin-top: 1; padding-top: 1; }

    DataTable { height: 1fr; background: #08080A;
                scrollbar-size-horizontal: 1; scrollbar-size-vertical: 1;
                scrollbar-background: #0B0B0D; scrollbar-color: #26262C; scrollbar-color-hover: #D6A24A; }
    DataTable > .datatable--cursor { background: #1C1C22; }
    DataTable > .datatable--header { color: #D6A24A; text-style: bold; }
    VerticalScroll { scrollbar-size-vertical: 1; scrollbar-background: #0B0B0D;
                     scrollbar-color: #26262C; scrollbar-color-hover: #D6A24A; }
    #booktbl { height: 12; }
    #agent_reply_box { height: 1fr; border-top: solid #26262C; padding: 0 1; }
    #agent_reply { height: auto; }
    #book_detail { height: auto; min-height: 4; border-top: solid #26262C; padding: 1; color: #B6B6BE; }

    Input  { border: tall #26262C; background: #0E0E10; }
    Input:focus { border: tall #D6A24A; }
    Button { background: #121214; color: #D9C27E; border: tall #26262C; height: 3; }
    Button:hover { border: tall #D6A24A; }
    Button.knob { color: #B6B6BE; min-width: 9; }
    .row { height: auto; }

    #wf_result  { height: 1fr; border: round #26262C; padding: 1; }
    #wf_history { height: auto; color: #74747C; }
    #wf_status  { height: auto; color: #B6B6BE; }
    #wf_hint    { height: auto; color: #74747C; }
    #regime  { padding: 0 1; }
    #dossier_list { width: 34; border-right: solid #26262C; padding: 0 1; color: #B6B6BE; }
    #dossier_body { width: 1fr; padding: 0 1; }
    #dossier_open { width: 34; }

    #ticker { dock: bottom; height: 1; padding: 0 1; background: #0B0B0D;
              color: #B6B6BE; border-top: solid #26262C; }
    #cmdbar { dock: bottom; height: 3; border: tall #26262C; background: #0B0B0D; display: none; }
    #cmdbar.active { display: block; }
    #cmdbar:focus { border: tall #D6A24A; }
    Footer { background: #0E0E10; }

    .glow { border: round #6FA8A6; }
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
        # --- "alive" state: rolling history for sparklines, heartbeat + ticker animation ---
        self._hist: dict = {}                 # metric -> deque of recent values (for sparklines/trend)
        self._beat = 0                        # pulse frame, advanced ~2x/sec
        self._ticker_body: Text | None = None  # cached colored macro line; _pulse adds the heartbeat
        self._asked: str | None = None        # last plain-text prompt sent to the agents from the bar

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("connecting to engine…", id="statusband")
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
                    with VerticalScroll(id="agent_reply_box"):
                        yield Static("", id="agent_reply")
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
        yield Static("", id="ticker")          # live macro ticker (always on) — see _pulse
        yield Input(placeholder="ask the agents in plain text…  or a /command (/focus AGA.V · /whatif AGA.V silver=+5 · /confirm 3)   ·   Esc to close",
                    id="cmdbar")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#booktbl", DataTable)
        for c, w in (("", 3), ("TICKER", 7), ("ARCH", 8), ("R", 4), ("BAND", 14),
                     ("T", 3), ("Q", 3), ("V", 3), ("UP%", 5), ("FLOOR", 6),
                     ("GATE", 13), ("DIRECTIVE", 22)):
            t.add_column(c, key=c or "role", width=w)
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.set_interval(0.5, self._pulse)     # ~2 Hz heartbeat (no network) — keeps the desk live
        self.refresh_data()

    # ------------------------------------------------------------------ polling
    def action_refresh(self) -> None:
        self.refresh_data()

    def _push_hist(self, key: str, val) -> None:
        if isinstance(val, (int, float)):
            self._hist.setdefault(key, deque(maxlen=40)).append(float(val))

    def _pulse(self) -> None:
        """Animate the LIVE heartbeat + breathe the bottom ticker, with no network calls
        (data lands on the 3 s poll; this just makes the desk feel awake)."""
        self._beat = (self._beat + 1) % 10000
        body = self._ticker_body
        if body is None:
            return
        on = (self._beat % 2 == 0)
        line = Text("◉ " if on else "◯ ", style=(GREEN if on else DIM))
        line.append("".join("▏▎▍▌▋▊▉"[(self._beat + i) % 7] for i in range(3)) + " ", style=GREEN)
        line.append_text(body)
        try:
            self.query_one("#ticker", Static).update(line)
        except Exception:
            pass

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
        self._render_agent_reply(state)
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
        tape = state.get("macro_tape", {}) or {}
        tape_by_key = {s.get("key"): s for s in (tape.get("signals") or [])}
        regime = ctx.get("regime") or tape.get("net_tilt", "—")
        mri = state.get("mri")
        spot = (metrics.get("Spot_Ag", {}) or {}).get("value")
        gsr = (metrics.get("GSR", {}) or {}).get("value")
        dxy_mom = (metrics.get("DXY_MOMENTUM", {}) or {}).get("value")
        dxy = (metrics.get("DXY", {}) or {}).get("value")
        y10 = (metrics.get("10Y", {}) or {}).get("value")
        y30 = (metrics.get("30Y", {}) or {}).get("value")
        health = hr.get("health_rating")
        status = state.get("status", "—")
        focus = self._focus or "—"
        gold = (gsr * spot) if (_num(gsr) is not None and _num(spot) is not None) else None

        for k, v in (("mri", mri), ("ag", spot), ("au", gold)):   # feed the sparkline memory
            self._push_hist(k, v)

        sep = Text("   ", style=BORDER)
        line = Text()
        line.append("REGIME ", style=DIM)
        line.append(str(regime), style=f"bold {bias_color('risk_off' if 'OFF' in str(regime).upper() else ('risk_on' if 'ON' in str(regime).upper() else 'neutral'))}")
        line.append_text(sep)
        line.append("MRI ", style=DIM); line.append(_fmt(mri, "{:.0f}"), style=GOLD)
        line.append(" "); line.append_text(_mri_gauge(mri))
        sp = _spark(self._hist.get("mri", []))
        if sp:
            line.append(" "); line.append(sp, style=TEAL)
        line.append_text(sep)
        if gold is not None:
            line.append("Au ", style=DIM); line.append(f"${_fmt(gold, '{:.0f}')}", style=SILVER)
            line.append_text(sep)
        line.append("Ag ", style=DIM); line.append(f"${_fmt(spot, '{:.2f}')}", style=SILVER)
        sp = _spark(self._hist.get("ag", []))
        if sp:
            line.append(" "); line.append(sp, style=TEAL)
        line.append("  GSR ", style=DIM); line.append(_fmt(gsr, "{:.0f}"), style=SILVER)
        line.append_text(sep)
        ry = tape_by_key.get("real_yield")
        if ry:
            line.append("RealY ", style=DIM)
            line.append(str(ry.get("display", "—")), style=bias_color(ry.get("bias")))
            line.append_text(sep)
        # rates cluster: dollar level + the long end (levels, not the spread)
        if _num(dxy) is not None:
            arrow = "▲" if (_num(dxy_mom) or 0) > 0 else "▼"
            line.append("DXY ", style=DIM)
            line.append(f"{_fmt(dxy, '{:.1f}')}{arrow}", style=(ORANGE if (_num(dxy_mom) or 0) > 0 else GREEN))
            line.append_text(sep)
        if _num(y10) is not None:
            line.append("10Y ", style=DIM); line.append(f"{_fmt(y10, '{:.2f}')}", style=SILVER)
            line.append(" 30Y ", style=DIM); line.append(f"{_fmt(y30, '{:.2f}')}", style=SILVER)
            line.append_text(sep)
        line.append("HEALTH ", style=DIM); line.append(f"{_fmt(health)}/10", style=health_color(health))
        line.append_text(sep)
        line.append("◆ ", style=AMBER); line.append(str(focus), style=f"bold {AMBER}")
        line.append_text(sep)
        line.append("● " if status == "LIVE" else "○ ", style=(GREEN if status == "LIVE" else ORANGE))
        line.append(str(status), style=(GREEN if status == "LIVE" else ORANGE))
        self.query_one("#statusband", Static).update(line)

    def _render_tape(self, state) -> None:
        """Build the bottom live-ticker body: every cross-asset signal, bias-coloured and compact.
        _pulse() prepends the animated heartbeat and pushes it to #ticker ~2x/sec."""
        tape = state.get("macro_tape", {}) or {}
        sig = tape.get("signals", []) or []
        tilt = str(tape.get("net_tilt", "—"))
        on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
        body = Text()
        body.append("NET ", style=DIM)
        body.append(f"{tilt}", style=f"bold {bias_color('risk_on' if 'ON' in tilt else ('risk_off' if 'OFF' in tilt else 'neutral'))}")
        body.append(f" {on}↑/{off}↓", style=DIM)
        for s in sig:
            body.append("   ")
            body.append(f"{_tape_short(s.get('label', ''))} ", style=DIM)
            body.append(str(s.get("display", "—")), style=bias_color(s.get("bias")))
        self._ticker_body = body
        self._pulse()                          # paint immediately, don't wait for the next beat

    # ------------------------------------------------------------------ watch rail
    def _render_watch(self, state, baskets) -> None:
        nodes = state.get("nodes", {}) or {}
        annos = state.get("agent_annotations", {}) or {}
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
            for a in (annos.get(tk) or [])[-1:]:          # agent's visual trace (pin_insight/highlight)
                col = _level_color(a.get("level"))
                out.append("\n     ", style=DIM)
                out.append(f"{a.get('badge', '✦')} ", style=f"bold {col}")
                out.append(str(a.get("reason", ""))[:19], style=col)
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
        annos = state.get("agent_annotations", {}) or {}
        anno_sig = tuple(sorted((tk, (v[-1].get("seq") if v else None)) for tk, v in annos.items()))
        sig = (self._book_signature(baskets), anno_sig)
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
            tick = Text(tk, style="bold white")             # agent badge rides next to the ticker
            for a in (annos.get(tk) or [])[-1:]:
                tick.append(f" {a.get('badge', '✦')}", style=f"bold {_level_color(a.get('level'))}")
            tbl.add_row(
                Text(f"{focus_mark}{_role_glyph(tk, nodes)}", style=AMBER if tk == prev else health_color(r)),
                tick,
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

        # rates & dollar — raw levels (not the spread): DXY, the long end, plus the slope
        metrics = state.get("metrics", {}) or {}
        def _mv(k):
            return (metrics.get(k, {}) or {}).get("value")
        dxy_, y10_, y30_, dmom = _mv("DXY"), _mv("10Y"), _mv("30Y"), _mv("DXY_MOMENTUM")
        rates = Text("\nrates  ", style=f"bold {AMBER}")
        if _num(dxy_) is not None:
            arrow = "▲" if (_num(dmom) or 0) > 0 else "▼"
            rates.append("DXY ", style=DIM)
            rates.append(f"{_fmt(dxy_, '{:.1f}')}{arrow}", style=(ORANGE if (_num(dmom) or 0) > 0 else GREEN))
        rates.append("    10Y ", style=DIM); rates.append(f"{_fmt(y10_, '{:.2f}')}%", style=SILVER)
        rates.append("    30Y ", style=DIM); rates.append(f"{_fmt(y30_, '{:.2f}')}%", style=SILVER)
        if _num(y10_) is not None and _num(y30_) is not None:
            sp = y30_ - y10_
            rates.append("    30Y–10Y ", style=DIM); rates.append(f"{sp:+.2f}%", style=(RED if sp < 0 else SILVER))
        # full UST curve from FMP (1mo…30yr), if available
        tc = state.get("treasury_curve") or {}
        ten = tc.get("tenors") or {}
        if any(_num(v) is not None for v in ten.values()):
            rates.append("\nUST curve ", style=DIM)
            for lbl, key in (("1M", "month1"), ("3M", "month3"), ("6M", "month6"), ("1Y", "year1"),
                             ("2Y", "year2"), ("5Y", "year5"), ("10Y", "year10"), ("30Y", "year30")):
                if _num(ten.get(key)) is not None:
                    rates.append(f" {lbl} ", style=DIM)
                    rates.append(f"{_fmt(ten.get(key), '{:.2f}')}", style=SILVER)
            rates.append(f"   ({tc.get('source', 'FMP')})", style=DIM)
        rates.append("\n")

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

        self.query_one("#regime", Static).update(Group(head, tug, rates, tt, decg, ig))

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

        annos = state.get("agent_annotations", {}) or {}
        if annos:
            parts.append(Text("\nAGENT NOTES", style="bold #8C8C92"))
            shown = 0
            for tk in sorted(annos.keys(), key=lambda t: (t != self._focus, t)):
                for a in annos[tk][-2:]:
                    col = _level_color(a.get("level"))
                    ln = Text(f"{a.get('badge', '✦')} ", style=f"bold {col}")
                    ln.append(f"{tk} ", style=f"bold {col}")
                    ln.append(str(a.get("reason", ""))[:30], style=SILVER)
                    ln.append(f"  ·{str(a.get('agent', ''))[:8]}", style=DIM)
                    parts.append(ln)
                    shown += 1
                    if shown >= 5:
                        break
                if shown >= 5:
                    break

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
        parts.append(Text("\nASK AGENTS", style="bold #8C8C92"))
        for key, label, col in (("a", f"analyst — why is {tk} rated this?", AMBER),
                                ("x", f"/dossier {tk}  (Claude)", AMBER),
                                ("b", f"bear case on {tk}  (Antigravity)", TEAL)):
            a = Text(f" {key} ", style=f"bold {col} on #1C1C22")     # dim badge, not a solid bar
            a.append(f" {label}", style=SILVER)
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
        if action in ("focus", "focus_element") and args.get("ticker"):
            self._set_focus(args["ticker"], move_cursor=True, report=False)
        elif action == "scenario":
            ov = args.get("scenario") or args.get("overrides") or ""
            self.query_one("#wf_overrides", Input).value = str(ov)
            self._wf_source = "agent"
            self._status(Text(f"↯ scenario proposed by agent: {ov}", style=GREEN))
        elif action == "switch_tab":
            self.action_tab(self._tab_for(args.get("view") or args.get("tab")))
        elif action == "apply_scenario":
            if args.get("ticker"):
                self._set_focus(args["ticker"], move_cursor=True, report=False)
            ov = args.get("overrides") or args.get("scenario") or ""
            self.query_one("#wf_overrides", Input).value = str(ov)
            self._wf_source = "agent"
            self.action_tab("whatif")
            self._do_whatif()
            self._status(Text(f"↯ agent ran what-if: {ov}", style=GREEN))
        elif action in ("highlight", "pin_insight") and args.get("ticker"):
            r = str(args.get("reason") or args.get("note") or "")[:48]
            self._status(Text(f"✦ {args.get('agent','agent')} flagged {args['ticker']}: {r}",
                              style=_level_color(args.get("level"))))
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
            if val.startswith("/") or val.startswith(":"):
                self._run_command(val)
            elif val:
                self._ask_agent(val)              # plain text -> ask the agents, reply lands in Book
            self._hide_cmd()
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

    @staticmethod
    def _tab_for(view) -> str:
        return {"book": "book", "whatif": "whatif", "what-if": "whatif", "live what-if": "whatif",
                "regime": "regime_tab", "regime_tab": "regime_tab",
                "dossier": "dossier_tab", "dossier_tab": "dossier_tab"}.get(str(view or "").lower(), "book")

    def action_whatif_focus(self) -> None:
        self.action_tab("whatif")
        if self._focus:
            self.query_one("#wf_ticker", Input).value = self._focus
        self.query_one("#wf_overrides", Input).focus()

    def action_cmd(self) -> None:
        """Summon the slim command bar (hidden by default so the bottom is a live ticker).
        Plain text → ask the agents; a leading / → a cockpit command."""
        bar = self.query_one("#cmdbar", Input)
        bar.add_class("active")
        bar.value = ""
        self.call_after_refresh(bar.focus)

    def _ask_agent(self, text: str) -> None:
        """Plain-text prompt → the Claude pane; the reply lands in the Book tab's AGENT REPLY panel."""
        text = text.strip()
        if not text:
            return
        self._asked = text
        self.action_tab("book")
        self._render_agent_reply(self._state)        # show the pending state immediately
        self._dispatch("CLAUDE", "claude", text)
        self._status(Text("→ asked Claude — the reply appears in the Book tab", style=GREEN))

    def _render_agent_reply(self, state) -> None:
        rep = (state or {}).get("agent_reply") or {}
        parts = [Text("AGENT REPLY", style=f"bold {AMBER}")]
        if self._asked:
            parts.append(Text(f"⟵ you asked: {self._asked}", style=DIM))
        if rep.get("text"):
            parts.append(Text(f"{rep.get('agent', 'claude')} · {_rel_age(rep.get('ts'))}", style=DIM))
            parts.append(Text(str(rep.get("text")), style=SILVER))
        elif self._asked:
            parts.append(Text("⟳ waiting for the agent…", style=TEAL))
        else:
            parts.append(Text("Press  /  and ask in plain text — the agent's reply shows here.", style=DIM))
        self.query_one("#agent_reply", Static).update(Group(*parts))

    def _hide_cmd(self) -> None:
        try:
            bar = self.query_one("#cmdbar", Input)
            bar.remove_class("active")
            bar.value = ""
            self.query_one("#booktbl", DataTable).focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            try:
                if self.query_one("#cmdbar", Input).has_class("active"):
                    self._hide_cmd()
                    event.stop()
            except Exception:
                pass

    def action_confirm(self) -> None:
        if self._pending:
            self._do_confirm(self._pending[0].get("id"))

    # ---- one-key dispatch: Claude -> its pane; Antigravity -> headless research ----
    def action_ask(self, which: str) -> None:
        """`a`/`x` fire a grounded prompt into the Claude pane; `b` runs Antigravity headless."""
        tk = self._focus
        if not tk:
            self._status(Text("focus a name first", style=ORANGE)); return
        if which == "analyst":
            self._dispatch("CLAUDE", "claude",
                           f"@conviction-analyst why is {tk} rated this? Ground in the live engine state.")
        elif which == "dossier":
            self._dispatch("CLAUDE", "claude", f"/dossier {tk}")
        elif which == "bear":
            self._agy_research(
                f"Red-team the investment thesis for {tk}, a precious-metals name. Give the strongest, "
                f"most specific bear case: valuation, dilution / financing risk, jurisdiction, execution, "
                f"and the concrete signals that would invalidate the bull case.", "bear-case")

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

    # ---- Antigravity as a headless research backend (web-auth'd CLI, no API key) ----
    def _agy_argv(self, prompt: str):
        """One-shot Antigravity/Gemini invocation. Flags vary by CLI, so it's configurable:
        CEX_AGY_HEADLESS (default 'agy -p {prompt}'); {prompt} is substituted, else appended."""
        import shlex
        binary = os.environ.get("CEX_AGY_CMD", "agy")
        tmpl = os.environ.get("CEX_AGY_HEADLESS", f"{binary} -p {{prompt}}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            return [prompt if p == "{prompt}" else p for p in parts]
        return parts + [prompt]

    def _save_research(self, tk: str, tag: str, prompt: str, result: str) -> str:
        import datetime
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{tk}_{tag}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
        with open(path, "w") as f:
            f.write(f"# Antigravity {tag} — {tk}\n\n_{datetime.datetime.now():%Y-%m-%d %H:%M}_\n\n"
                    f"**Prompt:** {prompt}\n\n---\n\n{result}\n")
        return path

    @work(thread=True, group="research")
    def _agy_research(self, prompt: str, tag: str) -> None:
        tk = self._focus or "?"
        self.call_from_thread(self._status, Text(f"⟳ Antigravity {tag} on {tk}… (headless, up to ~2 min)", style=TEAL))
        _post("/agent/activity", {"agent": "antigravity", "kind": "prompt", "summary": f"{tag}: {tk}", "ticker": tk})
        try:
            out = subprocess.run(self._agy_argv(prompt), capture_output=True, text=True, timeout=180)
            result = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._status, Text("agy CLI not found — set CEX_AGY_CMD / CEX_AGY_HEADLESS", style=ORANGE))
            _post("/agent/activity", {"agent": "antigravity", "kind": "alert", "summary": "CLI not found", "ticker": tk}); return
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._status, Text("Antigravity timed out (180s)", style=ORANGE))
            _post("/agent/activity", {"agent": "antigravity", "kind": "alert", "summary": f"{tag} timed out", "ticker": tk}); return
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"research failed: {exc}", style=ORANGE)); return
        if not result:
            self.call_from_thread(self._status, Text("Antigravity returned nothing — check CEX_AGY_HEADLESS flag", style=ORANGE)); return
        path = self._save_research(tk, tag, prompt, result)
        _post("/agent/activity", {"agent": "antigravity", "kind": "note",
                                  "summary": f"{tag} ready → {os.path.basename(path)} ({len(result)}c)", "ticker": tk})
        self.call_from_thread(self._status, Text(f"✓ Antigravity {tag} saved → {path}", style=GREEN))

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
