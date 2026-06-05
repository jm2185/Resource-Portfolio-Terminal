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
from rich.style import Style
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


_SUB_ABBR = {
    "nsr_royalty": "nsr", "streamer": "strm", "royalty_generator_holdco": "gen·holdco",
    "mature_royalty": "mat·roy", "grassroots": "grass", "delineation": "delin",
    "pre_pea": "pre-pea", "pea_dev": "pea-dev", "near_term_dev": "near-dev", "ramp_up": "ramp",
    "marginal_producer": "marg", "low_cost_producer": "lowcost", "physical_trust": "trust",
    "futures_etp": "etp", "enricher": "enrich", "infrastructure": "infra",
}


def _sub_abbr(sub):
    """Compact watch-rail label for a sub-archetype (graceful: a trimmed name when unmapped)."""
    s = str(sub or "")
    return _SUB_ABBR.get(s, s.replace("_", " ")[:9])


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
    # value-mode (royalty / holdco): coverage φ is ~flat by construction, so show the floor PRICE —
    # which IS name-specific — instead of a uniform-looking ratio.
    if v.get("mode") == "value":
        fl = _num((basket.get("ladder") or {}).get("floor"))
        if fl is not None:
            return Text(_money(fl), style=SILVER)
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


def _money(x, sym="$"):
    v = _num(x)
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1000:
        return f"{sym}{v:,.0f}"
    if a >= 1:
        return f"{sym}{v:,.2f}"
    return f"{sym}{v:.3f}"


def _compact(x):
    """1_234_567 → 1.2M (volume / market cap), tabular-friendly."""
    v = _num(x)
    if v is None:
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"


def _range_bar(rng, price, width=20):
    """52-wk range as a position gauge (Koyfin/TradingView style): low ├──●────┤ high,
    marker tinted by where price sits (green near highs, red near lows)."""
    try:
        parts = str(rng).replace("$", "").split("-")
        lo, hi = float(parts[0]), float(parts[1])
        p = float(_num(price))
    except (ValueError, TypeError, IndexError):
        return None
    if hi <= lo or p is None:
        return None
    frac = max(0.0, min(1.0, (p - lo) / (hi - lo)))
    pos = int(round(frac * (width - 1)))
    col = GREEN if frac >= 0.66 else (RED if frac <= 0.33 else AMBER)
    t = Text("52wk ", style=DIM)
    t.append(f"{_money(lo)} ", style=DIM)
    t.append("─" * pos, style=BORDER)
    t.append("●", style=f"bold {col}")
    t.append("─" * (width - 1 - pos), style=BORDER)
    t.append(f" {_money(hi)}  ", style=DIM)
    t.append(f"{frac * 100:.0f}%", style=col)
    return t


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

# Interactive what-if knobs: (name, override-key, kind, coarse-step, fine-step, label).
# name doubles as the override token the engine accepts (except capdisc → capital_discount).
_WF_KNOBS = [
    ("silver",  "silver",           "delta", 1.0,  0.25, "Ag $"),
    ("gold",    "gold",             "delta", 25.0, 5.0,  "Au $"),
    ("ry",      "ry",               "delta", 0.1,  0.05, "RealY"),
    ("dxy",     "dxy",              "delta", 0.5,  0.1,  "DXY"),
    ("peer",    "peer",             "pct",   5.0,  1.0,  "Peer%"),
    ("vol",     "vol",              "pct",   5.0,  1.0,  "Vol%"),
    ("mri",     "mri",              "delta", 5.0,  1.0,  "MRI"),
    ("capdisc", "capital_discount", "delta", 0.5,  0.1,  "CapDisc"),
]
_ALIAS_TO_KNOB = {"silver": "silver", "ag": "silver", "spot_ag": "silver", "gold": "gold", "au": "gold",
                  "ry": "ry", "real_yield": "ry", "yield": "ry", "yields": "ry", "dxy": "dxy",
                  "peer": "peer", "ev": "peer", "peer_ev_oz": "peer", "vol": "vol", "silver_vol": "vol",
                  "mri": "mri", "regime": "mri", "capital_discount": "capdisc"}


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
    #cmdbar { dock: bottom; height: 3; border: tall #26262C; background: #0B0B0D; }
    #cmdbar:focus { border: tall #D6A24A; }
    Footer { background: #0E0E10; }

    .glow { border: round #6FA8A6; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("1", "tab('book')", "Book"),
        ("2", "tab('council_tab')", "Council"),
        ("3", "tab('whatif')", "What-If"),
        ("4", "tab('regime_tab')", "Regime"),
        ("5", "tab('dossier_tab')", "Dossier"),
        ("w", "whatif_focus", "What-If"),
        ("p", "open_profile", "Profile"),
        ("left_square_bracket", "wf_knob(-1)", "Prev knob"),
        ("right_square_bracket", "wf_knob(1)", "Next knob"),
        ("minus", "wf_step(-1, False)", "Knob −"),
        ("equals_sign", "wf_step(1, False)", "Knob +"),
        ("comma", "wf_step(-1, True)", "Knob − fine"),
        ("full_stop", "wf_step(1, True)", "Knob + fine"),
        ("backslash", "wf_reset", "Reset knobs"),
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
        self._open_doss: str | None = None    # currently-open dossier (for index highlight)
        self._del_arm: str | None = None       # dossier armed for delete (two-click safety)
        self._baskets_by_ticker: dict = {}
        self._fund: dict = {}                 # FMP fundamentals per ticker (cached; {} = fetched/none)
        self._row_index: dict = {}
        self._book_sig = None
        self._focus: str | None = None
        self._last_reported: tuple | None = None
        self._active_scenario: str | None = None
        self._wf_source = "you"
        self._wf_hist: list = []
        self._wf_knobs: dict = {k[0]: 0.0 for k in _WF_KNOBS}   # interactive what-if knob deltas
        self._wf_sel = 0                                         # selected knob index
        self._wf_timer = None                                   # debounce for live revalue
        self._last_seq = 0
        self._act_seq = 0
        self._tick = 0
        self._suppress_report = False
        # --- "alive" state: rolling history for sparklines, heartbeat + ticker animation ---
        self._hist: dict = {}                 # metric -> deque of recent values (for sparklines/trend)
        self._beat = 0                        # pulse frame, advanced ~2x/sec
        self._ticker_body: Text | None = None  # cached colored macro line; _pulse adds the heartbeat
        self._asked: str | None = None        # last plain-text prompt sent to the agents from the bar
        # branching conversation tree: nodes keyed by id, each {id,parent,role,text,agent,ts}.
        # _active = the node your next message hangs off (None → a fresh thread). Context for an
        # ask is ONLY the active node's lineage (root→here), so threads stay isolated.
        self._conv: dict = {}
        self._active: str | None = None
        self._pending_user: str | None = None     # the just-asked node awaiting its reply
        self._node_seq = 0
        self._expanded: set = set()                # reply node ids the user expanded in the tree
        self._last_reply_ts = None                 # dedupe agent replies arriving via terminal_state
        self._pipe_seen = None                     # started-ts of the last pipeline run seeded to threads

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
                    yield Static("Select a name to ground agents and see its price ladder.",
                                 id="book_detail")
                    with VerticalScroll(id="agent_reply_box"):
                        yield Static("", id="agent_reply")
                    # chat lives IN the conversation, not a shell bar at the screen bottom — type a
                    # plain question (no commands needed) and press Enter; click a name/tab to navigate.
                    yield Input(placeholder="Ask anything — type and press Enter · click a name to focus it",
                                id="cmdbar")
                with TabPane("Council", id="council_tab"):
                    yield VerticalScroll(Static("Focus a name (click it in the Book grid or watchlist) — "
                                                "the Dialectic Council reconciles one verdict for it.\n\n"
                                                "Just ask in plain text (e.g. \"convene the council on GMX\" "
                                                "or \"bear case on AGA\") — no commands needed.",
                                                id="council_body"))
                with TabPane("Live What-If", id="whatif"):
                    with Horizontal(classes="row"):
                        yield Input(placeholder="ticker — blank uses the focused name", id="wf_ticker")
                        yield Input(placeholder="load a saved scenario by name…", id="wf_scenario")
                    yield Input(placeholder="overrides (silver=+5 ry=-0.5)  ·  or type a plain-text idea to prototype  ·  Enter",
                                id="wf_overrides")
                    yield Static("", id="wf_knobs")
                    with Horizontal(classes="row"):
                        yield Button("− step", id="k_down", classes="knob")
                        yield Button("+ step", id="k_up", classes="knob")
                        yield Button("Reset", id="k_clear", classes="knob")
                        yield Button("▶ Run", id="wf_run", variant="warning")
                        yield Button("Decompose", id="wf_decomp", classes="knob")
                        yield Input(placeholder="save as…", id="wf_name")
                        yield Button("Save", id="wf_save")
                    yield Static("Type an idea above (e.g. “silver +8, real yield −0.5”) and press Enter — "
                                 "or click a knob then ▶ Run.", id="wf_result")
                    yield Static("", id="wf_history")
                    yield Static("", id="wf_status")
                    yield Static("", id="wf_hint")
                with TabPane("Regime", id="regime_tab"):
                    yield VerticalScroll(Static("…", id="regime"))
                with TabPane("Profile", id="profile_tab"):
                    yield VerticalScroll(Static("Click a company in the Book (or press p) for its profile.",
                                                id="profile_body"))
                with TabPane("Dossier", id="dossier_tab"):
                    with Horizontal():
                        with Vertical(id="dossier_list"):
                            yield Static("DOSSIERS", classes="railtitle")
                            yield Static("…", id="dossier_index")
                            yield Input(placeholder="open #  or  ticker", id="dossier_open")
                        yield VerticalScroll(Markdown("", id="dossier_body"))
            with VerticalScroll(id="signals"):
                yield Static("INTEL", classes="railtitle")
                yield Static("no agent activity yet", id="signalbody")
        yield Static("", id="ticker")          # live macro ticker (always on) — see _pulse

    def on_mount(self) -> None:
        t = self.query_one("#booktbl", DataTable)
        for c, w in (("", 3), ("TICKER", 7), ("PRICE", 8), ("ARCH", 8), ("R", 4), ("BAND", 14),
                     ("T", 3), ("Q", 3), ("V", 3), ("UP%", 5), ("FLOOR", 6),
                     ("GATE", 13), ("DIRECTIVE", 22)):
            t.add_column(c, key=c or "role", width=w)
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.set_interval(0.5, self._pulse)     # ~2 Hz heartbeat (no network) — keeps the desk live
        self.refresh_data()
        self.call_after_refresh(lambda: self.query_one("#cmdbar", Input).focus())   # chat-first: ready to type

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
        self._maybe_seed_pipeline(state)
        self._render_agent_reply(state)
        self._render_wf_knobs()
        self._render_regime(state)
        try:
            active = self.query_one("#tabs", TabbedContent).active
            if self._focus and active == "profile_tab":
                self._render_profile(self._focus)
            elif active == "council_tab":
                self._render_council(self._focus)
        except Exception:
            pass
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
        # what MOVED the MRI: session delta + the dominant driver (low MRI = risk-on, so ▼ is GREEN)
        hist = [h for h in self._hist.get("mri", []) if _num(h) is not None]
        if len(hist) >= 2:
            d = _num(hist[-1]) - _num(hist[0])
            if abs(d) >= 0.1:
                line.append(f" {'▲' if d > 0 else '▼'}{abs(d):.1f}", style=(ORANGE if d > 0 else GREEN))
        drv = tape.get("top_mri_driver")
        if drv:
            line.append(f" {drv}", style=DIM)
        line.append_text(sep)
        # POSTURE — the master temperature dial (book-level size cap that composes everywhere)
        posture = state.get("posture") or {}
        if posture.get("label"):
            pcode = posture.get("code")
            pc = GREEN if pcode == "spear_exploit" else (ORANGE if pcode == "defensive" else SILVER)
            line.append("POSTURE ", style=DIM)
            line.append(str(posture["label"]), style=f"bold {pc}")
            if _num(posture.get("cap")) is not None:
                capc = ORANGE if posture.get("headwind") else GREEN
                line.append(f" {posture['cap']:g}x", style=capc)
                if posture.get("headwind"):
                    line.append(" headwind", style=DIM)
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
            # clicking the name (glyph + ticker + rating) opens the company profile — the same
            # action the Book table rows fire, so the watch rail is a live nav rail too.
            click = Style(meta={"@click": f"app.open_profile('{tk}')"})
            hc = Style.parse(health_color(r))
            out.append(f"{mark}", style=AMBER)
            out.append(f"{_role_glyph(tk, nodes)} ", style=hc + click)
            out.append(f"{tk:<7}", style=Style.parse("bold white") + click)
            out.append(f"{_fmt(r):>4} ", style=hc + click)
            out.append_text(_bar(r, 8))
            out.append("\n     ", style=DIM)
            out.append(f"{str(b.get('band','—'))[:14]:<14} ", style=health_color(r))
            out.append_text(_floor_edge(b))
            sub = b.get("subarchetype")
            if sub:                                           # finer-sort hint (differentiates royalties)
                out.append(f"  {_sub_abbr(sub)}", style=TEAL)
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
            px = _num((nodes.get(tk) or {}).get("price")) or _num((b.get("ladder") or {}).get("price"))
            tbl.add_row(
                Text(f"{focus_mark}{_role_glyph(tk, nodes)}", style=AMBER if tk == prev else health_color(r)),
                tick,
                Text(_money(px), style="white", justify="right"),
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
        node = ((self._state or {}).get("nodes") or {}).get(ticker, {}) or {}
        fund = self._fund.get(ticker) or {}
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) if isinstance(pil.get("V"), dict) else {}
        rib = b.get("confidence_ribbon", {}) or {}
        L = b.get("ladder", {}) or {}
        rating = b.get("rating")
        price = _num(node.get("price")) or _num(L.get("price"))

        # ── header: ticker · role · archetype ························· band (bright) ──
        head = Text()
        head.append(f"{ticker}  ", style=f"bold {GOLD}")
        if node.get("role"):
            head.append(f"{node.get('role')} · ", style=DIM)
        head.append(f"{_arch_short(b.get('archetype'), b.get('archetype_code'))}", style=DIM)
        head.append(f"   {b.get('band', '—')}", style=f"bold {health_color(rating)}")

        # ── price line: bright last + day change · upside · floor (margin of safety) ──
        pl = Text("price ", style=DIM)
        pl.append(f"{_money(price)}", style="bold white")
        chg = _num(fund.get("changePercentage"))
        if chg is not None:
            pl.append(f"  {'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%", style=(GREEN if chg >= 0 else RED))
        up = _num(V.get("upside_pct"))
        if up is not None:
            pl.append("    upside ", style=DIM); pl.append(f"{up:+.0f}%", style=(GREEN if up >= 0 else RED))
        fl = _num(L.get("floor")); cov = _num(V.get("floor_coverage")); dtf = _num(V.get("downside_to_floor_pct"))
        if fl is not None:
            pl.append("    floor ", style=DIM); pl.append(f"{_money(fl)}", style=ORANGE)
            if cov is not None:
                pl.append(f" φ{cov:.2f}", style=(GREEN if cov >= 1 else DIM))
            if dtf is not None:
                pl.append(f" −{abs(dtf):.0f}%", style=ORANGE)

        # ── fundamentals (FMP where covered; many juniors aren't — degrade gracefully) ──
        fl2 = Text("mcap ", style=DIM)
        fl2.append(f"{_compact(fund.get('marketCap'))}".rjust(0), style=SILVER)
        fl2.append("   β ", style=DIM); fl2.append(f"{_fmt(fund.get('beta'), '{:.2f}')}", style=SILVER)
        if _num(fund.get("volume")) is not None:
            fl2.append("   vol ", style=DIM)
            fl2.append(f"{_compact(fund.get('volume'))}/{_compact(fund.get('averageVolume'))} avg", style=SILVER)
        if not fund:
            fl2.append("   (no FMP coverage — engine price)", style=DIM)
        rbar = _range_bar(fund.get("range"), price)

        # ── conviction: T/Q/V · ρ · ribbon · gate ──
        tqv = Text()
        for k in ("T", "Q", "V"):
            s = _score(pil.get(k))
            tqv.append(f"{k} ", style=DIM); tqv.append(f"{_fmt(s)}  ", style=health_color(s))
        if _num(V.get("rho")) is not None:
            tqv.append(f"ρ {_fmt(V.get('rho'), '{:.2f}')}  ", style=SILVER)
        tqv.append(f"±{_fmt(rib.get('plus_minus'), '{:.2f}')} ({rib.get('quality', '?')})  ",
                   style=quality_color(rib.get("quality")))
        tqv.append_text(_gate_text(b, short=False))

        bar, legend = _ladder([("F", L.get("floor"), ORANGE), ("b", L.get("bear"), RED),
                               ("●", price, "white"), ("◆", L.get("base"), GOLD),
                               ("▲", L.get("bull"), GREEN)])

        cat = b.get("catalysts") or []
        cat_line = Text()
        if cat:
            sig = _num(b.get("catalyst_signal"))
            cat_line.append(f"↯{len(cat)} ", style=(GREEN if (sig or 0) >= 0 else ORANGE))
            if sig is not None:
                cat_line.append(f"signal {sig:+.1f}  ", style=DIM)
            cat_line.append(" · ".join(str(c.get("headline", c.get("type", "event")))[:30] for c in cat[:3]),
                            style=SILVER)

        parts = [head, pl, fl2]
        if rbar:
            parts.append(rbar)
        parts += [Text(""), tqv, bar, legend]
        if cat:
            parts.append(cat_line)
        det.update(Group(*parts))

    # ------------------------------------------------------------------ company profile
    def action_open_profile(self, ticker: str = "") -> None:
        tk = (ticker or self._focus or "").strip()
        if not tk:
            return
        self._set_focus(tk, move_cursor=True)
        self.action_tab("profile_tab")
        self._render_profile(tk)

    # ------------------------------------------------------------------ Dialectic Council
    def _memory(self):
        """Lazy Living Memory handle (read-only here). None if the substrate is unavailable."""
        m = getattr(self, "_mem", None)
        if m is None:
            try:
                import living_memory
                self._mem = living_memory.LivingMemory()
                m = self._mem
            except Exception:
                self._mem = False
                return None
        return m or None

    def _research(self):
        """Lazy research-cache handle (sourced filings data). None if unavailable."""
        rc = getattr(self, "_rc", None)
        if rc is None:
            try:
                import research_cache
                self._rc = research_cache.ResearchCache()
                rc = self._rc
            except Exception:
                self._rc = False
                return None
        return rc or None

    def _sourced_mcap(self, ticker, price):
        """Market cap from the SOURCED filing share count × live price — preferred over FMP's
        marketCap field, which goes stale for post-merger TSXV micro-caps (FMP missed AGA.V's
        merger issuance: it shows ~$112M on ~173M implied shares vs the filed 208.6M). Returns
        (mcap, shares) in the price's currency, or None when shares aren't sourced."""
        rc = self._research()
        p = _num(price)
        if rc is None or not p or p <= 0:
            return None
        sh = _num(rc.value(ticker, "shares_out"))
        if not sh or sh <= 0:
            return None
        return sh * p, sh

    def _regime_ctx(self) -> dict:
        """The live regime context to stamp on a memory entry (so it's regime-recallable later)."""
        st = self._state or {}
        return {"mri": st.get("mri"),
                "net_tilt": (st.get("macro_tape") or {}).get("net_tilt"),
                "posture": (st.get("posture") or {}).get("code")}

    def _write_note(self, text: str, ticker: str = "") -> None:
        """Persist a plain-text research note to Living Memory, tagged to the focused name and
        stamped with the live regime — so the next Council run / What-If inherits it. This is the
        'type a thought, it becomes structured, connected memory' loop."""
        text = (text or "").strip()
        if not text:
            return
        mem = self._memory()
        tk = (ticker or self._focus or "").strip() or None
        if mem is None:
            self._toast("memory unavailable — note not saved", ORANGE)
            return
        try:
            mem.write("note", text=text, ticker=tk, regime=self._regime_ctx(), source="user")
            where = f" → {tk}" if tk else " (book-level)"
            self._toast(f"✎ note saved to memory{where} — Council & What-If will see it", TEAL)
            if self.query_one("#tabs", TabbedContent).active == "council_tab":
                self._render_council(self._focus)         # reflect it live in the name's thread
        except Exception as e:
            self._toast(f"note not saved: {e}", ORANGE)

    def _toast(self, msg, color=None) -> None:
        """Lightweight status line (reuses the what-if status slot; harmless if absent)."""
        try:
            self.query_one("#wf_status", Static).update(Text(str(msg), style=(color or SILVER)))
        except Exception:
            pass

    def _render_council(self, ticker) -> None:
        """The Dialectic Council view: the engine's grounded asymmetry as the Bull's factual basis,
        the floor as the Bear's invalidation anchor, and — once a /council run has written one — the
        reconciled verdict + convergence + tension + caveats pulled live from Living Memory."""
        body = self.query_one("#council_body", Static)
        tk = (ticker or self._focus or "").strip()
        if not tk:
            body.update(f"[{DIM}]Focus a name (click in Book / watchlist), then this seats the "
                        f"Dialectic Council on it. Run [/]/council <ticker>[{DIM}] to convene.[/]")
            return
        b = self._baskets_by_ticker.get(tk) or {}
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) if isinstance(pil.get("V"), dict) else {}
        T = pil.get("T", {}) if isinstance(pil.get("T"), dict) else {}
        gate = b.get("gate", {}) or {}
        L = b.get("ladder", {}) or {}
        rating = b.get("rating")
        hc = health_color(rating)
        rule = f"[{BORDER}]{'─' * 58}[/]"

        # latest reconciled verdict from Living Memory (None until a /council run lands)
        verdict = None
        mem = self._memory()
        if mem is not None:
            try:
                verdict = mem.latest(ticker=tk, type="council_verdict")
            except Exception:
                verdict = None

        out = [f"[bold {GOLD}]DIALECTIC COUNCIL[/]  [bold white]{self._esc(tk)}[/]"
               f"   [{hc}]{_fmt(rating)}/10[/]  [{hc}]{self._esc(b.get('band','—'))}[/]"]
        # status line — reconciled verdict if present, else the engine's provisional directive
        if verdict:
            meta = verdict.get("meta", {}) or {}
            conv = meta.get("convergence", {}) or {}
            contested = conv.get("contested")
            cc = ORANGE if contested else GREEN
            when = str(verdict.get("ts", ""))[:16].replace("T", " ")
            out.append(f"  [{DIM}]STATUS[/] [bold {cc}]{self._esc(str(meta.get('stance','—')))}[/]"
                       f"   [{DIM}]convergence[/] [{cc}]{conv.get('bull','?')}/{conv.get('bear','?')}"
                       f"{'  CONTESTED' if contested else ''}[/]   [{DIM}]{when}[/]")
        else:
            out.append(f"  [{DIM}]STATUS[/] [{SILVER}]engine directive (pre-debate)[/] — "
                       f"run [{TEAL}]/council {self._esc(tk)}[/] to convene")
        out.append(rule)

        # two columns: BULL (asymmetry, grounded) | BEAR + LIQUIDITY (invalidation)
        def g(x, s="{:.2f}"):
            v = _num(x)
            return s.format(v) if v is not None else "—"
        out.append(f"[bold {GREEN}]BULL — asymmetry (engine-grounded)[/]")
        out.append(f"  φ floor-coverage  [{GREEN if (_num(V.get('floor_coverage')) or 0) >= 1 else SILVER}]"
                   f"{g(V.get('floor_coverage'))}[/]     ρ payoff  [{SILVER}]{g(V.get('rho'))}[/]")
        out.append(f"  upside  [{SILVER}]{g(V.get('upside_pct'),'{:.0f}%')}[/]"
                   f"     tailwind  [{SILVER}]{g(T.get('score'),'{:.1f}')}[/] "
                   f"[{DIM}]({self._esc(str(T.get('commodity','—')))})[/]")
        out.append(f"  ladder  [{DIM}]floor[/] {_money(L.get('floor'))} [{DIM}]· base[/] "
                   f"{_money(L.get('base'))} [{DIM}]· bull[/] {_money(L.get('bull'))}")
        out.append("")
        out.append(f"[bold {RED}]BEAR + LIQUIDITY SENTINEL — invalidation[/]")
        out.append(f"  hard invalidation  [{RED}]{_money(L.get('floor'))}[/] [{DIM}](floor leg)[/]")
        gcap = gate.get("cap")
        cap_str = "" if gcap is None else f" — cap {g(gcap, '{:.1f}')}"
        if gate.get("applied"):
            out.append(f"  [{ORANGE}]⚠ forensic gate active{cap_str}: "
                       f"{self._esc(str(gate.get('reason',''))[:40])}[/]")
        else:
            out.append(f"  [{DIM}]forensic gate clear (JSF){cap_str}[/]")
        out.append(f"  [{DIM}]dilution / liquidity / exit-friction surface on a live /council run[/]")
        out.append(rule)

        # ARBITER — one reconciled verdict + caveats (dissent preserved, never a rival number)
        out.append(f"[bold {AMBER}]ARBITER — single reconciled verdict[/]")
        if verdict:
            meta = verdict.get("meta", {}) or {}
            out.append(f"  [bold {hc}]{self._esc(verdict.get('text','') or meta.get('stance',''))}[/]")
            if meta.get("tension"):
                out.append(f"  [{DIM}]tension:[/] [{ORANGE}]{self._esc(str(meta['tension'])[:72])}[/]")
            for cav in (meta.get("caveats") or [])[:3]:
                out.append(f"  [{DIM}]⚑[/] [{SILVER}]{self._esc(str(cav)[:72])}[/]")
        else:
            out.append(f"  [{SILVER}]{self._esc(str(b.get('directive','—')))}[/]  [{DIM}](engine directive)[/]")
            posture = (self._state or {}).get("posture") or {}
            if _num(posture.get("cap")) is not None and posture.get("cap") != 1.0:
                pc = GREEN if not posture.get("headwind") else ORANGE
                out.append(f"  [{DIM}]posture composes:[/] [{pc}]{self._esc(str(posture.get('label','')))} "
                           f"{posture['cap']:g}x[/] [{DIM}]({self._esc(str(posture.get('rationale','')))})[/]")
            out.append(f"  [{DIM}]No Council verdict yet — the Bear's invalidation + reconciliation "
                       f"land here after[/] [{TEAL}]/council {self._esc(tk)}[/][{DIM}].[/]")

        # the name's LIVING research thread (everything-talks): notes, verdicts, theses, outcomes —
        # type "note: …" to add one; the next Council run inherits it.
        if mem is not None:
            try:
                thread = mem.query(ticker=tk, limit=6)
            except Exception:
                thread = []
            out.append(rule)
            out.append(f"[bold {TEAL}]RESEARCH THREAD[/]  [{DIM}]living memory[/]")
            if thread:
                glyphs = {"note": "✎", "council_verdict": "⚖", "thesis": "◆", "scenario_prior": "⊹",
                          "outcome": "✓", "regime_snapshot": "◷", "decision": "▸", "catalyst": "⛏",
                          "thread": "↯", "pin": "📌"}
                for e in thread:
                    g = glyphs.get(e.get("type"), "·")
                    when = str(e.get("ts", ""))[:10]
                    src = self._esc(str(e.get("source", "")))
                    out.append(f"  [{DIM}]{when}[/] {g} [{SILVER}]{self._esc(str(e.get('text',''))[:58])}[/]"
                               f"  [{DIM}]{src}[/]")
            else:
                out.append(f"  [{DIM}]empty — type[/] [{TEAL}]note: <your observation>[/] "
                           f"[{DIM}]to start this name's thread.[/]")
        body.update("\n".join(out))

    def _render_profile(self, ticker) -> None:
        body = self.query_one("#profile_body", Static)
        b = self._baskets_by_ticker.get(ticker)
        if not b:
            body.update(f"[{DIM}]No live data for {self._esc(ticker)}.[/]")
            return
        node = ((self._state or {}).get("nodes") or {}).get(ticker, {}) or {}
        fund = self._fund.get(ticker) or {}
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) if isinstance(pil.get("V"), dict) else {}
        rib = b.get("confidence_ribbon", {}) or {}
        L = b.get("ladder", {}) or {}
        gate = b.get("gate", {}) or {}
        rating = b.get("rating")
        hc = health_color(rating)
        price = _num(node.get("price")) or _num(L.get("price"))
        rule = f"[{BORDER}]{'─' * 58}[/]"

        # header
        hdr = f"[bold {GOLD}]{self._esc(ticker)}[/]"
        if fund.get("companyName"):
            hdr += f"  [{SILVER}]{self._esc(fund.get('companyName'))}[/]"
        meta = " · ".join(self._esc(x) for x in (fund.get("exchange"), fund.get("sector"), node.get("role")) if x)
        if meta:
            hdr += f"   [{DIM}]{meta}[/]"
        out = [hdr, rule]

        # taxonomy: archetype (how it's valued) · sub-archetype (finer sort) · sector tags
        arch = b.get("archetype")
        sub_label = b.get("subarchetype_label") or b.get("subarchetype")
        tax = []
        if arch:
            tax.append(f"[{DIM}]archetype[/] [{TEAL}]{self._esc(str(arch).replace('_', ' '))}[/]")
        if sub_label:
            tax.append(f"[{DIM}]›[/] [{SILVER}]{self._esc(str(sub_label))}[/]")
        if tax:
            out.append("  ".join(tax))
        tags = b.get("sector_tags") or []
        if tags:
            out.append("  ".join(f"[{BORDER}]\\[[/][{AMBER}]{self._esc(str(t))}[/][{BORDER}]][/]"
                                 for t in tags[:8]))

        # price + fundamentals
        chg = _num(fund.get("changePercentage"))
        pr = f"[{DIM}]PRICE[/] [bold white]{_money(price)}[/]"
        if chg is not None:
            pr += f" [{GREEN if chg >= 0 else RED}]{'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%[/]"
        # MCAP from SOURCED filing shares × live price (not FMP's stale marketCap field); when the
        # FMP feed disagrees materially, surface it as a flag so stale feeds are caught, not trusted.
        src_mc = self._sourced_mcap(ticker, price)
        fmp_mc = _num(fund.get("marketCap"))
        if src_mc:
            mc, sh = src_mc
            pr += f"    [{DIM}]MCAP[/] [{SILVER}]{_compact(mc)}[/] [{DIM}]({_compact(sh)}sh×px)[/]"
            if fmp_mc and (fmp_mc / mc < 0.87 or fmp_mc / mc > 1.15):
                pr += f"  [{ORANGE}]⚠ FMP feed {_compact(fmp_mc)}[/]"
        else:
            pr += f"    [{DIM}]MCAP[/] [{SILVER}]{_compact(fmp_mc)}[/]"
        pr += f"    [{DIM}]β[/] [{SILVER}]{_fmt(fund.get('beta'), '{:.2f}')}[/]"
        if _num(fund.get("volume")) is not None:
            pr += f"    [{DIM}]VOL[/] [{SILVER}]{_compact(fund.get('volume'))}/{_compact(fund.get('averageVolume'))}[/]"
        out.append(pr)
        rng = fund.get("range")
        if rng:
            try:
                lo, hi = [float(x) for x in str(rng).replace("$", "").split("-")[:2]]
                frac = max(0.0, min(1.0, (float(price) - lo) / (hi - lo))) if (price and hi > lo) else 0.0
                rc = GREEN if frac >= 0.66 else (RED if frac <= 0.33 else AMBER)
                out.append(f"[{DIM}]52wk[/] [{SILVER}]{_money(lo)}–{_money(hi)}[/]  [{rc}]{frac * 100:.0f}%[/]")
            except (ValueError, IndexError, TypeError):
                pass
        if not fund:
            out.append(f"[{DIM}](no FMP coverage — engine price; mcap/β/range unavailable)[/]")

        # conviction
        out.append(rule)
        out.append(f"[bold {AMBER}]CONVICTION[/]  [bold {hc}]{_fmt(rating)}/10[/]  [{hc}]{self._esc(b.get('band', '—'))}[/]")
        out.append(f"  [{DIM}]directive[/]  [{SILVER}]{self._esc(b.get('directive', '—'))}[/]")
        tline = "  "
        for k in ("T", "Q", "V"):
            s = _score(pil.get(k))
            tline += f"[{DIM}]{k}[/] [{health_color(s)}]{_fmt(s)}[/]   "
        if _num(V.get("rho")) is not None:
            tline += f"[{DIM}]ρ[/] [{SILVER}]{_fmt(V.get('rho'), '{:.2f}')}[/]   "
        tline += f"[{quality_color(rib.get('quality'))}]±{_fmt(rib.get('plus_minus'), '{:.2f}')} ({self._esc(rib.get('quality', '?'))})[/]"
        out.append(tline)
        up = _num(V.get("upside_pct")); fl = _num(L.get("floor")); cov = _num(V.get("floor_coverage"))
        dtf = _num(V.get("downside_to_floor_pct")); sup = _num(V.get("support"))
        vd = "  "
        if up is not None:
            vd += f"[{DIM}]upside[/] [{GREEN if up >= 0 else RED}]{up:+.0f}%[/]   "
        if fl is not None:
            vd += f"[{DIM}]floor[/] [{ORANGE}]{_money(fl)}[/]"
            vd += f"[{DIM}] φ{cov:.2f}[/]" if cov is not None else ""
            vd += "   "
        if dtf is not None:
            vd += f"[{ORANGE}]−{abs(dtf):.0f}% to floor[/]   "
        if sup is not None:
            vd += f"[{DIM}]support {sup:.2f}[/]"
        out.append(vd)
        gr = self._esc(gate.get("reason", "clean"))
        gl = f"  [{DIM}]gate[/]  [{RED if gate.get('applied') else GREEN}]{gr}[/]"
        if _num(gate.get("cap")) is not None and gate.get("applied"):
            gl += f" [{DIM}]· cap {_num(gate.get('cap')):.0f}[/]"
        out.append(gl)

        # valuation ladder points
        out.append(rule)
        pts = [("floor", L.get("floor"), ORANGE), ("bear", L.get("bear"), RED), ("price", price, "white"),
               ("base", L.get("base"), GOLD), ("bull", L.get("bull"), GREEN)]
        out.append(f"[bold {AMBER}]VALUATION[/]   " +
                   "   ".join(f"[{DIM}]{lab}[/] [{c}]{_money(_num(v))}[/]" for lab, v, c in pts if _num(v) is not None))

        # catalysts (full)
        cat = b.get("catalysts") or []
        sig = _num(b.get("catalyst_signal"))
        out.append(rule)
        out.append(f"[bold {AMBER}]CATALYSTS[/] [{DIM}]({len(cat)}{f' · signal {sig:+.1f}' if sig is not None else ''})[/]")
        for c in cat[:8]:
            out.append(f"  [{SILVER}]· {self._esc(str(c.get('headline', c.get('type', 'event')))[:52])}[/]"
                       f"  [{DIM}]{self._esc(c.get('type', ''))}[/]")
        if not cat:
            out.append(f"  [{DIM}]none in window[/]")

        # notes (agent annotations on this name)
        annos = ((self._state or {}).get("agent_annotations") or {}).get(ticker, []) or []
        out.append(rule)
        out.append(f"[bold {AMBER}]NOTES[/]")
        if annos:
            for a in annos[-6:]:
                col = _level_color(a.get("level"))
                out.append(f"  [{col}]{a.get('badge', '✦')}[/] [{SILVER}]{self._esc(str(a.get('reason', ''))[:52])}[/]"
                           f"  [{DIM}]·{self._esc(str(a.get('agent', '')))}[/]")
        else:
            out.append(f"  [{DIM}]none yet — ask in chat; the agents pin notes here[/]")

        # related research (clickable dossiers + threads bound to this name)
        doss = [d for d in self._decisions if str(d.get("ticker", "")).upper() == ticker.upper()]
        thr = [n for n in self._conv.values() if not n.get("parent") and (n.get("ticker") or "") == ticker]
        if doss or thr:
            out.append(rule)
            out.append(f"[bold {AMBER}]RELATED RESEARCH[/]")
            for d in doss[:5]:
                nm = self._esc(str(d.get("name", "")))
                out.append(f"  [@click=app.open_dossier('{nm}')][{TEAL}]▸ {self._esc(str(d.get('title', ''))[:38])}[/][/]"
                           f"  [{DIM}]dossier[/]")
            for n in thr[:5]:
                out.append(f"  [{TEAL}]▸ thread[/] [{SILVER}]{self._esc(str(n.get('text', ''))[:40])}[/]")

        # data & trust — every key input tagged by provenance so nothing is a black box
        out.append(rule)
        out.append(f"[bold {AMBER}]DATA & TRUST[/]  [{DIM}](● live · ◐ cached · ◆ sourced · … pending · ✕ placeholder)[/]")
        gl = {"live": (GREEN, "●"), "cached": (SILVER, "◐"), "stale": (ORANGE, "◐"),
              "config": (ORANGE, "▲"), "placeholder": (RED, "✕"), "na": (DIM, "·"),
              "web": (TEAL, "◆"), "pending": (ORANGE, "…")}
        for label, cls, note in self._provenance_rows(ticker, b):
            col, glyph = gl.get(cls, (SILVER, "·"))
            out.append(f"  [{col}]{glyph}[/] [{SILVER}]{self._esc(label)}[/]"
                       + (" " * max(1, 18 - len(label))) + f"[{DIM}]{self._esc(note)}[/]")
        body.update("\n".join(out))

    def _provenance_rows(self, ticker, b):
        """Per-input provenance for the focused name (audit knowledge × live freshness)."""
        feeds = (self._state or {}).get("data_freshness", {}).get("feeds", {}) or {}

        def age(feed):
            a = _num((feeds.get(feed) or {}).get("age_minutes"))
            return "" if a is None else (f"{a / 60:.0f}h" if a >= 90 else f"{a:.0f}m")

        def st(feed):
            return bool((feeds.get(feed) or {}).get("stale"))

        covered = bool(self._fund.get(ticker))
        rows = [
            ("price", "live", "yfinance"),
            ("fundamentals", "live" if covered else "na", f"FMP {age('macro')}" if covered else "no FMP coverage"),
            ("macro / regime", "stale" if st("macro") else "live", age("macro") or "—"),
            ("regime history / vol", "stale" if st("mri_history") else "cached", age("mri_history") or "—"),
            ("forensics", "cached", f"last quarter · {age('forensic') or '—'}"),
        ]
        # filings-derived inputs now come from the provenance-stamped research cache (web fallback)
        if getattr(self, "_rc", None) is None:
            try:
                from research_cache import ResearchCache
                self._rc = ResearchCache()
            except Exception:
                self._rc = False

        def rc_row(label, field):
            e = self._rc.get(ticker, field) if self._rc else None
            if not e:
                return (label, "config", "not sourced yet")
            if e.get("value") is None:
                return (label, "pending", f"pending — {str(e.get('note', ''))[:42]}")
            return (label, "web", f"web · {e.get('as_of', '')} · {e.get('confidence', '?')}")

        arch = str(b.get("archetype") or "")
        is_expl = ("convex" in arch or "explor" in arch
                   or (b.get("pillars", {}) or {}).get("V", {}).get("mode") == "asymmetry")
        if is_expl:
            rows += [
                rc_row("in-ground oz I", "in_ground_ageq_oz_indicated"),
                rc_row("in-ground oz Inf", "in_ground_ageq_oz_inferred"),
                rc_row("AISC", "aisc_per_oz"),
                rc_row("NAV / share", "nav_per_share"),
                rc_row("shares out", "shares_out"),
            ]
        else:
            rows += [
                rc_row("floor (book/sh)", "book_value_per_share"),
                rc_row("cash", "cash"),
                rc_row("shares out", "shares_out"),
            ]
        return rows

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
        # --- background research pipeline status (runs headless; the chat stays free) ---
        pipe = state.get("pipeline") or {}
        if pipe.get("status") and pipe.get("status") != "idle":
            st = str(pipe.get("status"))
            col = {"running": TEAL, "done": GREEN, "error": ORANGE}.get(st, AMBER)
            head = Text("PIPELINE ", style="bold #8C8C92")
            head.append(st.upper(), style=f"bold {col}")
            if pipe.get("theme"):
                head.append(f"  {pipe.get('theme')}", style=SILVER)
            if pipe.get("stage") and st == "running":
                head.append(f"  ·{pipe.get('stage')}", style=DIM)
            parts.append(head)
            for tk, v in (pipe.get("verdicts") or {}).items():
                verdict = v.get("verdict") if isinstance(v, dict) else v
                vc = {"APPROVE": GREEN, "CONDITIONAL": AMBER, "REJECT": RED}.get(str(verdict).upper(), SILVER)
                vl = Text(f"  {tk:<7} ", style=SILVER)
                vl.append(str(verdict), style=vc)
                parts.append(vl)
            if pipe.get("status") == "done" and pipe.get("verdicts"):
                parts.append(Text("  → seeded as research threads", style=DIM))
            for ev in (pipe.get("events") or [])[-3:]:
                if ev.get("message"):
                    parts.append(Text(f"  › {str(ev.get('message'))[:38]}", style=DIM))
            parts.append(Text(""))
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
            parts.append(Text("ask in chat to confirm or reject (human-gated)", style=DIM))
        else:
            parts.append(Text("none pending", style=DIM))

        integ = state.get("integrity", {}) or {}
        feeds = (state.get("data_freshness", {}) or {}).get("feeds", {}) or {}
        parts.append(Text("\nDATA", style="bold #8C8C92"))
        dl = Text()
        for lbl, key in (("macro", "macro"), ("regime", "mri_history"), ("forensic", "forensic"), ("peers", "peers")):
            a = _num((feeds.get(key) or {}).get("age_minutes"))
            if a is None:
                continue
            disp = f"{a / 60:.0f}h" if a >= 90 else f"{a:.0f}m"
            stale = (feeds.get(key) or {}).get("stale")
            dl.append(f"{lbl} ", style=DIM)
            dl.append(f"{disp}{'⚠' if stale else ''}  ", style=(ORANGE if stale else GREEN))
        parts.append(dl if dl.plain else Text("freshness unavailable", style=DIM))
        if integ.get("forensic_override_count"):
            parts.append(Text(f"⚠ {integ.get('forensic_override_count')} forensic waiver(s)", style=ORANGE))

        # --- LIVING MEMORY: the research stream (focused name first, then book-level) ---
        parts.append(Text("\nLIVING MEMORY", style="bold #8C8C92"))
        mem = self._memory()
        entries = []
        if mem is not None:
            try:
                if self._focus:
                    entries = mem.query(ticker=self._focus, limit=4)
                entries += [e for e in mem.query(limit=6) if e not in entries]
            except Exception:
                entries = []
        if entries:
            glyphs = {"note": "✎", "council_verdict": "⚖", "thesis": "◆", "scenario_prior": "⊹",
                      "outcome": "✓", "regime_snapshot": "◷", "decision": "▸", "catalyst": "⛏",
                      "thread": "↯", "pin": "📌"}
            for e in entries[:6]:
                col = AMBER if e.get("ticker") == self._focus else SILVER
                ln = Text(f"{glyphs.get(e.get('type'), '·')} ", style=col)
                if e.get("ticker"):
                    ln.append(f"{e['ticker']} ", style=f"bold {col}")
                ln.append(str(e.get("text", ""))[:30], style=SILVER)
                ln.append(f"  {str(e.get('ts',''))[5:10]}", style=DIM)
                parts.append(ln)
        else:
            parts.append(Text("type \"note: …\" to start the book's memory", style=DIM))
        self.query_one("#signalbody", Static).update(Group(*parts))

    # ------------------------------------------------------------------ dossier
    def _render_dossier_index(self) -> None:
        idx = self.query_one("#dossier_index", Static)
        if not self._decisions:
            idx.update(f"[{DIM}]No dossiers yet.\n\nSave one from the CONVERSATION (⇪ save on a thread),\n"
                       f"or just ask the desk to “run the pipeline on silver” /\n“write a dossier on GMX”.[/]")
            return
        lines = []
        for i, d in enumerate(self._decisions[:20]):
            name = self._esc(str(d.get("name", "")))
            sel = (d.get("name") == self._open_doss)
            mark = "▸" if sel else " "
            col = AMBER if sel else SILVER
            tk = self._esc(str(d.get("ticker") or "?"))
            title = self._esc(str(d.get("title", ""))[:20])
            age = d.get("age_minutes", "?")
            arm = (name == self._del_arm)
            lines.append(f"[{col}]{mark}[/][@click=app.open_dossier('{name}')] "
                         f"[bold {col}]{tk:<7}[/] [{col}]{title}[/]  [{DIM}]{age}m[/][/]"
                         f"  [@click=app.delete_dossier('{name}')]"
                         f"[{RED if arm else DIM}]{'✕ sure?' if arm else '✕'}[/][/]")
        idx.update("\n".join(lines))

    def action_open_dossier(self, name: str) -> None:
        self.action_tab("dossier_tab")
        self._open_doss = name
        self._del_arm = None
        self._render_dossier_index()
        self._open_dossier(name)
        try:
            self.query_one("#dossier_open", Input).value = ""
        except Exception:
            pass

    def action_delete_dossier(self, name: str) -> None:
        if self._del_arm != name:                          # first click arms, second deletes
            self._del_arm = name
            self._render_dossier_index()
            self._status(Text("click ✕ again to delete this dossier", style=ORANGE))
            return
        self._del_arm = None
        self._delete_dossier(name)

    @work(thread=True, group="dossier_del")
    def _delete_dossier(self, name: str) -> None:
        res = _post("/decisions/delete", {"name": name})
        ok = isinstance(res, dict) and res.get("ok")

        def after():
            if self._open_doss == name:
                self._open_doss = None
                try:
                    self.query_one("#dossier_body", Markdown).update("")
                except Exception:
                    pass
            self._status(Text("🗑 dossier deleted" if ok else f"delete failed: {(res or {}).get('error', '?')}",
                              style=(GREEN if ok else RED)))
            self._refresh_decisions()
        self.call_from_thread(after)

    @work(thread=True, group="dossier")
    def _open_dossier(self, name: str) -> None:
        res = _get(f"/decisions/item?name={quote(name)}")
        md = (res or {}).get("markdown") or (res or {}).get("body") or f"*could not load {name}*"
        self.call_from_thread(self.query_one("#dossier_body", Markdown).update, md)

    @work(thread=True, group="dossier_refresh", exclusive=True)
    def _refresh_decisions(self) -> None:
        """Pull the dossier index immediately (don't wait for the ~12s poll) after a save."""
        res = _get("/decisions")
        self._decisions = (res or {}).get("decisions", []) or []
        self.call_from_thread(self._render_dossier_index)

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
            self._fetch_fundamentals(ticker)
        if report:
            self._report_ui(ticker)

    @work(thread=True, group="fund")
    def _fetch_fundamentals(self, ticker: str) -> None:
        """FMP fundamentals for the focused name (engine-cached + budget-capped). Many TSXV juniors
        aren't covered on the free tier — we store {} so the panel degrades to engine data, no spam."""
        if ticker in self._fund:
            return
        res = _get(f"/fmp/fundamentals?ticker={quote(ticker)}")
        data = (res or {}).get("data") if isinstance(res, dict) else None
        self._fund[ticker] = data if isinstance(data, dict) else {}
        if self._focus == ticker:
            self.call_from_thread(self._render_book_detail, ticker)

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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tk = getattr(event.row_key, "value", event.row_key)      # click / Enter on a row → full profile
        if tk:
            self.action_open_profile(str(tk))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if self._focus:
            self._report_ui(self._focus)
        try:                                              # immediate render on tab switch (not 3s poll)
            active = self.query_one("#tabs", TabbedContent).active
            if active == "council_tab":
                self._render_council(self._focus)
            elif active == "profile_tab" and self._focus:
                self._render_profile(self._focus)
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id
        val = event.value.strip()
        if wid == "cmdbar":
            low = val.lower()
            if val.startswith("/") or val.startswith(":"):
                self._run_command(val)
            elif low.startswith("note:") or low.startswith("note "):
                self._write_note(val.split(":", 1)[-1].strip() if ":" in val else val[5:].strip())
            elif val:
                self._ask_agent(val)              # plain text -> ask the agents, reply lands in Book
            event.input.value = ""
            self.call_after_refresh(event.input.focus)   # stay in chat — no / to send the next one
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
        if bid == "k_down":
            self.action_wf_step(-1, False)
        elif bid == "k_up":
            self.action_wf_step(1, False)
        elif bid == "k_clear":
            self.action_wf_reset()
        elif bid == "wf_run":
            self._do_whatif()
        elif bid == "wf_decomp":
            self._wf_decompose()
        elif bid == "wf_save":
            self._do_save(self.query_one("#wf_name", Input).value.strip())

    # ------------------------------------------------------------------ actions
    def action_tab(self, tab_id: str) -> None:
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            tabs.active = tab_id
            # Chat/grid widgets live INSIDE the Book pane; a focused widget there would otherwise
            # drag the active tab back to Book. Blur on switch so clicking a tab actually sticks
            # (the user re-focuses chat by clicking it). Caller focuses a target widget if needed.
            self.set_focus(None)
        except Exception:
            pass

    @staticmethod
    def _tab_for(view) -> str:
        return {"book": "book", "whatif": "whatif", "what-if": "whatif", "live what-if": "whatif",
                "council": "council_tab", "council_tab": "council_tab",
                "regime": "regime_tab", "regime_tab": "regime_tab", "profile": "profile_tab",
                "profile_tab": "profile_tab",
                "dossier": "dossier_tab", "dossier_tab": "dossier_tab"}.get(str(view or "").lower(), "book")

    def action_whatif_focus(self) -> None:
        self.action_tab("whatif")
        if self._focus:
            self.query_one("#wf_ticker", Input).value = self._focus
        self._render_wf_knobs()
        self.query_one("#wf_overrides", Input).focus()

    # ---- interactive what-if knobs -----------------------------------------
    def _wf_active(self) -> bool:
        try:
            return self.query_one("#tabs", TabbedContent).active == "whatif"
        except Exception:
            return False

    def action_wf_knob(self, direction: int) -> None:
        if not self._wf_active():
            return
        self._wf_sel = (self._wf_sel + int(direction)) % len(_WF_KNOBS)
        self._render_wf_knobs()

    def action_wf_step(self, direction: float, fine: bool = False) -> None:
        if not self._wf_active():
            return
        name, key, kind, coarse, finestep, label = _WF_KNOBS[self._wf_sel]
        step = (finestep if fine else coarse) * (1 if direction >= 0 else -1)
        self._wf_knobs[name] = round(self._wf_knobs.get(name, 0.0) + step, 4)
        self._sync_knobs(); self._render_wf_knobs(); self._wf_live()

    def action_wf_reset(self) -> None:
        for n in self._wf_knobs:
            self._wf_knobs[n] = 0.0
        self._sync_knobs(); self._render_wf_knobs()
        try:
            self.query_one("#wf_result", Static).update(Text("knobs reset", style=DIM))
        except Exception:
            pass

    def _sync_knobs(self) -> None:
        try:
            self.query_one("#wf_overrides", Input).value = self._wf_overrides_from_knobs()
        except Exception:
            pass

    def _wf_overrides_from_knobs(self) -> str:
        parts = []
        for name, key, kind, coarse, fine, label in _WF_KNOBS:
            v = self._wf_knobs.get(name, 0.0)
            if abs(v) < 1e-9:
                continue
            parts.append(f"{key}={v:+g}%" if kind == "pct" else f"{key}={v:+g}")
        return " ".join(parts)

    def _knobs_from_overrides(self, ov: str) -> None:
        for n in self._wf_knobs:
            self._wf_knobs[n] = 0.0
        for tok in str(ov or "").replace(",", " ").split():
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            name = _ALIAS_TO_KNOB.get(k.strip().lower())
            if not name:
                continue
            try:
                self._wf_knobs[name] = float(v.strip().rstrip("%"))
            except ValueError:
                pass

    def _wf_live(self) -> None:
        if self._wf_timer is not None:
            try:
                self._wf_timer.stop()
            except Exception:
                pass
        self._wf_timer = self.set_timer(0.5, self._do_whatif)   # debounce live revalue while stepping

    def _render_wf_knobs(self) -> None:
        t = Text()
        for i, (name, key, kind, coarse, fine, label) in enumerate(_WF_KNOBS):
            v = self._wf_knobs.get(name, 0.0)
            sel = i == self._wf_sel
            nm_col = AMBER if sel else (SILVER if abs(v) > 1e-9 else DIM)
            disp = (f"{v:+g}{'%' if kind == 'pct' else ''}") if abs(v) > 1e-9 else "·"
            click = Style(meta={"@click": f"app.wf_sel({i})"})       # click a knob to select it
            t.append(f"{'▸' if sel else ' '}{label:<8}", style=Style.parse(f"bold {nm_col}") + click)
            t.append(f"{disp:>7}", style=Style.parse(GREEN if v > 0 else (RED if v < 0 else DIM)) + click)
            t.append("    " if i % 2 == 0 else "\n")
        try:
            self.query_one("#wf_knobs", Static).update(t)
        except Exception:
            pass

    def action_wf_sel(self, i: int) -> None:
        """Click-select a what-if knob (replaces the [ ] keys); then the ± buttons nudge it."""
        try:
            self._wf_sel = int(i) % len(_WF_KNOBS)
            self._render_wf_knobs()
        except Exception:
            pass

    @work(thread=True, group="wfproto", exclusive=True)
    def _wf_prototype_bg(self, idea: str, ticker: str) -> None:
        """Elevate a plain-text idea into a runnable scenario: a headless agent translates the idea
        into knob overrides, which then fill the knobs + run live."""
        self.call_from_thread(lambda: self.query_one("#wf_result", Static).update(
            Text(f"⟳ prototyping idea → scenario…  “{idea[:48]}”", style=TEAL)))
        prompt = ("Translate this market idea into CommodityEx what-if overrides. Knobs and units: "
                  "silver (+/- $), gold (+/- $), ry (+/- percentage points of real yield), "
                  "dxy (+/- index pts), peer (+/-% EV/oz multiple), vol (+/-% silver vol), "
                  "mri (+/- regime score). Return ONLY one line of space-separated key=value pairs "
                  "(deltas like silver=+8 ry=-0.5, or percents like peer=+20%). No prose, no fences. "
                  f"Idea: {idea}")
        try:
            out = subprocess.run(self._ask_argv(prompt), capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_ASK_TIMEOUT", "180")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            raw = (out.stdout or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._status, Text("prototype: CLI not found — set CEX_ASK_CMD", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"prototype failed: {exc}", style=ORANGE)); return
        ov = " ".join(tok for tok in raw.replace(",", " ").split()
                      if "=" in tok and tok.split("=", 1)[0].strip().lower() in _ALIAS_TO_KNOB)
        if not ov:
            self.call_from_thread(self._status, Text("couldn't translate idea — try explicit overrides", style=ORANGE)); return

        def apply():
            self._knobs_from_overrides(ov); self._render_wf_knobs()
            self.query_one("#wf_overrides", Input).value = ov
            self._wf_source = "idea"
            self.query_one("#wf_result", Static).update(Text(f"idea → {ov}  · running…", style=GREEN))
            self._run_whatif(ticker, ov)
        self.call_from_thread(apply)

    @work(thread=True, group="wfdecomp", exclusive=True)
    def _wf_decompose(self) -> None:
        """Granularity: attribute the move to each lever by revaluing one knob at a time."""
        ticker = self.query_one("#wf_ticker", Input).value.strip()
        active = [(n, k, kind) for (n, k, kind, c, f, l) in _WF_KNOBS if abs(self._wf_knobs.get(n, 0.0)) > 1e-9]
        if not active:
            self.call_from_thread(self._status, Text("set some knobs first, then Decompose", style=ORANGE)); return
        self.call_from_thread(lambda: self.query_one("#wf_result", Static).update(
            Text("⟳ decomposing the move per driver…", style=TEAL)))
        rows = []
        for n, k, kind in active:
            v = self._wf_knobs[n]
            ov = f"{k}={v:+g}%" if kind == "pct" else f"{k}={v:+g}"
            res = _post("/action/whatif", {"ticker": ticker, "overrides": ov})
            dp = (res.get("delta") or {}).get("intrinsic_pct") if isinstance(res, dict) else None
            rows.append((n, ov, _num(dp)))
        comb = _post("/action/whatif", {"ticker": ticker, "overrides": self._wf_overrides_from_knobs()})
        cdp = _num((comb.get("delta") or {}).get("intrinsic_pct")) if isinstance(comb, dict) else None
        self.call_from_thread(self._show_decomp, ticker, rows, cdp)

    def _show_decomp(self, ticker, rows, cdp) -> None:
        t = Text(f"{ticker} — per-driver attribution of Δ intrinsic\n", style=f"bold {GOLD}")
        mx = max((abs(d) for _, _, d in rows if d is not None), default=1.0) or 1.0
        for name, ov, d in sorted(rows, key=lambda r: -(abs(r[2]) if r[2] is not None else 0)):
            w = round(abs(d) / mx * 16) if d is not None else 0
            t.append(f"{ov:<14}", style=SILVER)
            t.append("▰" * w + " " * (16 - w), style=(GREEN if (d or 0) >= 0 else RED))
            t.append(f" {_fmt(d)}%\n", style=(GREEN if (d or 0) >= 0 else RED))
        if cdp is not None:
            t.append(f"{'COMBINED':<14}", style=f"bold {AMBER}")
            t.append(f"{'':16} {_fmt(cdp)}%", style=f"bold {(GREEN if cdp >= 0 else RED)}")
            interact = sum(d for _, _, d in rows if d is not None)
            t.append(f"   (interaction {cdp - interact:+.1f}pp)", style=DIM)
        self.query_one("#wf_result", Static).update(t)

    def action_cmd(self) -> None:
        """Focus the chat input (which now lives in the Book conversation panel). Plain text is a
        query to the desk agents; you never need a command or a hotkey."""
        self.action_tab("book")
        try:
            self.query_one("#cmdbar", Input).focus()
        except Exception:
            pass

    def action_focus_chat(self) -> None:
        """Click-to-type: clicking the conversation routes here and focuses the chat input."""
        self.action_cmd()

    def _ask_agent(self, text: str) -> None:
        """Plain-text query → a *background* headless agent. Hangs off the active conversation node
        (None → a fresh thread). Context sent to the agent is ONLY the active branch's lineage, so
        research threads stay isolated. Both query and reply land in the CONVERSATION tree (Book)."""
        text = text.strip()
        if not text:
            return
        self._asked = text
        new_thread = self._active is None
        uid = self._new_node("you", text, self._active)
        if new_thread:                               # a thread binds to what you're looking at now
            self._conv[uid]["ticker"] = self._focus
            try:
                self._conv[uid]["scenario"] = self.query_one("#wf_overrides", Input).value.strip()
            except Exception:
                self._conv[uid]["scenario"] = ""
        self._pending_user = uid
        self._active = uid
        self.action_tab("book")
        self._render_agent_reply(self._state)        # show the pending state immediately
        self._ask_agent_bg(text, uid)

    # ---- conversation tree -------------------------------------------------
    def _new_node(self, role: str, text: str, parent, agent=None) -> str:
        self._node_seq += 1
        nid = str(self._node_seq)
        self._conv[nid] = {"id": nid, "parent": parent, "role": role,
                            "text": str(text), "agent": agent, "ts": time.time()}
        return nid

    def _lineage(self, nid):
        chain, seen = [], set()
        while nid and nid in self._conv and nid not in seen:
            seen.add(nid); chain.append(self._conv[nid]); nid = self._conv[nid]["parent"]
        return list(reversed(chain))

    def _branch_root(self, nid):
        cur = nid
        while cur and self._conv.get(cur, {}).get("parent"):
            cur = self._conv[cur]["parent"]
        return cur

    def _roots(self):
        return [n for n in self._conv.values() if not n.get("parent")]

    def _thread_meta(self, nid):
        """The name + scenario a thread is bound to (captured on its root)."""
        root = self._conv.get(self._branch_root(nid)) or {}
        return root.get("ticker"), root.get("scenario")

    def _maybe_seed_pipeline(self, state) -> None:
        """When a background pipeline finishes, turn each surviving name into a context-bound research
        thread (seeded with the finding) so the run flows INTO your research instead of just being a
        readout. Also persists the full report as a Dossier memo. Runs once per completed run."""
        pipe = (state or {}).get("pipeline") or {}
        if pipe.get("status") != "done" or pipe.get("started") is None or pipe.get("started") == self._pipe_seen:
            return
        self._pipe_seen = pipe.get("started")
        theme = pipe.get("theme") or "pipeline"
        seeded = 0
        for tk, v in (pipe.get("verdicts") or {}).items():
            verdict = (v.get("verdict") if isinstance(v, dict) else str(v)) or "—"
            if str(verdict).upper() == "REJECT":          # survivors become threads; rejects stay in the panel
                continue
            note = (v.get("note") if isinstance(v, dict) else "") or ""
            seed = f"[{verdict}] {note}".strip()
            aid = self._new_node("agent", f"Pipeline finding ({theme}): {seed}", None, agent="pipeline")
            self._conv[aid]["ticker"] = tk
            self._conv[aid]["scenario"] = ""
            seeded += 1
        self._save_pipeline_dossier(pipe)
        if seeded:
            self._status(Text(f"⑂ pipeline seeded {seeded} research thread(s) — open CONVERSATION to dig in",
                              style=GREEN))

    def _save_pipeline_dossier(self, pipe) -> None:
        body = (pipe.get("result") or "").strip()
        if not body:
            return
        import datetime
        theme = pipe.get("theme") or "pipeline"
        verds = ", ".join(f"{tk} {(v.get('verdict') if isinstance(v, dict) else v)}"
                          for tk, v in (pipe.get("verdicts") or {}).items())
        out = [f"# Pipeline — {theme}", "",
               f"_run {datetime.datetime.now():%Y-%m-%d %H:%M}_" + (f" · {verds}" if verds else ""),
               "", body]
        try:
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "decisions")
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(theme))[:20] or "pipeline"
            with open(os.path.join(d, f"pipeline_{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md"),
                      "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            self._refresh_decisions()
        except Exception:
            pass

    @staticmethod
    def _esc(s) -> str:
        return str(s).replace("\\", "\\\\").replace("[", "\\[")   # neutralise markup in user/agent text

    def action_new_thread(self) -> None:
        self._active = None
        self._render_agent_reply(self._state)
        self._status(Text("✦ new thread — your next message starts fresh (no prior context)", style=TEAL))

    def action_sel_node(self, nid: str) -> None:
        if nid in self._conv:
            self._active = nid
            self._render_agent_reply(self._state)
            self._status(Text("⤷ following up on this reply — next message forks here", style=GREEN))

    def action_sel_branch(self, root_nid: str) -> None:
        # jump to a thread: make its most-recent node active AND restore its research frame
        tip = max((n for n in self._conv.values() if self._branch_root(n["id"]) == root_nid),
                  key=lambda n: n["ts"], default=None)
        if tip:
            self._active = tip["id"]
            self._restore_thread_frame(root_nid)
            self._render_agent_reply(self._state)

    def _restore_thread_frame(self, root_nid: str) -> None:
        """Re-load the name + what-if scenario a thread was opened on, so revisiting it restores the
        exact frame you were exploring — research and valuation stay in lockstep."""
        n = self._conv.get(root_nid) or {}
        tk, scen = n.get("ticker"), n.get("scenario")
        restored = []
        if tk:
            self._set_focus(tk, move_cursor=True)
            restored.append(tk)
        if scen:
            try:
                self.query_one("#wf_overrides", Input).value = scen
                self._knobs_from_overrides(scen)
                self._render_wf_knobs()
                restored.append(scen)
            except Exception:
                pass
        if restored:
            self._status(Text(f"↻ restored frame: {' · '.join(restored)}", style=TEAL))

    def action_toggle_node(self, nid: str) -> None:
        self._expanded.discard(nid) if nid in self._expanded else self._expanded.add(nid)
        self._render_agent_reply(self._state)

    def action_save_thread(self) -> None:
        """Turn the active thread into a saved research memo (data/decisions → the Dossier tab)."""
        chain = self._lineage(self._active)
        if not chain:
            self._status(Text("no active thread to save", style=ORANGE)); return
        import datetime
        root = self._conv.get(self._branch_root(self._active)) or {}
        tk = root.get("ticker") or "thread"
        out = [f"# {tk} — {(root.get('text') or 'research thread')[:70]}", "",
               f"_cockpit research thread · {datetime.datetime.now():%Y-%m-%d %H:%M}_"]
        if root.get("scenario"):
            out.append(f"_scenario: {root['scenario']}_")
        out.append("")
        for m in chain:
            who = "**You**" if m["role"] == "you" else f"**{m.get('agent', 'claude')}**"
            out.append(f"{who}: {m['text']}\n")
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "decisions")
        try:
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(tk))[:16] or "thread"
            path = os.path.join(d, f"{safe}_thread_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
        except Exception as exc:
            self._status(Text(f"save failed: {exc}", style=ORANGE)); return
        self._status(Text(f"✓ thread saved → Dossier ({os.path.basename(path)})", style=GREEN))
        self._refresh_decisions()

    def _ask_argv(self, prompt: str):
        """Headless one-shot for the prompt bar. Configurable (CEX_ASK_CMD, default 'claude -p
        {prompt}') so it fits the user's CLI; shares the cockpit's permission allowlist."""
        import shlex
        tmpl = os.environ.get("CEX_ASK_CMD", "claude -p {prompt}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            return [prompt if p == "{prompt}" else p for p in parts]
        return parts + [prompt]

    @work(thread=True, group="ask", exclusive=True)
    def _ask_agent_bg(self, text: str, uid: str) -> None:
        _post("/agent/activity", {"agent": "cockpit", "kind": "prompt", "summary": text, "ticker": self._focus})
        self.call_from_thread(self._status, Text("⟳ asking… (chat stays free; reply lands in Book)", style=TEAL))
        # context = ONLY this thread's lineage (prior turns above the new question), not other branches
        chain = self._lineage(self._conv.get(uid, {}).get("parent"))
        ctx = ""
        if chain:
            lines = "\n".join(("You: " if m["role"] == "you" else "Assistant: ") + str(m["text"])[:400]
                              for m in chain)
            ctx = f"Earlier in THIS research thread:\n{lines}\n\nContinue this thread.\n\n"
        # the thread is self-aware: it carries the name + scenario it was opened on
        tk, scen = self._thread_meta(uid)
        bind = ""
        if tk:
            bind += f"This research thread is about {tk}. "
        if scen:
            bind += f"Its working what-if scenario is: {scen}. "
        if bind:
            bind += "Ground your answer in that name/scenario unless told otherwise.\n"
        prompt = f"{ctx}{bind}{text}"
        try:
            out = subprocess.run(self._ask_argv(prompt), capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_ASK_TIMEOUT", "300")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            reply = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._status, Text("ask: CLI not found — set CEX_ASK_CMD", style=ORANGE)); return
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._status, Text("ask timed out — raise CEX_ASK_TIMEOUT", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"ask failed: {exc}", style=ORANGE)); return
        reply = reply or "(no output — check CEX_ASK_CMD permission flags)"
        _post("/agent/activity", {"agent": "claude", "kind": "reply", "summary": reply[:180], "text": reply[:6000]})
        self.call_from_thread(self._status, Text("✓ reply in the Book tab", style=GREEN))

    def _render_agent_reply(self, state) -> None:
        rep = (state or {}).get("agent_reply") or {}
        # fold a freshly-arrived reply into the tree — but only if it answers a cockpit ask
        # (pending_user set); interactive-pane turns are left to the AGENT STREAM, not the tree.
        if rep.get("text") and rep.get("ts") != self._last_reply_ts and self._pending_user:
            self._last_reply_ts = rep.get("ts")
            aid = self._new_node("agent", rep["text"], self._pending_user, agent=rep.get("agent", "claude"))
            self._active = aid                     # stay on this thread for a natural follow-up
            self._pending_user = None
            try:
                self.query_one("#agent_reply_box", VerticalScroll).scroll_end(animate=False)
            except Exception:
                pass
        self.query_one("#agent_reply", Static).update(self._conversation_markup())

    def _council_strip(self, tk) -> list:
        """A compact Council reconciliation for the focused name, shown atop the Book conversation —
        the verdict (from Living Memory if a /council ran, else the engine directive) + φ/ρ/upside,
        with a click-through to the full debate. Empty when no name is focused."""
        tk = (tk or "").strip()
        b = self._baskets_by_ticker.get(tk) if tk else None
        if not b:
            return []
        V = (b.get("pillars", {}) or {}).get("V", {}) or {}
        hc = health_color(b.get("rating"))

        def g(x, s="{:.2f}"):
            v = _num(x)
            return s.format(v) if v is not None else "—"
        verdict_txt, vcol = str(b.get("directive", "—")), SILVER
        mem = self._memory()
        if mem is not None:
            try:
                cv = mem.latest(ticker=tk, type="council_verdict")
            except Exception:
                cv = None
            if cv:
                meta = cv.get("meta", {}) or {}
                conv = meta.get("convergence", {}) or {}
                verdict_txt = f"{meta.get('stance','')} · {conv.get('bull','?')}/{conv.get('bear','?')}"
                vcol = ORANGE if conv.get("contested") else GREEN
        return [
            f"[b {GOLD}]COUNCIL[/] [b white]{self._esc(tk)}[/] [{hc}]{_fmt(b.get('rating'))}/10[/]"
            f"  [{vcol}]{self._esc(verdict_txt)}[/]"
            f"   [@click=app.go_council][{TEAL}]full debate ›[/][/]",
            f"[{DIM}]φ[/] {g(V.get('floor_coverage'))}  [{DIM}]ρ[/] {g(V.get('rho'))}  "
            f"[{DIM}]upside[/] {g(V.get('upside_pct'),'{:.0f}%')}   "
            f"[{DIM}]regime composes posture[/]",
            f"[{BORDER}]{'─' * 52}[/]",
        ]

    def action_go_council(self) -> None:
        self.action_tab("council_tab")
        self._render_council(self._focus)

    def _conversation_markup(self) -> str:
        roots = sorted(self._roots(), key=lambda n: n["ts"])
        lines = list(self._council_strip(self._focus))   # Council reconciliation, on the Book page
        head = (f"[b {AMBER}]CONVERSATION[/]   [@click=app.new_thread][{TEAL}]✦ new[/][/]"
                f"   [@click=app.focus_chat][{DIM}]› click to type[/][/]")
        if self._active:
            head += f"   [@click=app.save_thread][{GOLD}]⇪ save[/][/]"
        lines.append(head)
        if not self._conv:
            lines.append(f"[{DIM}]Type your question below and press Enter — plain English, no commands.[/]")
            lines.append(f"[{DIM}]Each question opens its own thread bound to the name you're on; click a[/]")
            lines.append(f"[{DIM}]reply's ‘⤷ follow up’ to branch. Click a name in the grid to focus it.[/]")
            return "\n".join(lines)
        active_root = self._branch_root(self._active) if self._active else None
        # THREADS rail — each titled by its bound ticker + opening question (capped so it stays clean)
        shown = roots[-7:]
        if len(roots) > len(shown):
            lines.append(f"[{DIM}]  +{len(roots) - len(shown)} older threads[/]")
        base_i = len(roots) - len(shown)
        for i, r in enumerate(shown, base_i + 1):
            mark = "▸" if r["id"] == active_root else " "
            col = AMBER if r["id"] == active_root else SILVER
            tag = (self._esc(r.get("ticker")) + " · ") if r.get("ticker") else ""
            title = (tag + self._esc(r["text"]))[:34]
            lines.append(f"[{col}]{mark}[/][@click=app.sel_branch('{r['id']}')] [{col}]{i} {title}[/][/]")
        # active thread transcript (lineage root→active); long replies collapse to keep it scannable
        chain = self._lineage(self._active)
        if chain:
            lines.append(f"\n[{DIM}]── thread ──[/]")
            for m in chain:
                if m["role"] == "you":
                    lines.append(f"[b {TEAL}]you ›[/] [{SILVER}]{self._esc(m['text'])}[/]")
                    continue
                long = len(m["text"]) > 160
                full = (m["id"] == self._active) or (m["id"] in self._expanded) or not long
                body = self._esc(m["text"]) if full else self._esc(m["text"][:90].rstrip()) + "…"
                acts = ""
                if long and m["id"] != self._active:
                    g = "⤡" if m["id"] in self._expanded else "⤢"
                    acts += f"[@click=app.toggle_node('{m['id']}')][{DIM}]{g}[/][/]  "
                acts += f"[@click=app.sel_node('{m['id']}')][{DIM}]⤷ follow up[/][/]"
                lines.append(f"[b {GREEN}]{self._esc(m.get('agent') or 'claude')} ‹[/] [#C8C8CE]{body}[/]  {acts}")
        if self._pending_user:
            lines.append(f"[{TEAL}]⟳ thinking…[/]")
        # where the next message goes — shows the bound name so you always know the frame
        if self._active and active_root is not None:
            tk, _ = self._thread_meta(self._active)
            where = (self._esc(tk) + " · " if tk else "") + self._esc((self._conv.get(active_root) or {}).get('text', ''))[:22]
            lines.append(f"\n[{DIM}]next →[/] [{GREEN}]⤷ {where}[/]  [{DIM}](✦ new to reset)[/]")
        else:
            lines.append(f"\n[{DIM}]next →[/] [{TEAL}]✦ new thread[/]")
        return "\n".join(lines)

    def _hide_cmd(self) -> None:
        """Drop from chat to keyboard-nav mode (the bar stays visible; single-key binds work again)."""
        try:
            bar = self.query_one("#cmdbar", Input)
            bar.value = ""
            self.query_one("#booktbl", DataTable).focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            try:
                if self.focused is self.query_one("#cmdbar", Input):
                    self._hide_cmd()                       # Esc → keyboard-nav (1-4 tabs, q, etc.)
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

    # ---- background research pipeline (headless agent; the interactive panes stay free) ----
    def _pipeline_argv(self, prompt: str):
        """Headless launch for the pipeline. Configurable so it fits the user's CLI/permission setup:
        CEX_PIPELINE_CMD (default 'claude -p {prompt}'). Research agents are read-only, so a
        permission-bypass flag is usually needed to keep it from blocking — see the cockpit docs."""
        import shlex
        tmpl = os.environ.get("CEX_PIPELINE_CMD", "claude -p {prompt}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            return [prompt if p == "{prompt}" else p for p in parts]
        return parts + [prompt]

    @work(thread=True, group="pipeline", exclusive=True)
    def _run_pipeline_bg(self, theme: str, mode: str = "pipeline") -> None:
        prompt = f"/pipeline {theme}" if mode == "pipeline" else f"scout for {theme}"
        _post("/pipeline/event", {"status": "running", "stage": "scout", "theme": theme,
                                  "message": f"launching headless {mode}…"})
        self.call_from_thread(self._status, Text(
            f"⟳ {mode} running in background: {theme} — your chat stays free (watch PIPELINE)", style=TEAL))
        try:
            out = subprocess.run(self._pipeline_argv(prompt), capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_PIPELINE_TIMEOUT", "900")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            result = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            _post("/pipeline/event", {"status": "error", "message": "CLI not found — set CEX_PIPELINE_CMD"})
            self.call_from_thread(self._status, Text("pipeline: CLI not found — set CEX_PIPELINE_CMD", style=ORANGE)); return
        except subprocess.TimeoutExpired:
            _post("/pipeline/event", {"status": "error", "message": "timed out"})
            self.call_from_thread(self._status, Text("pipeline timed out — raise CEX_PIPELINE_TIMEOUT / check permissions", style=ORANGE)); return
        except Exception as exc:
            _post("/pipeline/event", {"status": "error", "message": str(exc)[:80]})
            self.call_from_thread(self._status, Text(f"pipeline failed: {exc}", style=ORANGE)); return
        tail = (result[-3500:] if result else "(no output — check CEX_PIPELINE_CMD permission flags)")
        _post("/pipeline/event", {"status": "done", "stage": "done", "result": tail, "message": "complete"})
        self.call_from_thread(self._status, Text(f"✓ {mode} complete: {theme}", style=GREEN))

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
        # a plain-text idea (a phrase with no '=') → translate to overrides via a background agent
        if overrides and "=" not in overrides and len(overrides.split()) > 1:
            self._wf_prototype_bg(overrides, ticker)
            return
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

        # granularity: per-leg base→scenario breakdown so the user sees *which* components moved
        blegs = base.get("legs") or {}; slegs = scen.get("legs") or {}
        legkeys = [k for k in list(blegs) + [x for x in slegs if x not in blegs]
                   if _num(blegs.get(k)) is not None or _num(slegs.get(k)) is not None]
        legs_txt = None
        if legkeys:
            legs_txt = Text(f"\n{'valuation legs':<14}{'BASE':>11}{'SCENARIO':>11}{'Δ':>9}\n", style=AMBER)
            for k in legkeys[:8]:
                b_, s_ = _num(blegs.get(k)), _num(slegs.get(k))
                d_ = (s_ - b_) if (b_ is not None and s_ is not None) else None
                legs_txt.append(f"{str(k)[:14]:<14}{_fmt(b_):>11}{_fmt(s_):>11}", style=SILVER)
                legs_txt.append(f"{(f'{d_:+.2f}' if d_ is not None else '—'):>9}\n",
                                style=(GREEN if (d_ or 0) >= 0 else RED))

        bar, legend = _ladder([("F", (base.get("legs") or {}).get("cost"), ORANGE),
                               ("●", price, "white"),
                               ("◆", bi, GOLD),
                               ("✦", si, GREEN)])
        ladder = Group(Text("\nvalue ladder  (F floor · ● price · ◆ base intrinsic · ✦ scenario)", style=DIM),
                       bar, legend)

        groups = [head, applied, cols, dl] + ([legs_txt] if legs_txt else []) + [ladder]
        out.update(Group(*groups))
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
            self.action_open_dossier(target.get("name"))

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
        elif verb in ("profile", "prof"):
            self.action_open_profile(rest[0].upper() if rest else (self._focus or ""))
        elif verb in ("council", "debate") and (rest or self._focus):
            self.action_tab("council_tab")
            if rest:
                self._set_focus(rest[0].upper(), move_cursor=True)
            self._render_council(self._focus)
            self._ask_agent(f"/council {rest[0].upper() if rest else self._focus}")
        elif verb == "note":                              # persist a research note to Living Memory
            self._write_note(" ".join(rest))
        elif verb == "tab" and rest:
            self.action_tab(rest[0])
        elif verb in ("pipeline", "pipe", "scout") and rest:
            self._run_pipeline_bg(" ".join(rest), mode=("scout" if verb == "scout" else "pipeline"))
        elif verb in ("refresh", "r"):
            self.refresh_data()
        else:
            self.action_tab("whatif")
            self._status(Text("commands: /focus TK · /council TK · /note … · /whatif TK ov… · /scenario name · "
                              "/save name · /confirm id · /reject id · /pipeline theme · /tab id · /refresh", style=DIM))


if __name__ == "__main__":
    Cockpit().run()
