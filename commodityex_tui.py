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
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Collapsible, DataTable, Footer, Header, Input,
                             Markdown, Static)

ENGINE = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000")
SESSION = os.environ.get("CEX_SESSION", "commodityex")   # tmux session for one-key agent dispatch
REFRESH_SECONDS = 3.0
SCHED_TICK_SECONDS = 60.0   # how often the recurring-job scheduler checks for due work

# ---- the amber / silver / gold palette (one source of truth) ---------------------------
# Muted on purpose: a low-glare "desk at night" amber, not a blinding hi-vis orange.
AMBER  = "#D6A24A"   # primary accent / focus (soft brass)
AMBER_BRIGHT = "#E6B968"  # the single bright accent (fleet badge value, hot composer)
GOLD   = "#D9C27E"   # headline values (soft gold)
SILVER = "#B6B6BE"   # body text
DIM    = "#74747C"   # secondary / hints
FAINT  = "#5C5C66"   # faintest text (group notes, placeholders)
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


# ---- design-system glyph primitives (the cells CSS can't draw) -------------------------
# The web kit's PillarBar / Badge / ConvictionRating, rendered in Rich markup per
# guidelines/tmux-textual-theme.md. Solid █ fill over a hairline track for the hero card;
# the compact rails keep their lighter ▰ meter (_bar).
def _pillar(label, score, width=22, color=None):
    """A labelled pillar fill-bar — ``T · TAILWIND  ██████████████░░░░░░░░  6.7``. Fill is
    health-coloured (or an explicit colour); the unfilled track is a faint hairline."""
    s = _num(score)
    col = color or health_color(s)
    out = Text(f"{str(label):<14}", style=f"bold {SILVER}")
    out.append(" ")
    if s is None:
        out.append("─" * width, style="#1B1B21")
        out.append("    —", style=DIM)
        return out
    filled = int(round(max(0.0, min(1.0, s / 10.0)) * width))
    out.append("█" * filled, style=col)
    out.append("─" * (width - filled), style="#1B1B21")
    out.append(f" {s:>4.1f}", style=f"bold {col}")
    return out


def _badge(text, level="info"):
    """A chip-style status badge: dim fill + level-coloured label (``GATE CLEAN`` · ``⚠ DILUTION``).
    level ∈ info|good|warn|risk → amber|mint|orange|red (the shared level palette)."""
    return Text(f" {text} ", style=Style.parse(_level_color(level)) + Style(bgcolor="#141418"))


def _rating(r, band=""):
    """The hero conviction read — ``◆ 8.6  PRIME CONVICTION``. Glyph tiered gold/amber/orange
    by rating; band in amber. Degrades to ``◆ —`` when the rating is missing."""
    v = _num(r)
    out = Text()
    if v is None:
        out.append("◆ —", style=DIM)
    else:
        c = GOLD if v >= 8 else (AMBER if v >= 6 else ORANGE)
        out.append(f"◆ {v:.1f}", style=f"bold {c}")
    if band:
        out.append("  ")
        out.append(str(band), style=f"bold {AMBER}")
    return out


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


STALE_DAYS = 14.0          # Living-Memory entries older than this read as "stale · re-confirm?"


def _age_days(ts) -> float:
    """Age of an ISO-8601 ('…Z' UTC) timestamp in days; 0 on parse failure."""
    import datetime as _dt
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "").split("+")[0])
        return max(0.0, (_dt.datetime.utcnow() - t).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _mem_age(ts) -> str:
    """Compact relative age of an ISO memory timestamp — now · 12m · 3h · 2d · 5w (provenance)."""
    secs = _age_days(ts) * 86400.0
    if secs < 90:
        return "now"
    if secs < 5400:
        return f"{int(secs / 60)}m"
    if secs < 129600:
        return f"{int(secs / 3600)}h"
    d = secs / 86400.0
    return f"{int(d)}d" if d < 14 else f"{int(d / 7)}w"


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


def _clip(s, n) -> str:
    """Truncate with an ellipsis (so a cut row reads as 'there's more', and the full text is one
    click away) — never a bare mid-word stub."""
    s = str(s)
    return s if len(s) <= n else s[:n].rstrip() + "…"


# ── Agent Hub — the fleet, Forge-layer aligned (handoff: redesign/design_handoff_agent_hub) ──
# The fleet runs UNIFORMLY on Opus 4.8 — so the per-agent differentiator is no longer "which model"
# but its ROLE and its RUNTIME LANE. The lane chip carries that lane (pane/headless/sweep/rules);
# the model is stated once, in the header Fleet badge.
HUB_RUNTIMES = {
    "pane":     {"label": "pane",     "sub": "interactive pane",    "color": TEAL},
    "headless": {"label": "headless", "sub": "background run",      "color": SILVER},
    "sweep":    {"label": "sweep",    "sub": "scheduled watcher",   "color": GREEN},
    "rules":    {"label": "rules",    "sub": "deterministic local", "color": GOLD},
}

HUB_GROUPS = [
    ("sentinel",    "The Sentinel",        "the book that watches itself"),
    ("council",     "Dialectic Council",   "verdict & swaps"),
    ("research",    "Research Pipeline",   "scout → synthesize → gate"),
    ("audit",       "Calibration & Audit", "keep the book honest"),
    ("independent", "Independent",         "outside the house"),
]

# id → (group, runtime lane, default status, can[] verbs). The Sentinel is a MODULE (sentinel.py),
# not a .claude subagent — it leads the roster. antigravity is the Gemini-backed independent red-team.
HUB_AGENT_META = {
    "sentinel":               ("sentinel",    "sweep",    "watching", ["sweep", "liquidity", "death-spiral", "thesis-integrity"]),
    "arbiter":                ("council",     "pane",     "idle",     ["council", "swap", "explain", "ask"]),
    "bull":                   ("council",     "pane",     "idle",     ["thesis", "ask"]),
    "bear":                   ("council",     "headless", "idle",     ["red-team", "liquidity", "ask"]),
    "scout":                  ("research",    "headless", "idle",     ["scout", "fit", "screen", "compare"]),
    "value-analyst":          ("research",    "headless", "idle",     ["value", "compare", "ask"]),
    "balance-sheet-analyst":  ("research",    "headless", "idle",     ["balance-sheet", "runway", "ask"]),
    "synthesis":              ("research",    "pane",     "idle",     ["synthesize", "compare", "ask"]),
    "verifier":               ("research",    "headless", "idle",     ["verify", "red-team", "gate"]),
    "calibration":            ("audit",       "rules",    "idle",     ["calibrate", "grade", "bias-scan"]),
    "catalyst-verifier":      ("audit",       "headless", "idle",     ["catalyst", "verify", "audit"]),
    "data-integrity-auditor": ("audit",       "rules",    "idle",     ["audit", "grade"]),
    "conviction-analyst":     ("audit",       "pane",     "idle",     ["explain", "ask"]),
    "antigravity":            ("independent", "headless", "idle",     ["red-team", "ask"]),
}
HUB_VERBS = ["ask", "explain", "sweep", "swap", "catalyst", "rule", "claim", "red-team",
             "verify", "compare", "scout", "audit", "council", "calibrate", "bias-scan"]
HUB_LEDGER_VERBS = {"claim", "rule"}   # file to the Thesis Ledger — parsed/validated at save, no scheduler

# Per-agent provider + model. The provider drives WHICH CLI the cockpit shells out to:
#   claude → `claude -p "@agent …"`  (the model is pinned in the agent's .claude/agents/*.md)
#   gemini → the agy CLI            (Gemini — used where Google Finance / Search grounding + speed win)
# Rationale (Claude Max → opus where reasoning matters; faster models where speed does; Gemini for
# data/price aggregation + an independent, cross-model red-team):
#   opus   — deep judgment: the Council (arbiter/bull/bear), value, balance-sheet, synthesis, the
#            forensic gate (verifier), conviction explanations.
#   sonnet — speed-sensitive periodic / rules / structured work: the Sentinel sweep, calibration,
#            the data-integrity audit. (On a Max plan we never drop to haiku — opus or sonnet only.)
#   gemini — scout (proposer / data aggregator), catalyst-verifier (straight-to-source prices/dates
#            via Google Finance), antigravity (independent outside red-team).
HUB_AGENT_MODEL = {
    "sentinel":               ("claude", "sonnet"),
    "arbiter":                ("claude", "opus"),
    "bull":                   ("claude", "opus"),
    "bear":                   ("claude", "opus"),
    "scout":                  ("gemini", "gemini-flash"),
    "value-analyst":          ("claude", "opus"),
    "balance-sheet-analyst":  ("claude", "opus"),
    "synthesis":              ("claude", "opus"),
    "verifier":               ("claude", "opus"),
    "calibration":            ("claude", "sonnet"),
    "catalyst-verifier":      ("gemini", "gemini-flash"),
    "data-integrity-auditor": ("claude", "sonnet"),
    "conviction-analyst":     ("claude", "opus"),
    "antigravity":            ("gemini", "gemini-flash"),
}
_MODEL_COLORS = {"opus": AMBER_BRIGHT, "sonnet": SILVER, "gemini-flash": TEAL}


def _agent_model(agent_id: str):
    """(provider, model) for an agent — the registry, default claude/sonnet."""
    return HUB_AGENT_MODEL.get(agent_id, ("claude", "sonnet"))


def _model_chip(agent_id: str) -> str:
    """A small model badge for the roster/inspector (now the fleet is mixed, the model matters)."""
    _prov, model = _agent_model(agent_id)
    return f"[{_MODEL_COLORS.get(model, SILVER)}]◇{model}[/]"


def _run_model_label(agent: str, provider: str) -> str:
    """The model a run is ACTUALLY on — honest about the agy fallback: a Gemini seat that fell back to
    Claude reads as its Claude model (sonnet), not 'gemini-flash'."""
    if provider == "gemini":
        return "gemini-flash"
    prov, model = _agent_model(agent)
    return model if prov == "claude" else "sonnet"

# Natural-language intent → (agent, verb). First match wins, so order specific → generic. The router
# reads your words to pick the agent, then hands the WHOLE request through (no template flattening).
HUB_INTENT_RULES = [
    (("red-team", "red team", "red team", "invalidate", "bear case", "what breaks", "what would break",
      "downside", "stress test", "stress-test", "tear apart", "poke holes"), "bear", "red-team"),
    (("bull case", "upside case", "strongest case for", "long thesis", "why own", "make the case"), "bull", "thesis"),
    (("balance sheet", "balance-sheet", "runway", "can it fund", "fund itself", "cash burn", "burn rate"), "balance-sheet-analyst", "balance-sheet"),
    (("intrinsic", "fair value", "fair-value", "margin of safety", "ev/oz", "ev per", "cheap or rich", "how cheap", "valuation"), "value-analyst", "value"),
    (("council", "verdict", "debate", "bull and bear", "reconcile", "convene"), "arbiter", "council"),
    (("swap", "rotate into", "rotate out", "replace ", "switch out"), "arbiter", "swap"),
    (("calibrate", "scorecard", "how are my calls", "expectancy", "the journal", "grade my"), "calibration", "calibrate"),
    (("catalyst", "catalysts", "sedar", "edgar", "press release", "drill result", "assay", "straight-to-source"), "catalyst-verifier", "catalyst"),
    (("mis-id", "misid", "ticker/company", "alias", "archetype drift", "audit the book", "data integrity", "data-integrity"), "data-integrity-auditor", "audit"),
    (("verify", "forensic", "red flag", "red-flag", "accounting", "the gate", "gate it"), "verifier", "verify"),
    (("compare", " versus ", " vs ", "peers", "peer set", "stack up", "against other", "other names", "similar names"), "scout", "compare"),
    (("scout", "find names", "screen for", "hunt for", "look for", "discover", "new names", "overlooked", "universe"), "scout", "scout"),
    (("synthesize", "synthesis", "deep dive", "deep-dive", "full analysis", "write up", "write-up", "dossier"), "synthesis", "synthesize"),
    (("why is", "why's", "rated", "rating", "explain", "conviction", "pillar", "t/q/v", "break down the score"), "conviction-analyst", "explain"),
    (("sweep", "liquidity-runway", "liquidity runway", "runway", "death-spiral", "death spiral",
      "thesis-integrity", "thesis integrity", "financing window", "watch the book"), "sentinel", "sweep"),
]

# Per-agent operating notes: a clear one-line WHAT it does (inspector) · a short TAG (roster) · WHEN
# to reach for it · example briefs (clickable — they pre-fill the NL line so you can edit for specifics).
HUB_AGENT_DOC = {
    "sentinel": {"tag": "watches the book for risk · 6h sweep",
                 "what": "Watches the whole book for risk every 6h — liquidity-runway, financing / death-spiral windows, thesis drift, and fired Ulysses rules. Alerts fire on their own; trims & exits it only proposes.",
                 "when": "the book's risk needs watching — liquidity drying up, a financing/death-spiral window, a thesis drifting from the tape, or an armed rule about to fire.",
                 "eg": ["sweep the book now", "check AGA.V liquidity-runway vs the 5d floor", "is URC.TO in a financing/death-spiral window?"]},
    "arbiter":  {"tag": "Council judge — verdict & swaps",
                 "what": "The Dialectic Council's judge — runs Bull vs Bear into ONE reconciled verdict, and arbitrates swaps (challenger vs incumbent) on the friction-adjusted hurdle.",
                 "when": "you want one reconciled verdict, or to arbitrate a swap (one name in, one out).",
                 "eg": ["convene the council on AGA.V", "should I swap URC.TO into MAG?", "reconcile the bull and bear on GROY"]},
    "bull":     {"tag": "Council — the bull case",
                 "what": "The Council's long advocate — builds the strongest asymmetric bull case for a name, grounded in live engine ρ / φ / upside.",
                 "when": "you want the strongest asymmetric long case for a name.",
                 "eg": ["build the bull case for AGA.V", "what's the upside thesis on GMX.TO?"]},
    "bear":     {"tag": "Council — the bear / invalidation",
                 "what": "The Council's bear + liquidity sentinel — the invalidation case: what breaks the thesis, the hard stop, the dilution / liquidity attack at the base leg.",
                 "when": "you want what breaks the thesis — the downside case, the hard stop, a dilution/liquidity stress-test.",
                 "eg": ["red-team URC.TO — what breaks it?", "stress-test AGA.V's dilution & liquidity", "set the hard stop on GROY"]},
    "scout":    {"tag": "finds names that fit your book",
                 "what": "Opportunity finder across the silver / uranium / junior-mining universe — finds new or overlooked names, screens them for PORTFOLIO FIT (your thesis, your holdings, the regime), and builds peer sets to compare against what you hold.",
                 "when": "you want to FIND or COMPARE names that fit your book — new juniors/royalties, or a peer set for something you hold.",
                 "eg": ["scout uranium royalty names that fit my book", "compare URC.TO to other uranium royalties on EV/lb", "find silver developers clearing the forensic gate"]},
    "value-analyst":{"tag": "intrinsic + relative value",
                 "what": "The value desk — builds the intrinsic + relative value case for a shortlist: REP-floor coverage & margin of safety, NAV / EV-per-unit vs peers, the ρ-payoff-vs-φ-downside asymmetry, and a fair-value range with sensitivities.",
                 "when": "you want a name (or a scout shortlist) valued — cheap/fair/rich, and the margin of safety.",
                 "eg": ["value AGA.V vs its REP floor", "is URC.TO cheap vs uranium royalty peers?", "fair-value range for GMX.TO with sensitivities"]},
    "balance-sheet-analyst":{"tag": "runway, debt, dilution",
                 "what": "The balance-sheet desk — assesses survivability: cash & runway in months, debt/obligations, dilution history & the financing/death-spiral window, and JSF accounting integrity. Flags names that can't fund themselves to the catalyst.",
                 "when": "you want to know if a name can fund itself to its thesis — runway, dilution, accounting integrity.",
                 "eg": ["can AGA.V fund itself to the PEA?", "balance-sheet read on URC.TO", "dilution & runway risk across the shortlist"]},
    "synthesis":{"tag": "full deep-dive on a name",
                 "what": "Aggregator / analyst — builds the full structured deep-dive on one name: valuation what-ifs under live scenarios, regime fit, barbell-sleeve fit, the whole memo.",
                 "when": "you want a full structured deep-dive on one name (not just a finding).",
                 "eg": ["deep dive on AGA.V", "full analysis of GMX.TO with a valuation what-if"]},
    "verifier": {"tag": "forensic gate before you act",
                 "what": "The forensic red-team and final gate — JSF / accounting integrity, catalyst credibility, dilution & financing risk, hidden liabilities, regime vulnerability. Can downgrade or reject.",
                 "when": "you want a name pressure-tested before acting on it.",
                 "eg": ["verify AGA.V before I add", "red-flag check on URC.TO's accounting & dilution"]},
    "calibration":{"tag": "grades your closed calls",
                 "what": "Grades your CLOSED decisions on the Druckenmiller objective — slugging, expectancy, upside capture, downside containment (hit-rate demoted) — per archetype, with credible intervals.",
                 "when": "you want to know how your closed calls actually did, not how they felt.",
                 "eg": ["how are my calls doing?", "show the expectancy scorecard for spears", "grade last week's closed decisions"]},
    "catalyst-verifier":{"tag": "catalysts, straight-to-source",
                 "what": "Verifies a name's catalysts straight-to-source (issuer PR / SEDAR+ / EDGAR) — real, correctly attributed, not stale or misidentified. Grounded-or-silent.",
                 "when": "you want a name's catalysts checked at the source — real, attributed, current.",
                 "eg": ["are AGA.V's catalysts real?", "verify URC.TO's next catalyst straight-to-source"]},
    "data-integrity-auditor":{"tag": "audits ticker/company/archetype",
                 "what": "Audits the book for ticker → company → archetype → alias mismatches (the GMX.TO = Globex-not-GoldMining class of bug). Read-only; reports the issue and the fix.",
                 "when": "after a config change, or when a rating / feed reads wrong for a name.",
                 "eg": ["audit the book for mis-IDs", "is GMX.TO mapped to the right company & archetype?"]},
    "conviction-analyst":{"tag": "explains a name's rating",
                 "what": "Explains a holding's Conviction-Mode rating in plain English — which pillar (T/Q/V), band, gate, or driver moved the score, from the live engine state.",
                 "when": "you want a name's rating explained — which pillar/gate/driver drove it.",
                 "eg": ["why is AGA.V rated this?", "break down GMX.TO's conviction score", "what's dragging URC.TO's V pillar?"]},
    "antigravity":{"tag": "independent outside red-team",
                 "what": "An independent, outside red-team / bear case — runs headless via the Gemini-backed agy CLI, so it's a second opinion from outside the house.",
                 "when": "you want a second, INDEPENDENT red-team from outside the house.",
                 "eg": ["independent red-team on AGA.V", "outside bear case for URC.TO"]},
}


def _hub_meta(agent_id):
    return HUB_AGENT_META.get(agent_id, ("audit", "headless", "idle", ["ask"]))


def _lane_chip(lane: str) -> str:
    """The runtime-lane badge (pane/headless/sweep/rules) — a dot + lowercase label. Because the
    whole fleet is Opus 4.8, the chip carries the LANE, not the model (handoff §5)."""
    r = HUB_RUNTIMES.get(lane)
    return f"[{r['color']}]▪{r['label']}[/]" if r else ""


def _status_dot(status: str) -> str:
    """Agent status dot: watching/working = live ●, scheduled = warn ◔, idle = hollow ○."""
    if status in ("watching", "working"):
        return f"[{GREEN}]●[/]"
    if status == "scheduled":
        return f"[{ORANGE}]◔[/]"
    return f"[{DIM}]○[/]"


def _routine_read(a) -> bool:
    """A low-signal, read-only agent MCP call (get_/list_/read_…). Folded into a tally on the desk
    tape so the nervous-system feed shows signal (prompts · replies · pins · operator actions), not
    every poll the agents make."""
    if str(a.get("kind")) != "tool":
        return False
    head = str(a.get("summary", "")).strip().lower().split("(")[0].split(" ")[0]
    return head.startswith(("get_", "list_", "read_", "query_", "fetch_", "search_"))

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
class InspectScreen(ModalScreen):
    """A universal pop-over breakdown — click any metric / tape entry / value ANYWHERE and its live,
    grounded detail pops up over the current view (works from every tab, unlike the old in-panel
    inspector). Esc or a click on the backdrop closes it; action links inside route to App actions."""

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, title: str, body: str, actions: str = "") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._actions = actions or "[#74747C]‹ Esc or click outside to close[/]"

    def compose(self) -> ComposeResult:
        with Vertical(id="inspect_box"):
            yield Static(self._title, id="inspect_title")
            yield VerticalScroll(Static(self._body, id="inspect_body"))
            yield Static(self._actions, id="inspect_actions")

    def action_dismiss(self, result=None) -> None:
        self.dismiss(result)

    def on_click(self, event) -> None:
        # a click on the dimmed backdrop (outside the box) closes the pop-over
        try:
            box = self.query_one("#inspect_box")
            w, _ = self.get_widget_at(event.screen_x, event.screen_y)
            if w is not box and box not in w.ancestors:
                self.dismiss()
        except Exception:
            pass


class ChatInput(Input):
    """The Book conversation input — a plain Input plus ↑/↓ history recall of prior asks
    (Bloomberg's History key). The history lives on the app (``_ask_history``)."""

    BINDINGS = [Binding("up", "hist(-1)", "Prev ask", show=False),
                Binding("down", "hist(1)", "Next ask", show=False)]

    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self._hist_idx: int | None = None

    def action_hist(self, d: int) -> None:
        hist = list(getattr(self.app, "_ask_history", []) or [])
        if not hist:
            return
        if self._hist_idx is None:
            self._hist_idx = len(hist)
        self._hist_idx = max(0, min(len(hist), self._hist_idx + d))
        self.value = hist[self._hist_idx] if self._hist_idx < len(hist) else ""
        self.cursor_position = len(self.value)


class PaletteScreen(ModalScreen):
    """A discoverable command palette (the Bloomberg command line): fuzzy-search names · council ·
    what-if · dossiers · scenarios · tabs · help — ↑/↓ to select, ↵ to run, Esc to close. Plain
    text with no match is sent straight to the desk agents, so you never wonder "what can I type?"."""

    BINDINGS = [Binding("escape", "close", "Close"), Binding("up", "move(-1)", "Up"),
                Binding("down", "move(1)", "Down")]

    def __init__(self, recap: str = "—") -> None:
        super().__init__()
        self._sel = 0
        self._results: list = []
        self._recap = recap or "—"

    def compose(self) -> ComposeResult:
        with Vertical(id="palette_box"):
            yield Input(placeholder="names · council · what-if · dossiers — or ask in plain English",
                        id="palette_input")
            yield Static("", id="palette_results")
            yield Static("", id="palette_foot")

    def on_mount(self) -> None:
        self.query_one("#palette_input", Input).focus()
        self._rebuild("")

    @staticmethod
    def _esc(s) -> str:
        return str(s).replace("[", "(").replace("]", ")")

    def _candidates(self) -> list:
        """(kind, label, hint, run) tuples; run = (verb, arg) dispatched by the app."""
        app = self.app
        focus = app._focus or "—"
        nodes = (app._state or {}).get("nodes", {}) or {}
        items: list = []
        for tk, b in (app._baskets_by_ticker or {}).items():
            role = (nodes.get(tk, {}) or {}).get("role", "") or "name"
            items.append(("focus", str(tk), f"{role} · rating {_fmt(b.get('rating'))}", ("focus", str(tk))))
        items.append(("council", f"Convene council on {focus}", "dialectic → verdict", ("council", focus)))
        items.append(("ask", f"Bear case on {focus}", "stress the thesis", ("bear", focus)))
        items.append(("what-if", f"What-If {focus}", "scenario forge", ("tab", "whatif")))
        for s in (app._scenarios or []):
            nm = s.get("name")
            if nm:
                items.append(("scenario", str(nm), "load saved scenario", ("scenario", str(nm))))
        for i, d in enumerate((app._decisions or [])[:8]):
            items.append(("dossier", f"#{i + 1} {d.get('ticker', '')}",
                          str(d.get("title", ""))[:28], ("dossier", str(d.get("ticker", "")))))
        for tid, label in (("book", "Book"), ("whatif", "What-If"), ("regime_tab", "Regime"),
                           ("profile_tab", "Profile"), ("dossier_tab", "Dossier")):
            items.append(("lens", label, "summon a lens", ("tab", tid)))
        items.append(("hub", "Hub (mission control)", "agents · results · memory · research · audit", ("hub", "")))
        items.append(("help", "Keys & help", "keymap + click grammar", ("help", "")))
        return items

    def _rebuild(self, q: str) -> None:
        q = (q or "").strip().lower()
        cands = self._candidates()
        if q:
            cands = [c for c in cands if q in (c[1] + " " + c[2]).lower()]
        self._results = cands[:8]
        self._sel = max(0, min(self._sel, len(self._results) - 1))
        self._render_results(q)

    def _render_results(self, q: str) -> None:
        lines = []
        if not self._results:
            lines.append(f"[#74747C]↵ send[/] [#B6B6BE]{self._esc(q)}[/] [#74747C]to the desk agents[/]"
                         if q else "[#74747C]type to search names · actions · views…[/]")
        for i, (kind, label, hint, _run) in enumerate(self._results):
            on = (i == self._sel)
            mark = "[#D6A24A]›[/] " if on else "  "
            kc = "#D6A24A" if on else "#74747C"
            lc = "bold white" if on else "#B6B6BE"
            lines.append(f"{mark}[{kc}]{kind:<8}[/] [{lc}]{self._esc(label)}[/]  [#74747C]— {self._esc(hint)}[/]")
        self.query_one("#palette_results", Static).update("\n".join(lines))
        self.query_one("#palette_foot", Static).update(
            f"[#74747C]↩ last:[/] [#B6B6BE]{self._esc(self._recap)}[/]   [#74747C]↑↓ select · ↵ run · esc[/]")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._sel = 0
        self._rebuild(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        run = self._results[self._sel][3] if self._results else None
        self.dismiss((run, event.value.strip()))

    def action_move(self, d: int) -> None:
        if self._results:
            self._sel = (self._sel + d) % len(self._results)
            self._render_results(self.query_one("#palette_input", Input).value)

    def action_close(self) -> None:
        self.dismiss(None)


class HubScreen(ModalScreen):
    """The Agent Hub — full-screen mission control (handoff: redesign/design_handoff_agent_hub).
    Three columns under a chrome band: TEAM (the roster, grouped by function, each agent with its
    runtime-lane chip + status) · WORK (the delegate composer — agent · verb · subject · when — over
    the board: Proposals · Working · Scheduled · Done) · FOCUS (the inspector / reader — a selected
    agent's Watching/Can-do/Recurring/Recent, a running task's live detail, or the master-detail
    reader over Results · Memory · Research · Threads · Tape). The fleet is uniformly Opus 4.8, so the
    differentiator is each agent's ROLE + RUNTIME LANE. Autonomy boundary: alerts fire; trims / exits /
    swaps surface as proposals you approve. ↑↓ / j k read · ←→ or 1-5 category · ↵ open · c copy · Esc."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("up", "move(-1)", "Up"), Binding("down", "move(1)", "Down"),
        Binding("k", "move(-1)", "Up", show=False), Binding("j", "move(1)", "Down", show=False),
        Binding("left", "cat(-1)", "Prev cat"), Binding("right", "cat(1)", "Next cat"),
        Binding("enter", "primary", "Open"), Binding("c", "copy", "Copy"),
        Binding("1", "catset('work')", "Results", show=False),
        Binding("2", "catset('thread')", "Threads", show=False),
        Binding("3", "catset('result')", "Jobs", show=False),
        Binding("4", "catset('research')", "Research", show=False),
        Binding("5", "catset('memory')", "Memory", show=False),
        Binding("6", "catset('tape')", "Tape", show=False),
        Binding("0", "catset('all')", "All", show=False),
    ]
    # the results board: "work" (finished runs/research/jobs — the default) first, then sub-filters
    CATS = [("work", "Results"), ("thread", "Threads"), ("result", "Jobs"), ("research", "Research"),
            ("memory", "Memory"), ("tape", "Tape"), ("all", "All")]

    def __init__(self, tk: str | None = None, cat: str = "work") -> None:
        super().__init__()
        self._cat = cat if cat in dict(self.CATS) else "work"
        self._tk = (tk or None)
        self._sel = 0
        self._items: list = []
        self._timer = None
        # ── composer state (the WORK column's delegate line): agent · verb · subject · when ──
        self._c_agent = "sentinel"
        self._c_verb = "sweep"
        self._c_subject = (tk or "book")
        self._c_when = "now"
        # ── inspector focus (the FOCUS column): an agent, a running task, or the reader ──
        self._insp_agent = "sentinel"   # the Sentinel leads — selected by default
        self._insp_task = None          # a working-task id wins over the agent when set
        self._collapsed_groups: set = set()   # folded roster groups (the collapsible TEAM sidebar)

    def compose(self) -> ComposeResult:
        with Vertical(id="hub_box"):
            # ── header chrome: brand · fleet badge · catalysts · status pips · autonomy dial ──
            with Vertical(id="hub_chrome"):
                yield Static("", id="hub_head")
                yield Static("", id="autonomy")             # the trust dial (lives in the chrome)
            with Horizontal(id="hub_main"):
                # ── TEAM — the roster, grouped by function (each agent: status · name · lane chip) ──
                with VerticalScroll(id="hub_colA"):
                    yield Static("", id="hub_roster")
                # ── WORK — the delegate composer (hero) over the board ──
                with Vertical(id="hub_colB"):
                    yield Static("", id="hub_compose_lab")  # "Delegate a task — describe it, or build it below"
                    yield Input(placeholder='e.g. "compare URC.TO to other uranium royalties on EV/lb" · "red-team AGA.V" · "why is GMX.TO rated this?" · "scenario: uranium spot doubles"', id="hub_input")
                    yield Static("", id="hub_composer")     # agent · verb · subject · when + the Go button
                    yield Static("", id="hub_commands")     # saved-command pills
                    with VerticalScroll(id="hub_board"):    # the board — lanes top → bottom
                        yield Static("", id="hub_workflow")  # ⛓ Workflow — the chain being composed / running
                        yield Static("", id="agents_strip") # ⟳ Working — live now (the prominent top lane)
                        yield Static("", id="proposals")    # ⚑ Proposals — the autonomy boundary
                        yield Static("", id="hub_recurring")# ⏲ Scheduled — recurring
                        yield Static("", id="hub_done")     # ✓ Done today — finished work, click to read
                        yield Static("", id="hub_audit")    # engine audit — fetch · verify · review
                # ── FOCUS — agent flags board + the inspector / reader ──
                with Vertical(id="hub_colC"):
                    yield Static("", id="hub_flags")        # ⚑ agent signals on names (moved off Working)
                    yield Static("", id="review_head")
                    with Horizontal(id="review_main"):
                        with VerticalScroll(id="review_listwrap"):
                            yield Static("", id="review_list")
                        with VerticalScroll(id="review_detailwrap"):
                            yield Static("", id="review_md")
                            yield Static("", id="review_actions")
            yield Static("", id="hub_foot")

    def on_mount(self) -> None:
        self.refresh_cards()
        self.reload()
        self._timer = self.set_interval(1.0, self._tick)    # live elapsed / proposals while open

    def _tick(self) -> None:
        a = self.app
        try:
            a._render_agents(); a._render_autonomy(a._state or {}); a._render_proposals(a._state or {})
            a._render_flags()
            self._paint_head(); self._paint_foot()          # live elapsed, status pips, watching banner
            self.query_one("#hub_done", Static).update(a._hub_done_markup())
            if self._insp_task is not None and self.current() is None:
                self._paint_inspector()                      # keep the live task monitor ticking
        except Exception:
            pass

    # ---- the review board (right) ----
    def current(self):
        return self._items[self._sel] if 0 <= self._sel < len(self._items) else None

    def reload(self) -> None:
        self._items = self.app._review_items(self._cat, self._tk)
        if self._sel >= len(self._items):
            self._sel = max(0, len(self._items) - 1)
        self._paint()

    def select(self, i: int) -> None:
        if 0 <= i < len(self._items):
            self._sel = i
            self._paint()

    def set_cat(self, c: str) -> None:
        if c in dict(self.CATS):
            self._cat = c
            self._sel = 0
            self.reload()

    def open_ref(self, cat: str, ref) -> None:
        """Open a specific item (by its source ref) in the reader — the Done-board → read flow.
        Switches to the item's category, finds it, and selects it so its full content shows."""
        self._insp_task = None
        self._cat = cat if cat in dict(self.CATS) else "all"
        self._items = self.app._review_items(self._cat, None)
        self._sel = next((i for i, it in enumerate(self._items) if str(it.get("ref")) == str(ref)), -1)
        if self._sel < 0 and self._items:
            self._sel = 0
        self._paint()

    def action_move(self, d: int) -> None:
        if self._items:
            self._sel = (self._sel + int(d)) % len(self._items)
            self._paint()

    def action_cat(self, d: int) -> None:
        keys = [c[0] for c in self.CATS]
        self.set_cat(keys[(keys.index(self._cat) + int(d)) % len(keys)])

    def action_catset(self, c: str) -> None:
        self.set_cat(c)

    def action_primary(self) -> None:
        self.app.action_review_do("primary")

    def action_copy(self) -> None:
        self.app.action_review_do("copy")

    def action_close(self) -> None:
        self.dismiss(None)

    # ---- the live cards — built from app state, refreshed on open / poll / action ----
    def refresh_cards(self) -> None:
        a = self.app; st = a._state or {}
        try:
            a._render_agents(); a._render_autonomy(st); a._render_proposals(st); a._render_flags()
        except Exception:
            pass
        for wid, builder in (("#hub_roster", a._card_roster_markup), ("#hub_recurring", a._card_recurring_markup),
                             ("#hub_commands", a._card_commands_markup), ("#hub_audit", a._card_audit_markup),
                             ("#hub_composer", a._hub_composer_markup), ("#hub_done", a._hub_done_markup),
                             ("#hub_compose_lab", a._hub_compose_lab_markup), ("#hub_workflow", a._hub_workflow_markup)):
            try:
                self.query_one(wid, Static).update(builder())
            except Exception:
                pass
        self._paint_head()
        self._paint_foot()
        if self.current() is None:                       # no reader item selected → repaint the inspector
            self._paint_inspector()

    def _paint_head(self) -> None:
        """The header chrome: brand · FLEET (the model mix — claude opus/sonnet + gemini) · catalyst windows ·
        status pips (awaiting · working · scheduled) · shell/esc hint."""
        a = self.app; e = a._esc
        head = Text()
        head.append("◆ ", style=f"bold {AMBER}")
        head.append("AGENT HUB", style="bold white")
        head.append("  mission control", style=FAINT)
        if a._focus:
            head.append("  · focus ", style=DIM); head.append(str(a._focus), style=f"bold {AMBER}")
        head.append("   ▪FLEET ", style=AMBER)
        tiers = [m for m in ("opus", "sonnet") if any(v == ("claude", m) for v in HUB_AGENT_MODEL.values())]
        gem = any(p == "gemini" for p, _ in HUB_AGENT_MODEL.values())
        head.append("·".join(tiers), style=f"bold {AMBER_BRIGHT}")
        if gem:
            head.append(" + ", style=DIM); head.append("gemini", style=f"bold {TEAL}")
        for tk, ev, din, macro in a._hub_calendar_windows(3):     # grounded-or-silent catalyst strip
            head.append("   ⛏ ", style=DIM)
            head.append(f"{tk} ", style=(DIM if macro else f"bold {GOLD}"))
            head.append(f"{e(ev)} ", style=DIM)
            head.append(din, style=AMBER)
        aw, wk, sc = a._hub_status_counts()
        head.append("    ● ", style=AMBER); head.append(f"{aw} ", style=f"bold {GOLD}"); head.append("awaiting", style=DIM)
        head.append("  ● ", style=GREEN);   head.append(f"{wk} ", style=f"bold {GOLD}"); head.append("working", style=DIM)
        head.append("  ◔ ", style=ORANGE);  head.append(f"{sc} ", style=f"bold {GOLD}"); head.append("scheduled", style=DIM)
        head.append("    ⌥O shell · esc", style=DIM)
        try:
            self.query_one("#hub_head", Static).update(head)
        except Exception:
            pass

    def _paint_foot(self) -> None:
        try:
            self.query_one("#hub_foot", Static).update(
                f"[{DIM}]↵ delegate · ⚑ approve · ⏲ schedule · click an agent to inspect · ↑↓ read · c copy · esc[/]"
                f"     [{GREEN}]● sentinel is watching the book[/] [{DIM}]· autonomy:[/] [{AMBER}]{self.app._autonomy}[/]")
        except Exception:
            pass

    def _paint_inspector(self) -> None:
        """The FOCUS column body when no reader item is selected: a running task wins, else the
        selected agent's inspector (Watching / Can-do / Recurring / Recent)."""
        a = self.app
        if self._insp_task is not None and int(self._insp_task) in a._inflight:
            md, acts = a._task_inspector_markup(self._insp_task)
        elif self._insp_agent:
            md, acts = a._agent_inspector_markup(self._insp_agent)
        else:
            md = (f"[bold {GOLD}]Nothing focused[/]\n\n[{DIM}]Click an agent in the roster to inspect it, "
                  f"a working task to watch it, or a reader item to read it.[/]")
            acts = f"[{DIM}]‹ Esc to close[/]"
        try:
            self.query_one("#review_md", Static).update(md)
            self.query_one("#review_actions", Static).update(acts)
        except Exception:
            pass

    def _paint(self) -> None:
        e = self.app._esc
        tabs = [f"[bold {GOLD}]RESULTS[/] [{DIM}]board[/]  "]
        for c, lbl in self.CATS:
            on = (c == self._cat)
            tabs.append(f"[@click=app.review_cat('{c}')][{'bold #D9C27E' if on else '#74747C'}]{lbl}[/][/]")
        head = " ".join(tabs[:1]) + "  ".join(tabs[1:])
        if self._tk:
            head += f"   [#74747C]filter[/] [#D6A24A]{e(self._tk)}[/] [@click=app.review_cat('{self._cat}')][#74747C](×)[/][/]"
        head += f"   [#74747C]· {len(self._items)} items[/]"
        self.query_one("#review_head", Static).update(head)
        lines = []
        for i, it in enumerate(self._items):
            on = (i == self._sel)
            mark = "[#D6A24A]▸[/]" if on else " "
            tcol = "bold #D9C27E" if on else "#B6B6BE"
            tk = f"[#D6A24A]{e(it['ticker'])}[/] " if it.get("ticker") else ""
            glyph = "📌" if it.get("pinned") else it.get("glyph", "·")
            lines.append(f"{mark} [@click=app.review_sel({i})]{glyph} {tk}[{tcol}]{e(_clip(it.get('title',''), 38))}[/][/]")
        empty = (f"[{DIM}]No results yet.\n\nFinished agent runs & research land here — delegate a task "
                 f"above (or run the pipeline) and the result appears on this board, click to read. "
                 f"Tabs narrow it: Threads · Jobs · Research · Memory · Tape.[/]")
        self.query_one("#review_list", Static).update("\n".join(lines) or empty)
        item = self.current()
        if not item:
            self._paint_inspector()                          # the agent/task inspector (the FOCUS default)
        else:
            md, acts = self.app._review_detail(item)
            self.query_one("#review_md", Static).update(md)
            self.query_one("#review_actions", Static).update(acts)
        self._paint_foot()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """The NL line routes itself: Forge prefixes (note/catalyst/claim/rule) and job/command saves
        keep their existing behavior; a bare ticker sets the composer subject; anything else delegates
        through the composer (the typed text becomes the task's natural-language brief)."""
        event.stop()
        app = self.app
        val = (event.value or "").strip(); low = val.lower()
        if not val:
            return
        if low.startswith("scenario:") or low.startswith("what if ") or low.startswith("what-if "):
            idea = val.split(":", 1)[1].strip() if ":" in val.split(" ", 1)[0] else val.split(" ", 1)[1].strip()
            app._hub_scenario(idea)                      # → desk what-if: agent builds knobs + narrative
            return
        if low.startswith("note:"):
            app._write_note(val.split(":", 1)[1].strip())
        elif low.startswith("catalyst:"):
            app._write_catalyst(val.split(":", 1)[1].strip())
        elif low.startswith("claim:"):
            app._amend_thesis_claim(val.split(":", 1)[1].strip())
        elif low.startswith("rule:"):
            app._amend_thesis_rule(val.split(":", 1)[1].strip())
        elif low.startswith("job ") or low.startswith("job:") or ("=" in val):
            app._hub_save_command(val)
        else:
            up = val.upper()
            if (up in (app._baskets_by_ticker or {})) or (("." in val or up == val) and " " not in val and 1 < len(val) <= 8):
                self._c_subject = up                         # a bare ticker just sets the subject
                app._toast(f"subject → {up}", TEAL)
            else:
                # INTENT ROUTER: read the words → pick the agent/verb/ticker, hand over the WHOLE request
                agent, verb, tk = app._route_intent(val)
                if tk:
                    self._c_subject = tk
                if agent:
                    self._c_agent = agent
                    if verb:
                        self._c_verb = verb
                    self._insp_agent, self._insp_task, self._sel = agent, None, -1   # show who took it
                    app._delegate(agent, val, subject=(tk or self._c_subject), verb=verb)
                else:
                    app._ask_agent(val)                      # no keyword → the orchestrator routes it
                    app._toast("routed to the orchestrator — it'll pick the agent", TEAL)
                event.input.value = ""
                self.refresh_cards()
                self._paint()
                return
        event.input.value = ""
        self.refresh_cards()
        self.reload()

    def on_click(self, event) -> None:
        try:
            box = self.query_one("#hub_box")
            w, _ = self.get_widget_at(event.screen_x, event.screen_y)
            if w is not box and box not in w.ancestors:
                self.dismiss()
        except Exception:
            pass


class Cockpit(App):
    TITLE = "CommodityEx"
    SUB_TITLE = "research cockpit"

    # Refined "desk at night" theme — the design system's tmux/Textual projection
    # (guidelines/tmux-textual-theme.md). Same one-source-of-truth palette, tightened to the
    # web kit's hierarchy: round borders stand in for radii, a bright amber border + the 2 Hz
    # pulse for the web glow, percent-alpha fills for rgba tints. No web-only properties.
    CSS = """
    Screen { background: #08080A; color: #CBCBD2; layers: base overlay; }

    /* chrome */
    Header      { background: #0E0E10; color: #D9C27E; text-style: bold; }
    #statusband { height: 1; padding: 0 1; background: #0E0E10; color: #B6B6BE; }
    Footer      { background: #0E0E10; color: #74747C; }

    /* the desk: holdings + book-health rail · reasoning spine (the Hub holds everything agentic) */
    #body    { height: 1fr; }
    #rail    { width: 32; border-right: solid #26262C; padding: 0 1; }
    #surface { width: 1fr; }

    /* rails */
    .railtitle  { color: #D6A24A; text-style: bold; }
    .railsub    { color: #74747C; text-style: bold; margin-top: 1; }
    #watchsearch { border: tall #26262C; background: #0E0E10; height: 3; margin: 1 0; }
    #watchsearch:focus { border: tall #D6A24A; }
    #healthmini { border-top: solid #26262C; margin-top: 1; padding-top: 1; }
    /* these ids now live inside the Hub's left control column */
    #agents_strip { height: auto; border-bottom: solid #26262C; margin-bottom: 1; }
    #autonomy   { height: auto; color: #B6B6BE; }
    #proposals  { height: auto; }

    /* center — always-on regime frame, then a two-column workspace, then the docked omnibox */
    #regime_panel { height: auto; border: round #26262C; margin: 0 1 1 1; padding: 1; }
    #workspace { height: 1fr; }
    #spine  { width: 1fr; padding: 0 1; }
    #cards  { width: 44%; padding: 0 1; border-left: solid #26262C; }
    #conviction { height: auto; }
    #agent_reply { height: auto; margin-top: 1; border-top: solid #1B1B21; padding-top: 1; }

    /* detail cards (Regime · Name · What-If) — always-on panels in the right column */
    Collapsible { border: round #26262C; margin: 0 0 1 0; background: #0D0D10; }
    Collapsible.-expanded { border: round #6FA8A6; }
    CollapsibleTitle { color: #6FA8A6; text-style: bold; }
    #lens_grid { display: none; height: auto; margin: 0 1 1 1; }   /* invisible until `g` */
    #lens_grid DataTable { height: 12; }

    /* the focused-name conviction card: round border + a STATIC amber left-rule (it marks the
       focused name — calm, never pulsing). .compactrow is the kit's non-focused row treatment. */
    .convictioncard   { border: round #26262C; border-left: thick #D6A24A;
                        background: #0D0D10; padding: 1 2; }
    .compactrow       { border: round #26262C; background: #0D0D10; padding: 1 2; margin-top: 1; }
    .compactrow:hover { border: round #33333B; background: #121214; }
    .glow { border: round #6FA8A6; }

    /* data table */
    DataTable { height: 1fr; background: #08080A;
                scrollbar-size-horizontal: 1; scrollbar-size-vertical: 1;
                scrollbar-background: #0B0B0D; scrollbar-color: #26262C; scrollbar-color-hover: #D6A24A; }
    DataTable > .datatable--cursor { background: #1C1C22; }
    DataTable > .datatable--header { color: #D6A24A; text-style: bold; }
    VerticalScroll { scrollbar-size-vertical: 1; scrollbar-background: #0B0B0D;
                     scrollbar-color: #26262C; scrollbar-color-hover: #D6A24A; }
    #booktbl { height: 12; }

    /* inputs / buttons */
    Input  { border: tall #26262C; background: #0E0E10; }
    Input:focus { border: tall #D6A24A; }
    Button { background: #121214; color: #D9C27E; border: tall #26262C; height: 3; }
    Button:hover { border: tall #D6A24A; }
    Button.knob { color: #B6B6BE; min-width: 9; }
    Button.-run { color: #E6B968; border: tall #D6A24A; }       /* primary ▶ Run */
    .row { height: auto; }

    #wf_result  { height: 1fr; border: round #26262C; padding: 1; }
    #wf_history { height: auto; color: #74747C; }
    #wf_status  { height: auto; color: #B6B6BE; }
    #wf_hint    { height: auto; color: #74747C; }
    #regime  { padding: 0 1; }
    #profile_body { height: auto; color: #B6B6BE; }
    #dossier_index { height: auto; color: #B6B6BE; }
    #dossier_open { width: 40; margin: 1 0; }
    #dossier_body { height: auto; }

    /* docked bands — the omnibox docks under the SPINE (so the agent column keeps full height) */
    #ticker { dock: bottom; height: 1; padding: 0 1; background: #0B0B0D;
              color: #B6B6BE; border-top: solid #26262C; }
    #cmdbar { dock: bottom; height: 3; border: tall #26262C; background: #0B0B0D; }
    #cmdbar:focus { border: tall #D6A24A; }

    /* modal inspector */
    InspectScreen { align: center middle; background: #08080A 70%; }
    #inspect_box { width: 72; max-width: 90%; height: auto; max-height: 80%;
                   border: round #D6A24A; background: #0E0E10; padding: 1 2; }
    #inspect_title { height: auto; text-style: bold; color: #D9C27E; }
    #inspect_body  { height: auto; max-height: 22; color: #CBCBD2; padding: 1 0; }
    #inspect_actions { height: auto; color: #74747C; }

    /* command palette (the discoverable Bloomberg command line) */
    PaletteScreen { align: center top; background: #08080A 60%; }
    #palette_box { width: 66; max-width: 90%; margin-top: 6; height: auto;
                   border: round #D6A24A; background: #0E0E10; }
    #palette_input { border: none; border-bottom: solid #26262C; background: #0E0E10; }
    #palette_input:focus { border: none; border-bottom: solid #D6A24A; }
    #palette_results { height: auto; padding: 1 1; }
    #palette_foot { height: 1; padding: 0 1; color: #74747C; border-top: solid #26262C; }

    /* the Agent Hub — full-screen mission control (handoff: redesign/design_handoff_agent_hub).
       Three columns: TEAM (roster) · WORK (delegate composer + board) · FOCUS (inspector / reader),
       under a header chrome band (brand · fleet · catalysts · pips · autonomy) and a footer legend. */
    HubScreen { align: center middle; background: #08080A 80%; }
    #hub_box { width: 98%; height: 96%; border: round #D6A24A; background: #0B0B0D; padding: 0 1; }
    #hub_chrome { height: auto; border-bottom: solid #26262C; }
    #hub_head { height: 1; padding: 0 1; }
    #hub_chrome #autonomy { height: 1; padding: 0 1; color: #B6B6BE; }
    #hub_main { height: 1fr; }
    /* TEAM — the roster column */
    #hub_colA { width: 46; border-right: solid #26262C; padding: 0 1; }
    #hub_roster { height: auto; }
    /* WORK — the delegate composer (hero) then the board */
    #hub_colB { width: 1fr; padding: 0 1; }
    #hub_compose_lab { height: 1; color: #74747C; }
    #hub_input  { border: tall #26262C; background: #0E0E10; height: 3; }
    #hub_input:focus { border: tall #D6A24A; }
    #hub_composer { height: auto; color: #B6B6BE; }
    #hub_commands { height: auto; margin-bottom: 1; border-bottom: solid #26262C; padding-bottom: 1; }
    #hub_board { height: 1fr; }
    #hub_board Static { height: auto; margin-bottom: 1; border-bottom: solid #1B1B21; padding-bottom: 1; }
    /* FOCUS — agent flags board + the results board (reader) + inspector column */
    #hub_colC { width: 82; border-left: solid #26262C; padding: 0 1; }
    #hub_flags { height: auto; padding: 0 1; border-bottom: solid #26262C; }
    #review_head { height: 1; padding: 0 1; border-bottom: solid #26262C; }
    #review_main { height: 1fr; }
    #review_listwrap { width: 44; border-right: solid #26262C; }
    #review_list { height: auto; padding: 1 1; }
    #review_detailwrap { width: 1fr; padding: 0 1; }
    #review_md { height: auto; background: #0B0B0D; }
    #review_actions { height: auto; padding: 1 0; border-top: solid #26262C; }
    #hub_foot { height: 1; padding: 0 1; border-top: solid #26262C; color: #74747C; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        # the five tabs are gone — lenses summon onto the spine; the palette covers the rest
        ("w", "whatif_focus", "What-If"),
        ("e", "go_council", "Council"),
        ("d", "open_profile", "Detail"),
        ("g", "grid", "Book grid"),
        ("h", "open_hub", "Hub"),
        ("v", "open_hub", "Hub"),
        Binding("p", "open_profile", "Profile", show=False),
        # what-if knob stepping (live only while the What-If lens is open; hints live in the lens)
        Binding("left_square_bracket", "wf_knob(-1)", "Prev knob", show=False),
        Binding("right_square_bracket", "wf_knob(1)", "Next knob", show=False),
        Binding("minus", "wf_step(-1, False)", "Knob −", show=False),
        Binding("equals_sign", "wf_step(1, False)", "Knob +", show=False),
        Binding("comma", "wf_step(-1, True)", "Knob − fine", show=False),
        Binding("full_stop", "wf_step(1, True)", "Knob + fine", show=False),
        Binding("backslash", "wf_reset", "Reset knobs", show=False),
        ("c", "confirm", "Confirm"),
        ("a", "ask('analyst')", "Ask analyst"),
        ("b", "ask('bear')", "Bear case"),
        ("x", "ask('dossier')", "Dossier"),
        ("slash", "cmd", "Command"),
        # the command palette — Ctrl-K reaches it from ANYWHERE (even mid-type in the chat, via
        # priority); ':' opens it when focus is on a tab/grid. '?' is the keymap/help overlay.
        Binding("ctrl+k", "palette", "Palette", priority=True),
        Binding("colon", "palette", "Palette", show=False),   # ':' alias (^K already in the footer)
        ("question_mark", "help", "Help"),
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
        self._inspect: tuple | None = None    # (metric_key, ticker) when the detail panel is inspecting a metric
        self._row_index: dict = {}
        self._book_sig = None
        self._focus: str | None = None
        self._last_reported: tuple | None = None
        self._active_scenario: str | None = None
        self._wf_source = "you"
        self._wf_scenario_brief = ""    # agent-proposed scenario narrative (effects beyond the 7 knobs)
        self._wf_scenario_ov = None     # the overrides that narrative belongs to (so it shows only for that run)
        self._wf_hist: list = []
        self._wf_knobs: dict = {k[0]: 0.0 for k in _WF_KNOBS}   # interactive what-if knob deltas
        self._wf_sel = 0                                         # selected knob index
        self._wf_timer = None                                   # debounce for live revalue
        self._wf_pinned: dict | None = None                     # pinned A/B baseline (scenario A)
        self._wf_last: dict | None = None                       # last what-if result (pinnable)
        self._wf_last_res: tuple | None = None                  # (res, overrides) — for A/B re-render
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
        self._council_open = False                 # inline Council debate expanded on the Book page?
        self._ask_history: list = []               # prior chat asks, for ↑/↓ recall in the cmdbar
        self._palette_recap = "—"                  # last command-palette action, echoed as a recap
        self._inflight: dict = {}                  # in-flight agent runs (AGENTS control strip): jid -> job
        self._job_seq = 0                          # in-flight job id sequence
        self._receipts: list = []                  # recent action receipts (what changed + optional undo)
        self._receipt_seq = 0                      # receipt id sequence
        self._done_runs: list = []                 # finished agent runs/research → the Hub's Done board (readable)
        self._done_seq = 0                         # done-run id sequence
        self._workflow: list = []                  # the chain being composed: [{agents:[...], note:str}, …]
        self._workflows = None                     # saved named workflows (lazy-loaded)
        self._wf_running = False                   # a workflow chain is executing
        self._editing_mem: str | None = None       # memory entry id being edited via the chat bar
        self._autonomy = "propose"                  # agent trust dial: manual · propose · auto (≤ posture cap)
        self._watch_query = ""                      # active watchlist search / scout theme
        self._active_view = "book"                  # last-summoned detail card (for /ui/state reporting)
        self._jobs: list | None = None              # recurring scheduler jobs (lazy-loaded)
        self._job_proposals: list = []              # due jobs awaiting a human ✓ (propose mode)

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("connecting to engine…", id="statusband")
        with Horizontal(id="body"):
            # ── LEFT RAIL — holdings + an open, agent-fed watchlist ─────────────────────
            with VerticalScroll(id="rail"):
                yield Static("HOLDINGS", classes="railtitle")
                yield Static("…", id="holdingsbody")               # the book's rated names
                yield Static("WATCHLIST", classes="railtitle railsub")
                yield Input(placeholder="+ search a name or scout a theme…", id="watchsearch")
                yield Static("…", id="watchbody")                  # agent-fed candidates / scout hits
                with Vertical(id="healthmini"):
                    yield Static("BOOK HEALTH", classes="railtitle")
                    yield Static("…", id="healthbody")
            # ── CENTER — the reasoning surface: always-on macro frame, then a two-column workspace
            #     (the reasoning spine on the left; Regime / Name / What-If detail cards on the right) ──
            with Vertical(id="surface"):
                yield Static("…", id="regime_panel")               # always-on regime decomposition
                with Horizontal(id="workspace"):
                    with VerticalScroll(id="spine"):               # LEFT — the name + council + chat
                        yield Static("Select a name to ground the desk.", id="conviction",
                                     classes="convictioncard")
                        # Council renders INLINE here (verdict strip → full debate ⌄) atop the shared
                        # conversation — it is NOT a card. Both live in #agent_reply.
                        yield Static("", id="agent_reply")
                    with VerticalScroll(id="cards"):               # RIGHT — always-on detail cards
                        with Collapsible(title="◑ REGIME DETAIL", collapsed=False, id="lens_regime"):
                            yield Static("…", id="regime")         # curve + integrity + full components
                        with Collapsible(title="▤ NAME DETAIL", collapsed=False, id="lens_dossier"):
                            yield Static("Click a name (or press d) for its deep-dive profile.", id="profile_body")
                            yield Static("DOSSIERS", classes="railsub")
                            yield Static("…", id="dossier_index")
                            yield Input(placeholder="open #  or  ticker", id="dossier_open")
                            yield Markdown("", id="dossier_body")
                        with Collapsible(title="△ WHAT-IF", collapsed=False, id="lens_whatif"):
                            with Horizontal(classes="row"):
                                yield Input(placeholder="ticker — blank uses the focused name", id="wf_ticker")
                                yield Input(placeholder="load a saved scenario by name…", id="wf_scenario")
                            yield Input(placeholder="knobs (silver=+5 ry=-0.5)  ·  or a free-form scenario: \"uranium spot doubles on a supply shock\"  ·  Enter",
                                        id="wf_overrides")
                            yield Static("", id="wf_knobs")
                            with Horizontal(classes="row"):
                                yield Button("− step", id="k_down", classes="knob")
                                yield Button("+ step", id="k_up", classes="knob")
                                yield Button("Reset", id="k_clear", classes="knob")
                                yield Button("▶ Run", id="wf_run", classes="-run")
                                yield Button("Decompose", id="wf_decomp", classes="knob")
                                yield Input(placeholder="save as…", id="wf_name")
                                yield Button("Save", id="wf_save")
                            yield Static("[#74747C]Knobs: [ ] select · − = step · , . fine · \\\\ reset.  "
                                         "Type an idea (e.g. “silver +8, real yield −0.5”) then Enter.[/]", id="wf_result")
                            yield Static("", id="wf_history")
                            yield Static("", id="wf_status")
                            yield Static("", id="wf_hint")
                # the BOOK GRID is invisible until you press `g` (a dense table when you want it)
                with Collapsible(title="▦ BOOK GRID", collapsed=False, id="lens_grid"):
                    yield DataTable(id="booktbl", zebra_stripes=True, cursor_type="row")
                # the omnibox — a ChatInput (↑↓ recall) docked under the spine. Everything agentic
                # (agents working · proposals · memory · results · research) lives in the Hub (press h).
                yield ChatInput(placeholder="Ask anything — type & Enter · ↑↓ recall · ^K palette · h Hub · g grid · ? help",
                                id="cmdbar")
        yield Static("", id="ticker")          # live macro ticker (always on) — see _pulse

    def on_mount(self) -> None:
        t = self.query_one("#booktbl", DataTable)
        for c, w in (("", 3), ("TICKER", 7), ("PRICE", 8), ("ARCH", 8), ("R", 4), ("BAND", 14),
                     ("T", 3), ("Q", 3), ("V", 3), ("UP%", 5), ("FLOOR", 6),
                     ("GATE", 13), ("DIRECTIVE", 22)):
            t.add_column(c, key=c or "role", width=w)
        self.set_interval(REFRESH_SECONDS, self.refresh_data)
        self.set_interval(0.5, self._pulse)     # ~2 Hz heartbeat (no network) — keeps the desk live
        self.set_interval(SCHED_TICK_SECONDS, self._scheduler_tick)   # recurring agent work (dial-gated)
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
        on = (self._beat % 2 == 0)
        # the Hub owns its own 1 Hz tick for live elapsed; nothing to animate on the desk but the ticker.
        body = self._ticker_body
        if body is None:
            return
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
        # The refresh worker can finish as the app tears down; the widget tree is then gone and
        # query_one would raise. Bail if we're not running (also avoids any post-exit render churn).
        if not self.is_running:
            return
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
        self._render_regime_panel(state)
        self._render_holdings(state, baskets)
        self._render_watchlist(state)
        self._render_health(state)
        self._render_book(state, baskets)
        self._maybe_seed_pipeline(state)
        self._render_agent_reply(state)
        self._render_wf_knobs()
        self._render_regime(state)
        if self._focus:                              # the Name card is always on — keep it live
            self._render_profile(self._focus)
        self._render_dossier_index()
        self._refresh_hub()                     # keep the Hub's live cards fresh while it's open
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
        line.append("MRI ", style=DIM)
        line.append(_fmt(mri, "{:.0f}"), style=Style.parse(GOLD) + Style(meta={"@click": "app.explain('mri')"}))
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
            line.append(str(posture["label"]), style=Style.parse(f"bold {pc}") + Style(meta={"@click": "app.explain('posture')"}))
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

    # ------------------------------------------------------------------ always-on regime panel
    def _render_regime_panel(self, state) -> None:
        """The compact, always-visible macro frame above the spine (the heavy decomposition lives in
        the Regime lens). Ends the old status-band / regime-tab / signals triplication."""
        try:
            panel = self.query_one("#regime_panel", Static)
        except Exception:
            return
        ctx = (state or {}).get("conviction_mode", {}).get("context", {}) or {}
        tape = (state or {}).get("macro_tape", {}) or {}
        label = ctx.get("regime") or tape.get("net_tilt", "—")
        mri = (state or {}).get("mri")
        head = Text("REGIME ", style=f"bold {DIM}")
        head.append(str(label),
                    style=f"bold {bias_color('risk_off' if 'OFF' in str(label).upper() else 'risk_on')}")
        head.append("   top driver ", style=DIM)
        head.append(str(tape.get("top_mri_driver", "—")), style=AMBER)
        head.append("    MRI ", style=DIM)
        head.append(_fmt(mri, "{:.0f}"), style=f"bold {GOLD}")
        head.append(" "); head.append_text(_mri_gauge(mri, 12))
        head.append("   ", style=DIM)
        head.append("‹ detail ›", style=Style.parse(TEAL) + Style(meta={"@click": "app.lens('lens_regime')"}))
        dec = (state or {}).get("mri_decomposition", {}) or {}
        comps = sorted(((k, _num(v)) for k, v in dec.items() if k != "top_driver" and _num(v) is not None),
                       key=lambda kv: -abs(kv[1]))[:5]
        bias = Text()
        for i, (k, v) in enumerate(comps):
            if i:
                bias.append("   ", style=DIM)
            bias.append(f"{str(k)[:10]} ", style=DIM)
            bias.append(f"{v:+.2f}", style=(GREEN if v >= 0 else ORANGE))
        panel.update(Group(head, bias) if comps else head)

    # ------------------------------------------------------------------ holdings rail
    def _render_holdings(self, state, baskets) -> None:
        nodes = state.get("nodes", {}) or {}
        annos = state.get("agent_annotations", {}) or {}
        try:
            body = self.query_one("#holdingsbody", Static)
        except Exception:
            return
        if not baskets:
            body.update(Text("waiting for baskets…", style=DIM))
            return
        out = Text()
        for i, b in enumerate(baskets):
            tk = str(b.get("ticker", "?"))
            r = b.get("rating")
            if i:
                out.append("\n")
            mark = "▸" if tk == self._focus else " "
            # clicking a holding FOCUSES it on the spine (the name becomes the subject); the rating
            # click pops its grounded breakdown. Holdings is the primary nav now (grid → a lens).
            click = Style(meta={"@click": f"app.focus_tk('{tk}')"})
            hc = Style.parse(health_color(r))
            out.append(f"{mark}", style=AMBER)
            out.append(f"{_role_glyph(tk, nodes)} ", style=hc + click)
            out.append(f"{tk:<7}", style=Style.parse("bold white") + click)
            out.append(f"{_fmt(r):>4} ", style=hc + Style(meta={"@click": f"app.explain('rating', '{tk}')"}))
            out.append_text(_bar(r, 8))
            out.append("\n     ", style=DIM)
            out.append(f"{str(b.get('band','—'))[:14]:<14} ", style=health_color(r))
            out.append_text(_floor_edge(b))
            sub = b.get("subarchetype")
            if sub:                                           # finer-sort hint (differentiates royalties)
                out.append(f"  {_sub_abbr(sub)}", style=TEAL)
            cat = b.get("catalysts") or []
            if cat:                                           # catalyst-countdown badge (Phase 4)
                sig = _num(b.get("catalyst_signal")) or 0.0
                out.append(f"  ↯{len(cat)}", style=(GREEN if sig >= 0 else ORANGE))
            V = (b.get("pillars", {}) or {}).get("V", {}) or {}
            if _num(V.get("floor_coverage")) is not None and _num(V.get("floor_coverage")) >= 1.0:
                out.append("  ⚑floor", style=GREEN)            # floor-breach: trading under liquidation
            for a in (annos.get(tk) or [])[-1:]:          # agent's visual trace (pin_insight/highlight)
                col = _level_color(a.get("level"))
                out.append("\n     ", style=DIM)
                out.append(f"{a.get('badge', '✦')} ", style=f"bold {col}")
                out.append(str(a.get("reason", ""))[:19], style=col)
        body.update(out)

    # ------------------------------------------------------------------ open watchlist (agent-fed)
    def _render_watchlist(self, state) -> None:
        """The watchlist is a DOOR, not a wall: a search box that scouts, and an agent-fed bench of
        candidate names (scout hits / pipeline finds not yet in the book). Click one to focus it."""
        try:
            body = self.query_one("#watchbody", Static)
        except Exception:
            return
        held = set(self._baskets_by_ticker or {})
        parts: list = []
        if self._watch_query:
            parts.append(Text(f"⟳ scanning: {self._watch_query[:22]}", style=TEAL))
        cands = [c for c in ((state or {}).get("watchlist") or []) if isinstance(c, dict)]
        if not cands:                                         # fall back to pipeline finds outside the book
            pipe = (state or {}).get("pipeline") or {}
            for tk, v in (pipe.get("verdicts") or {}).items():
                if tk in held:
                    continue
                verdict = (v.get("verdict") if isinstance(v, dict) else str(v)) or ""
                note = (v.get("note") if isinstance(v, dict) else "") or f"pipeline · {pipe.get('theme', '')}"
                cands.append({"ticker": tk, "note": note, "source": "pipeline", "status": verdict})
        vcol = {"APPROVE": GREEN, "CONDITIONAL": AMBER, "REJECT": RED}
        for c in cands[:6]:
            tk = str(c.get("ticker", "?"))
            click = Style(meta={"@click": f"app.focus_tk('{tk}')"})
            line = Text("◇ ", style=TEAL)
            line.append(f"{tk:<7}", style=Style.parse(f"bold {SILVER}") + click)
            st = str(c.get("status", "") or "")
            if st:
                line.append(f" {st[:10]}", style=vcol.get(st.upper(), DIM))
            parts.append(line)
            note = str(c.get("note") or c.get("source") or "")[:30]
            if note:
                parts.append(Text(f"   {note}", style=DIM))
        if not cands and not self._watch_query:
            parts.append(Text("type a name or theme above —", style=DIM))
            parts.append(Text("agents scout it onto the bench.", style=DIM))
        body.update(Group(*parts) if parts else Text("…", style=DIM))

    def _render_health(self, state) -> None:
        """The expanded BOOK HEALTH card (freed space, the Hub holds the agentic clutter): the book
        rating + integrity bar, forensics (JSF · runway · Sloan), risk (ES95 · avg corr), the posture
        dial, the data-integrity line, and the live priorities (click a named holding to focus it)."""
        hr = state.get("health_radar", {}) or {}
        fr = state.get("forensics", {}) or {}
        ps = state.get("portfolio_stats", {}) or {}
        integ = state.get("integrity", {}) or {}
        posture = state.get("posture") or {}
        health = hr.get("health_rating")
        out = Text()
        out.append("Rating ", style=DIM)
        out.append(f"{_fmt(health)}/10  ", style=Style.parse(health_color(health)) + Style(meta={"@click": "app.explain('rating')"}))
        out.append_text(_bar(health, 10)); out.append("\n")
        if hr.get("rating_desc"):
            out.append(str(hr.get("rating_desc"))[:30], style=health_color(health)); out.append("\n")
        # forensics — the JSF gate's book aggregate + runway + the Sloan accrual flag
        jsf = _num(fr.get("jsf_score"))
        out.append("JSF ", style=DIM); out.append(f"{_fmt(jsf)}/4", style=health_color((jsf or 0) * 2.5))
        rw = _num(fr.get("runway"))
        if rw is not None:
            out.append("  runway ", style=DIM)
            out.append(f"{rw:.0f}mo", style=(RED if rw < 6 else (AMBER if rw < 12 else SILVER)))
        sloan = _num(fr.get("sloan_cfo"))
        if sloan is not None:
            out.append("  sloan ", style=DIM)
            out.append(f"{sloan:+.2f}", style=(ORANGE if abs(sloan) > 0.10 else SILVER))
        out.append("\n")
        # risk — tail loss + how correlated the book is (concentration tell)
        es = _num(ps.get("expected_shortfall_95")); corr = _num(ps.get("avg_correlation"))
        out.append("ES95 ", style=DIM)
        out.append(f"{_fmt(es)}%", style=(GREEN if (es or 0) < 5 else (AMBER if (es or 0) < 10 else RED)))
        if corr is not None:
            out.append("  avg ρ ", style=DIM)
            out.append(f"{corr:.2f}", style=(ORANGE if corr > 0.6 else SILVER))
        out.append("\n")
        # posture — the master temperature dial (size cap that composes onto every name)
        if posture.get("label"):
            pc = GREEN if posture.get("code") == "spear_exploit" else (ORANGE if posture.get("code") == "defensive" else SILVER)
            out.append("Posture ", style=DIM)
            out.append(str(posture["label"]), style=Style.parse(f"bold {pc}") + Style(meta={"@click": "app.explain('posture')"}))
            if _num(posture.get("cap")) is not None:
                out.append(f" {posture['cap']:g}x", style=(ORANGE if posture.get("headwind") else GREEN))
            out.append("\n")
        # integrity — stale feeds / forensic waivers, or a clean tick
        out.append("Integrity ", style=DIM)
        if integ.get("any_stale") or integ.get("forensic_override_count"):
            bits = []
            if integ.get("any_stale"):
                bits.append(f"{len(integ.get('stale_feeds', []) or []) or 'feed'} stale")
            if integ.get("forensic_override_count"):
                bits.append(f"{integ['forensic_override_count']} waiver")
            out.append("⚠ " + " · ".join(bits), style=ORANGE)
        else:
            out.append("clean ✓", style=GREEN)
        # priorities — the health radar's to-watch list; link any named holding to focus it
        for p in (hr.get("priorities") or [])[:2]:
            title = str(p.get("title", ""))[:30]
            out.append("\n▸ ", style=AMBER)
            hit = next((tk for tk in (self._baskets_by_ticker or {}) if tk and tk in title), None)
            if hit:
                out.append(title, style=Style.parse(SILVER) + Style(meta={"@click": f"app.focus_tk('{hit}')"}))
            else:
                out.append(title, style=SILVER)
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

    # display metric -> (glossary key, label, live-value extractor) for click-to-inspect breakdowns
    _METRICS = {
        "T": ("T", "T · Macro Tailwind", lambda b, V, L: _score((b.get("pillars") or {}).get("T"))),
        "Q": ("Q", "Q · Quality", lambda b, V, L: _score((b.get("pillars") or {}).get("Q"))),
        "V": ("V", "V · Valuation Asymmetry", lambda b, V, L: _score((b.get("pillars") or {}).get("V"))),
        "rating": ("rating", "Conviction rating", lambda b, V, L: _num(b.get("rating"))),
        "rho": ("payoff", "ρ · Payoff ratio", lambda b, V, L: _num(V.get("rho"))),
        "phi": ("floor_coverage", "φ · Floor coverage", lambda b, V, L: _num(V.get("floor_coverage"))),
        "upside": ("upside", "Upside to bull leg", lambda b, V, L: _num(V.get("upside_pct"))),
        "floor": ("floor_coverage", "Floor (margin of safety)", lambda b, V, L: _num(L.get("floor"))),
        "gate": ("gate", "JSF forensic gate", lambda b, V, L: (b.get("gate") or {}).get("cap")),
        "band": ("band", "Conviction band", lambda b, V, L: b.get("band")),
        "directive": ("directive", "Directive", lambda b, V, L: b.get("directive")),
        "mri": ("mri", "MRI · Macro Regime Index", lambda b, V, L: (self._state or {}).get("mri")
                if False else None),  # filled live below
        "posture": (None, "Regime posture", lambda b, V, L: None),
    }

    def action_explain(self, key: str, ticker: str = "") -> None:
        """Click ANY metric, anywhere -> pop a live, grounded breakdown over the current view
        (glossary + value + how it's derived + an 'ask the analyst' deep-dive). The universal
        everything-is-clickable core; works from every tab via the modal."""
        tk = (ticker or self._focus or "").strip()
        if ticker:
            self._set_focus(ticker, move_cursor=True)
        title, body, actions = self._metric_breakdown(key, tk)
        try:
            self.push_screen(InspectScreen(title, body, actions))
        except Exception:
            pass

    def action_ask_metric(self, key: str) -> None:
        """Deep-dive from inside the pop-over: close it, route the metric to the analyst."""
        try:
            self.pop_screen()
        except Exception:
            pass
        spec = self._METRICS.get(key)
        label = spec[1] if spec else key
        tk = self._focus or ""
        self.action_tab("book")
        self._ask_agent(f"Explain {label} for {tk} in depth — what it measures, how the engine "
                        f"computes it here, its live value, and what would change it.")

    def _metric_breakdown(self, key, ticker):
        """Return (title, body, actions) markup for a metric's live, grounded breakdown."""
        b = self._baskets_by_ticker.get(ticker) or {}
        V = (b.get("pillars") or {}).get("V", {}) or {}
        L = b.get("ladder") or {}
        node = ((self._state or {}).get("nodes") or {}).get(ticker, {}) or {}
        price = _num(node.get("price")) or _num(L.get("price"))
        spec = self._METRICS.get(key)
        gloss = ((self._state or {}).get("conviction_mode") or {}).get("glossary") or {}
        glos_key, label = (spec[0], spec[1]) if spec else (key, key)
        val = spec[2](b, V, L) if spec else None
        if key == "mri":
            val = (self._state or {}).get("mri")

        title = f"[bold {GOLD}]{self._esc(label)}[/]  [bold white]{self._esc(ticker or 'book')}[/]"
        lines = []
        if key == "phi" and _num(L.get("floor")) is not None and price:
            lines.append(f"[{DIM}]live[/]  φ = floor ÷ price = {_money(L.get('floor'))} ÷ {_money(price)} "
                         f"= [bold {GREEN if (val or 0) >= 1 else SILVER}]{_fmt(val, '{:.2f}')}[/]")
            lines.append(f"[{DIM}](φ ≥ 1 = trading below the liquidation floor — margin of safety)[/]")
        elif key == "rho":
            lines.append(f"[{DIM}]live[/]  ρ = upside ÷ downside-to-floor = "
                         f"[bold {SILVER}]{_fmt(val, '{:.2f}')}[/]   [{DIM}](the asymmetry payoff ratio)[/]")
        elif key == "upside":
            lines.append(f"[{DIM}]live[/]  [bold {GREEN if (val or 0) >= 0 else RED}]{_fmt(val, '{:+.0f}')}%[/]"
                         f"  [{DIM}]to the bull leg[/] {_money(L.get('bull'))} [{DIM}]from[/] {_money(price)}")
        elif key in ("T", "Q", "V", "rating", "mri"):
            unit = "" if key == "mri" else "/10"
            lines.append(f"[{DIM}]live[/]  [bold {health_color(val if key != 'mri' else None)}]{_fmt(val)}{unit}[/]")
        elif key in ("band", "directive"):
            lines.append(f"[{DIM}]live[/]  [bold {SILVER}]{self._esc(str(val) if val is not None else '—')}[/]")
        elif key == "posture":
            p = (self._state or {}).get("posture") or {}
            lines.append(f"[{DIM}]live[/]  [bold {SILVER}]{self._esc(str(p.get('label', '—')))}[/] "
                         f"{p.get('cap', '')}x   [{DIM}]{self._esc(str(p.get('rationale', '')))}[/]")
        else:
            lines.append(f"[{DIM}]live[/]  [bold {SILVER}]{_fmt(val) if val is not None else '—'}[/]")
        g = gloss.get(glos_key) if glos_key else None
        if g:
            lines.append("")
            for ln in str(g).split("\n")[:8]:
                if ln.strip():
                    lines.append(f"[{SILVER}]{self._esc(ln.strip())}[/]")
        actions = (f"[@click=app.ask_metric('{key}')][{TEAL}]› ask the analyst for the full story[/][/]"
                   f"   [{DIM}]· Esc to close[/]")
        return title, "\n".join(lines), actions

    def action_tape(self, seq: int) -> None:
        """Click a DESK TAPE entry -> pop its full detail + actions (focus the name, dig in). Makes
        the tape interactive, not just a log."""
        acts = (self._state or {}).get("agent_activity", []) or []
        ev = next((a for a in acts if a.get("seq") == int(seq)), None)
        if not ev:
            return
        tk = ev.get("ticker")
        title = f"[bold {GOLD}]{self._esc(str(ev.get('kind', 'event')).upper())}[/]  " \
                f"[{SILVER}]{self._esc(str(ev.get('agent', '')))}[/]"
        body = [f"[white]{self._esc(str(ev.get('summary', '')))}[/]",
                f"\n[{DIM}]{_rel_age(ev.get('ts'))}" + (f" · {self._esc(tk)}" if tk else "") + "[/]"]
        rep = (self._state or {}).get("agent_reply") or {}
        if ev.get("kind") in ("reply", "response") and rep.get("text"):
            body.append(f"\n[{SILVER}]{self._esc(str(rep.get('text'))[:1200])}[/]")
        acts_md = "[#74747C]Esc to close[/]"
        if tk:
            acts_md = (f"[@click=app.focus_tk('{tk}')][{TEAL}]› focus {self._esc(tk)}[/][/]   "
                       f"[@click=app.go_council_tk('{tk}')][{TEAL}]› council[/][/]   [#74747C]· Esc to close[/]")
        try:
            self.push_screen(InspectScreen(title, "\n".join(body), acts_md))
        except Exception:
            pass

    def action_go_council_tk(self, tk: str) -> None:
        try:
            self.pop_screen()
        except Exception:
            pass
        self._set_focus(str(tk), move_cursor=True)
        self.action_go_council()

    def _render_book_detail(self, ticker) -> None:
        b = self._baskets_by_ticker.get(ticker)
        det = self.query_one("#conviction", Static)
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

        # ── header: ticker · hero conviction read (◆ rating + band), then role · archetype ──
        head = Text()
        head.append(f"{ticker}   ", style=f"bold {GOLD}")
        rt = _rating(rating, b.get("band", "—"))                 # ◆ 8.6  PRIME CONVICTION
        rt.stylize(Style(meta={"@click": f"app.explain('rating', '{ticker}')"}))
        head.append_text(rt)
        ctx = Text()
        if node.get("role"):
            ctx.append(f"{node.get('role')}  ·  ", style=DIM)
        ctx.append(_arch_short(b.get('archetype'), b.get('archetype_code')), style=DIM)

        # ── price line: bright last + day change · upside · floor (margin of safety) ──
        pl = Text("price ", style=DIM)
        pl.append(f"{_money(price)}", style="bold white")
        chg = _num(fund.get("changePercentage"))
        if chg is not None:
            pl.append(f"  {'▲' if chg >= 0 else '▼'}{abs(chg):.1f}%", style=(GREEN if chg >= 0 else RED))
        up = _num(V.get("upside_pct"))
        if up is not None:
            pl.append("    upside ", style=DIM)
            pl.append(f"{up:+.0f}%", style=Style.parse(GREEN if up >= 0 else RED) + Style(meta={"@click": "app.explain('upside')"}))
        fl = _num(L.get("floor")); cov = _num(V.get("floor_coverage")); dtf = _num(V.get("downside_to_floor_pct"))
        if fl is not None:
            pl.append("    floor ", style=DIM)
            pl.append(f"{_money(fl)}", style=Style.parse(ORANGE) + Style(meta={"@click": "app.explain('floor')"}))
            if cov is not None:
                pl.append(f" φ{cov:.2f}", style=Style.parse(GREEN if cov >= 1 else DIM) + Style(meta={"@click": "app.explain('phi')"}))
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

        # ── conviction: T/Q/V as the kit's PillarBars (labelled fill bars, each click-to-inspect) ──
        _PLAB = {"T": "T · TAILWIND", "Q": "Q · QUALITY", "V": "V · VALUE"}
        pillars = []
        for k in ("T", "Q", "V"):
            row = _pillar(_PLAB[k], _score(pil.get(k)))
            row.stylize(Style(meta={"@click": f"app.explain('{k}')"}))   # whole bar inspects the pillar
            pillars.append(row)

        # ── asymmetry summary under the bars: ρ · ribbon · the JSF gate as a chip (kit Badge) ──
        summ = Text()
        if _num(V.get("rho")) is not None:
            summ.append("ρ ", style=DIM)
            summ.append(f"{_fmt(V.get('rho'), '{:.2f}')}   ",
                        style=Style.parse(SILVER) + Style(meta={"@click": "app.explain('rho')"}))
        summ.append(f"±{_fmt(rib.get('plus_minus'), '{:.2f}')} ({rib.get('quality', '?')})   ",
                    style=quality_color(rib.get("quality")))
        g = b.get("gate") or {}
        if not g.get("applied"):
            summ.append_text(_badge("GATE CLEAN", "good"))
        else:
            cap = _num(g.get("cap"))
            lvl = "risk" if (cap is not None and cap <= 5.0) else "warn"
            summ.append_text(_badge("⚠ " + str(g.get("reason", "capped")).split(";")[0][:22], lvl))

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

        parts = [head, ctx, pl, fl2]
        if rbar:
            parts.append(rbar)
        parts += [Text(""), *pillars, summ, bar, legend]
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

    def _calendar(self):
        """Lazy catalyst-calendar handle (Forge M1). None if the module is unavailable."""
        c = getattr(self, "_cal", None)
        if c is None:
            try:
                import catalyst_calendar
                self._cal = catalyst_calendar.CatalystCalendar()
                c = self._cal
            except Exception:
                self._cal = False
                return None
        return c or None

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
            entry = mem.write("note", text=text, ticker=tk, regime=self._regime_ctx(), source="user")
            where = f" → {tk}" if tk else " (book-level)"
            self._toast(f"✎ note saved to memory{where} — Council & What-If will see it", TEAL)
            eid = (entry or {}).get("id")
            self._receipt(f"note → {tk or 'book'}", "✎", TEAL,
                          undo=(lambda i=eid: mem.retract(i, source="user")) if eid else None)
            self.query_one("#agent_reply", Static).update(self._conversation_markup())   # live in the thread
        except Exception as e:
            self._toast(f"note not saved: {e}", ORANGE)

    # ------------------------------------------------------------------ Forge M1/M2 NL entry points
    def _write_catalyst(self, spec: str) -> None:
        """`catalyst: <kind> | <title> | <YYYY-MM-DD>[..<YYYY-MM-DD>]` — add a WINDOW to the calendar.
        A catalyst is a window, not a point. kind omitted ⇒ inferred (macro if no focus, else drill).
        Grounded-or-silent: an undated catalyst is refused, not guessed."""
        cal = self._calendar()
        if cal is None:
            self._toast("calendar unavailable — catalyst not saved", ORANGE)
            return
        import catalyst_calendar as cc
        parts = [p.strip() for p in spec.split("|")]
        kind = title = dates = None
        if len(parts) >= 3:
            kind, title, dates = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            if parts[0].lower() in cc.KINDS:
                kind, title = parts[0].lower(), parts[1]
            else:
                title, dates = parts[0], parts[1]
        else:
            title = parts[0]
        kind = (kind or ("macro" if not self._focus else "drill_result")).lower()
        ws = we = None
        if dates:
            ws, we = ([d.strip() for d in dates.split("..", 1)] + [None])[:2] if ".." in dates \
                else (dates.strip(), None)
        if not ws:
            self._toast("need a date — catalyst: <kind> | <title> | YYYY-MM-DD[..YYYY-MM-DD]", ORANGE)
            return
        tk = None if kind == "macro" else (self._focus or None)
        try:
            e = cal.write(kind=kind, title=(title or kind), window_start=ws, window_end=we,
                          ticker=tk, confidence="guided", source="manual", regime=self._regime_ctx())
            where = f" → {tk}" if tk else " (macro)"
            self._toast(f"📅 catalyst saved{where}: {e['window_start'][:10]}…{e['window_end'][:10]}", TEAL)
            self._receipt(f"catalyst → {tk or 'macro'}", "📅", TEAL)
        except Exception as ex:
            self._toast(f"catalyst not saved: {ex}", ORANGE)

    def _amend_thesis(self, *, claim=None, rule=None):
        """Append a claim/rule to the focused name's thesis (creating a CONDITIONAL one if none yet),
        VALIDATE it, and persist via supersede (append-only). Returns the new body or None on error."""
        mem = self._memory()
        if mem is None:
            self._toast("memory unavailable", ORANGE)
            return None
        tk = (self._focus or "").strip()
        if not tk:
            self._toast("focus a name first (claims/rules attach to a name's thesis)", ORANGE)
            return None
        import thesis_ledger as tl
        cur = mem.latest_thesis(tk)
        body = dict((cur or {}).get("meta") or {})
        claims = list(body.get("claims") or [])
        rules = list(body.get("rules") or [])
        if claim:
            claims.append(claim)
        if rule:
            rules.append(rule)
        _std = {"ticker", "stance", "archetype", "claims", "rules", "expected", "linked_calendar",
                "source_urls", "entered_at", "regime_at_entry"}
        new_body = tl.build_thesis(
            tk, stance=body.get("stance", "CONDITIONAL"), archetype=body.get("archetype", ""),
            claims=claims, rules=rules, expected=body.get("expected"),
            linked_calendar=body.get("linked_calendar"), source_urls=body.get("source_urls"),
            regime_at_entry=body.get("regime_at_entry") or self._regime_ctx(),
            intangibles={k: v for k, v in body.items() if k not in _std})
        ok, errors = tl.validate_thesis(new_body)
        if not ok:
            self._toast("rejected: " + "; ".join(errors)[:120], ORANGE)
            return None
        try:
            txt = tl.thesis_summary_line(new_body)
            if cur:
                mem.supersede(cur["id"], "thesis", text=txt, ticker=tk, regime=self._regime_ctx(),
                              meta=new_body, source="user")
            else:
                mem.write("thesis", text=txt, ticker=tk, tags=["thesis", new_body["stance"].lower()],
                          regime=self._regime_ctx(), meta=new_body, source="user")
            try:
                self.query_one("#agent_reply", Static).update(self._conversation_markup())
            except Exception:
                pass
            return new_body
        except Exception as ex:
            self._toast(f"thesis not saved: {ex}", ORANGE)
            return None

    def _amend_thesis_claim(self, spec: str) -> None:
        """`claim: <text> [| <metric> <op> <threshold>]` — a manual claim, or one bound to an engine
        metric (Sentinel re-checks it every sweep)."""
        import thesis_ledger as tl
        if "|" in spec:
            text, expr = [p.strip() for p in spec.split("|", 1)]
            toks = expr.split()
            if len(toks) >= 3:
                thr = toks[2]
                try:
                    thr = float(thr)
                except ValueError:
                    pass
                c = tl.new_claim(text, metric=toks[0], op=toks[1], threshold=thr)
            else:
                c = tl.new_claim(text)
        else:
            c = tl.new_claim(spec.strip())
        body = self._amend_thesis(claim=c)
        if body is not None:
            self._toast(f"✓ claim bound to {self._focus} thesis ({len(body['claims'])} claim(s))", TEAL)

    def _amend_thesis_rule(self, spec: str) -> None:
        """`rule: <trigger> -> <action> [arg]` — arm a pre-commitment. The trigger is parsed through
        the safe grammar; a malformed one is rejected here, never armed."""
        if "->" not in spec:
            self._toast("form: rule: <trigger> -> <action> [arg]   e.g. phi < 1.0 -> trim_to 0.4", ORANGE)
            return
        import thesis_ledger as tl
        trig, act = [p.strip() for p in spec.split("->", 1)]
        toks = act.split()
        action = toks[0] if toks else ""
        arg = None
        if len(toks) > 1:
            try:
                arg = float(toks[1])
            except ValueError:
                arg = toks[1]
        body = self._amend_thesis(rule=tl.new_rule(trig, action, arg=arg))
        if body is not None:
            self._toast(f"🛰 rule armed on {self._focus} ({len(body['rules'])} rule(s))", TEAL)

    def _toast(self, msg, color=None) -> None:
        """Lightweight status line (reuses the what-if status slot; harmless if absent)."""
        try:
            self.query_one("#wf_status", Static).update(Text(str(msg), style=(color or SILVER)))
        except Exception:
            pass

    def _pop_if_modal(self) -> None:
        """Close a detail pop-over if one is open, so acting from inside it dismisses it (a no-op when
        clicked from a rail). Keeps the click-grammar consistent: act in a pop-over → it closes."""
        try:
            if isinstance(self.screen, InspectScreen):
                self.pop_screen()
        except Exception:
            pass

    def action_anno(self, seq) -> None:
        """Open an AGENT NOTE in full — the agent's whole pinned reason + level + the name it's on,
        with focus / council actions (the rail only shows a teaser)."""
        annos = (self._state or {}).get("agent_annotations", {}) or {}
        found, tk = None, None
        for t, lst in annos.items():
            for a in (lst or []):
                if str(a.get("seq")) == str(seq):
                    found, tk = a, t
        if not found:
            return
        lvl = str(found.get("level", "info"))
        col = _level_color(lvl)
        name = "book-level" if tk == "_book" else (tk or "—")
        title = f"[bold {col}]{self._esc(str(found.get('badge', '✦')))} AGENT NOTE[/]  [bold white]{self._esc(name)}[/]"
        body = [f"[#C8C8CE]{self._esc(str(found.get('reason', '')))}[/]", "",
                f"[{DIM}]level[/] [{col}]{self._esc(lvl)}[/]   "
                f"[{DIM}]by[/] [{SILVER}]{self._esc(str(found.get('agent', 'agent')))}[/]   "
                f"[{DIM}]{_rel_age(found.get('ts'))}[/]"]
        acts = "[#74747C]‹ Esc to close[/]"
        if tk and tk != "_book":
            acts = (f"[@click=app.focus_tk('{tk}')][{TEAL}]› focus {self._esc(tk)}[/][/]   "
                    f"[@click=app.go_council_tk('{tk}')][{TEAL}]› council[/][/]   [#74747C]· Esc[/]")
        try:
            self.push_screen(InspectScreen(title, "\n".join(body), acts))
        except Exception:
            pass

    def action_mem_open(self, eid) -> None:
        """Open a saved memory entry IN FULL — the whole note / verdict / thesis, its provenance, and
        the regime it was captured under — and manage it (focus · pin · re-confirm · retract) right
        there. This is the 'access my saved notes' path."""
        mem = self._memory()
        e = mem.get(eid) if mem is not None else None
        if not e:
            self._toast("memory entry not found", ORANGE)
            return
        typ = str(e.get("type", "note"))
        tk = e.get("ticker")
        pinned = e.get("id") in (mem.pinned_ids() if mem is not None else set())
        title = (f"[bold {GOLD}]{self._esc(typ.replace('_', ' ').upper())}[/]  "
                 f"[bold white]{self._esc(tk) if tk else 'book-level'}[/]")
        body = [f"[#C8C8CE]{self._esc(str(e.get('text', '')))}[/]", ""]
        prov = (f"[{DIM}]by[/] [{SILVER}]{self._esc(str(e.get('source', '—')))}[/]   "
                f"[{DIM}]{_mem_age(e.get('ts'))} ago[/]")
        if e.get("confidence"):
            prov += f"   [{DIM}]conf[/] [{SILVER}]{self._esc(str(e['confidence']))}[/]"
        body.append(prov)
        reg = e.get("regime") or {}
        if reg.get("mri") is not None or reg.get("posture") or reg.get("net_tilt"):
            body.append(f"[{DIM}]captured under[/] [{SILVER}]MRI {_fmt(reg.get('mri'), '{:.0f}')} · "
                        f"{self._esc(str(reg.get('posture') or reg.get('net_tilt') or '—'))}[/]")
        if e.get("tags"):
            body.append("  ".join(f"[{DIM}]#{self._esc(str(t))}[/]" for t in (e.get('tags') or [])[:8]))
        stale = (not pinned) and _age_days(e.get("ts")) >= STALE_DAYS
        acts = []
        if tk:
            acts.append(f"[@click=app.focus_tk('{tk}')][{TEAL}]› focus[/][/]")
        acts.append(f"[@click=app.mem_pin('{eid}')][{AMBER if pinned else DIM}]{'unpin' if pinned else '📌 pin'}[/][/]")
        if stale:
            acts.append(f"[@click=app.mem_reaffirm('{eid}')][{ORANGE}]↻ re-confirm[/][/]")
        acts.append(f"[@click=app.mem_del('{eid}')][{DIM}]✕ retract[/][/]")
        acts.append("[#74747C]· Esc[/]")
        try:
            self.push_screen(InspectScreen(title, "\n".join(body), "   ".join(acts)))
        except Exception:
            pass

    # ---- agent oversight (Tier 2): in-flight control strip + action receipts/undo -----------
    def _inflight_add(self, kind: str, label: str, ticker: str = "", agent: str = None, provider: str = None) -> int:
        """Register an in-flight agent run so it's visible (and cancellable) in the AGENTS strip.
        agent/provider record WHO is really doing it and on WHICH model, so the lane/monitor label it
        truthfully (a Gemini-routed scout reads 'scout · gemini-flash', not 'claude')."""
        self._job_seq += 1
        self._inflight[self._job_seq] = {"kind": kind, "label": str(label), "ticker": ticker,
                                         "started": time.time(), "proc": None, "cancelled": False,
                                         "agent": agent, "provider": provider}
        self._render_agents()
        return self._job_seq

    def _inflight_done(self, jid: int) -> None:
        if self._inflight.pop(jid, None) is not None:
            self._render_agents()

    @staticmethod
    def _task_label(j: dict):
        """Turn an in-flight run into a clear (who, what): the agent that's doing it + the task itself.
        Prefers the recorded agent; else parses '@agent <brief>' or a job's kind + topic."""
        label = str(j.get("label", "")).strip()
        if j.get("agent"):                                  # the run recorded who's really doing it
            if label.startswith("@"):
                parts = label[1:].split(None, 1)
                label = parts[1].strip() if len(parts) > 1 else ""
            return j["agent"], label
        kind = str(j.get("kind", "run"))
        if label.startswith("@"):
            parts = label[1:].split(None, 1)
            return parts[0], (parts[1].strip() if len(parts) > 1 else "")
        if kind not in ("ask", "run", "job", ""):
            return kind, label
        return "claude", label

    def action_cancel_job(self, jid) -> None:
        """Stop an in-flight agent run — terminate the child process and drop its (now-ignored)
        reply. In-flight interruptibility is the agent-trust unlock."""
        job = self._inflight.get(int(jid))
        if not job:
            return
        job["cancelled"] = True                       # the worker reads this and drops its reply
        proc = job.get("proc")
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._pending_user = None                     # stop the conversation waiting on the reply
        self._toast(f"✗ cancelled — {str(job.get('label', 'run'))[:24]}", ORANGE)
        self._render_agents()
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass

    def _render_agents(self) -> None:
        """AGENTS WORKING — the concise, no-noise live view (Hub card #agents_strip): in-flight runs
        with elapsed + cancel, the running pipeline, recent agent flags (annotations), and the last
        receipts with undo. Summaries only — the full feed is the board's Tape; full output is Results."""
        try:
            strip = self.screen.query_one("#agents_strip", Static)
        except Exception:
            return                                         # only present while the Hub is open
        parts = []
        pipe = (self._state or {}).get("pipeline") or {}
        pipe_running = pipe.get("status") == "running"
        live = [(jid, j) for jid, j in self._inflight.items() if not j.get("cancelled")]
        head = Text("⟳ ", style=GREEN)
        head.append("WORKING", style="bold #8C8C92")
        head.append(f"  {len(live) + (1 if pipe_running else 0)}", style=f"bold {GOLD}")
        head.append("   live now" if (live or pipe_running) else "   no agents working — delegate above", style=DIM)
        parts.append(head)
        now = time.time()
        monitoring = self.screen._insp_task if isinstance(self.screen, HubScreen) else None
        for jid, j in live:
            el = max(0, int(now - j.get("started", now)))
            click = Style(meta={"@click": f"app.hub_inspect_task('{jid}')"})
            on = (monitoring == jid)
            who, task = self._task_label(j)              # "who's doing it" + "what the task is" (clear)
            # a prominent, clickable card — the whole row opens a live monitor in FOCUS
            prov = j.get("provider") or self._agent_provider(who)
            model = _run_model_label(who, prov)
            line = Text("▸ " if on else "  ", style=(AMBER if on else TEAL))
            line.append("⟳ ", style=TEAL)
            line.append(f"{who} ", style=Style.parse(f"bold {GOLD if on else AMBER}") + click)
            line.append(f"◇{model} ", style=_MODEL_COLORS.get(model, DIM))
            line.append(_clip(task, 44), style=Style.parse(SILVER) + click)
            if j.get("ticker") and j["ticker"].lower() not in task.lower():
                line.append(f"  {j['ticker']}", style=Style.parse(AMBER) + click)
            line.append(f"   {el}s", style=DIM)
            line.append("  ▸ monitor", style=Style.parse(TEAL) + click)
            line.append("   ✗", style=Style.parse(ORANGE) + Style(meta={"@click": f"app.cancel_job('{jid}')"}))
            parts.append(line)
        if pipe_running:
            line = Text("  ⟳ ", style=TEAL)
            line.append("pipeline ", style=f"bold {SILVER}")
            line.append(_clip(pipe.get("theme", ""), 18), style=SILVER)
            if pipe.get("stage"):
                line.append(f" ·{pipe.get('stage')}", style=DIM)
            parts.append(line)
        if not live and not pipe_running:
            parts.append(Text("  no agents working — delegate a task above", style=DIM))
        # (agent FLAGS now live on the right-hand board — see _render_flags / #hub_flags)
        if self._receipts:
            parts.append(Text("RECEIPTS", style="bold #8C8C92"))
            for r in self._receipts[-2:]:
                line = Text("  ", style=DIM)
                line.append(f"{r['glyph']} ", style=r["color"])
                line.append(_clip(r["text"], 28), style=SILVER)
                if r.get("undo"):
                    line.append("  ", style=DIM)
                    line.append("↶", style=Style.parse(GOLD) + Style(meta={"@click": f"app.undo_receipt('{r['id']}')"}))
                parts.append(line)
        strip.update(Group(*parts))

    def _render_flags(self) -> None:
        """⚑ FLAGS — agent signals pinned on names (pins / highlights), shown on the right-hand board
        (not crammed into the live WORKING lane). Click one to open the full note."""
        try:
            box = self.screen.query_one("#hub_flags", Static)
        except Exception:
            return                                         # only present while the Hub is open
        annos = (self._state or {}).get("agent_annotations", {}) or {}
        flagged = []
        for tk in sorted(annos.keys(), key=lambda t: (t != self._focus, t)):
            for a in (annos[tk] or [])[-2:]:
                flagged.append((tk, a))
        head = Text("⚑ ", style=AMBER)
        head.append("FLAGS", style="bold #8C8C92")
        head.append(f"  {len(flagged)}", style=f"bold {GOLD}")
        head.append("   agent signals on names · click to open", style=DIM)
        parts = [head]
        if not flagged:
            parts.append(Text("  none — agents pin signals here as they surface them", style=DIM))
        for tk, a in flagged[:6]:
            col = _level_color(a.get("level"))
            meta = Style(meta={"@click": f"app.anno('{a.get('seq', 0)}')"})
            ln = Text("  ")
            ln.append(f"{a.get('badge', '✦')} ", style=Style.parse(f"bold {col}") + meta)
            ln.append(f"{'BOOK' if tk == '_book' else tk} ", style=Style.parse(f"bold {col}") + meta)
            ln.append(_clip(a.get("reason", ""), 38), style=SILVER)
            parts.append(ln)
        box.update(Group(*parts))

    def _receipt(self, text: str, glyph: str = "✓", color: str = None, undo=None) -> None:
        """Record an action receipt (what changed) + an optional undo closure, shown in the AGENTS
        strip. Receipts add reversibility on top of the Desk Tape's append-only log."""
        self._receipt_seq += 1
        self._receipts.append({"id": self._receipt_seq, "text": str(text), "glyph": glyph,
                               "color": (color or GREEN), "undo": undo, "ts": time.time()})
        del self._receipts[:-3]                        # keep the last few
        self._render_agents()

    def _record_done_run(self, agent, subject, summary, cat="thread", ref=None) -> None:
        """Log a FINISHED agent run / piece of research onto the Hub's Done board — a readable card.
        Clicking it opens the full result in the FOCUS reader (a Book thread, or a saved Result draft)."""
        self._done_seq += 1
        self._done_runs.insert(0, {"id": self._done_seq, "agent": str(agent or "agent"),
                                   "subject": str(subject or ""), "summary": _clip(str(summary or ""), 56),
                                   "cat": cat, "ref": ref, "ts": time.time()})
        del self._done_runs[12:]                        # keep the last dozen
        if isinstance(self.screen, HubScreen):
            try:
                self.screen.query_one("#hub_done", Static).update(self._hub_done_markup())
            except Exception:
                pass

    def action_undo_receipt(self, rid) -> None:
        """Reverse the most recent reversible action (memory note → supersede; saved file → delete)."""
        r = next((x for x in self._receipts if str(x["id"]) == str(rid)), None)
        if not r or not r.get("undo"):
            return
        try:
            r["undo"]()
        except Exception as exc:
            self._toast(f"undo failed: {exc}", ORANGE)
            return
        self._receipts.remove(r)
        self._toast(f"↺ undone — {str(r['text'])[:30]}", DIM)
        self._render_agents()
        try:                                           # reflect any thread / memory change live
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass

    def _undo_file(self, path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass
        self._refresh_decisions()

    # ---- memory management (Tier 2): pin / edit / retract / re-confirm + provenance ----------
    def _after_mem_change(self) -> None:
        """Reflect a memory mutation everywhere it shows (the agent column + the inline research thread)."""
        try:
            self._refresh_hub()
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
        except Exception:
            pass

    def action_mem_pin(self, eid: str) -> None:
        """Pin / unpin a memory entry — pinned floats to the top and is exempt from decay."""
        self._pop_if_modal()                          # if invoked from the detail pop-over, close it
        mem = self._memory()
        if mem is None:
            return
        try:
            if eid in mem.pinned_ids():
                mem.unpin(eid); self._toast("memory unpinned", DIM)
            else:
                mem.pin(eid, source="user"); self._toast("📌 pinned — kept & exempt from decay", AMBER)
        except Exception as exc:
            self._toast(f"pin failed: {exc}", ORANGE); return
        self._after_mem_change()

    def action_mem_del(self, eid: str) -> None:
        """Retract a memory entry — superseded so it leaves the live stream (the record survives)."""
        self._pop_if_modal()
        mem = self._memory()
        if mem is None:
            return
        try:
            e = mem.get(eid) or {}
            mem.retract(eid, source="user")
        except Exception as exc:
            self._toast(f"retract failed: {exc}", ORANGE); return
        self._receipt(f"retracted {str(e.get('text', ''))[:20]}", "✕", ORANGE)
        self._after_mem_change()

    def action_mem_reaffirm(self, eid: str) -> None:
        """Re-confirm a stale entry — supersede with a fresh-dated copy (resets decay)."""
        self._pop_if_modal()
        mem = self._memory()
        if mem is None:
            return
        try:
            mem.reaffirm(eid, regime=self._regime_ctx(), source="user")
        except Exception as exc:
            self._toast(f"re-confirm failed: {exc}", ORANGE); return
        self._toast("↻ re-confirmed — memory freshened", GREEN)
        self._after_mem_change()

    def action_mem_edit(self, eid: str) -> None:
        """Edit an entry — load it into the chat bar; saving supersedes it (an immutable edit)."""
        self._pop_if_modal()
        mem = self._memory()
        e = mem.get(eid) if mem is not None else None
        if not e:
            return
        self._editing_mem = eid
        self.action_tab("book")
        try:
            box = self.query_one("#cmdbar", Input)
            box.value = f"note: {e.get('text', '')}"
            box.cursor_position = len(box.value)
            self.call_after_refresh(box.focus)
        except Exception:
            pass
        self._toast("editing memory — Enter to save (supersedes the original)", TEAL)

    def _edit_note(self, eid: str, text: str) -> None:
        mem = self._memory()
        text = (text or "").strip()
        if mem is None or not text:
            return
        try:
            e = mem.get(eid) or {}
            mem.supersede(eid, e.get("type", "note"), text=text, ticker=e.get("ticker"),
                          regime=self._regime_ctx(), source="user", meta={"edited": True})
        except Exception as exc:
            self._toast(f"edit failed: {exc}", ORANGE); return
        self._receipt(f"edited {text[:20]}", "✎", TEAL)
        self._after_mem_change()

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
        tk_ = self._esc(ticker)
        tline = "  "
        for k in ("T", "Q", "V"):
            s = _score(pil.get(k))
            tline += f"[@click=app.explain('{k}','{tk_}')][{DIM}]{k}[/] [{health_color(s)}]{_fmt(s)}[/][/]   "
        if _num(V.get("rho")) is not None:
            tline += f"[@click=app.explain('rho','{tk_}')][{DIM}]ρ[/] [{SILVER}]{_fmt(V.get('rho'), '{:.2f}')}[/][/]   "
        tline += f"[{quality_color(rib.get('quality'))}]±{_fmt(rib.get('plus_minus'), '{:.2f}')} ({self._esc(rib.get('quality', '?'))})[/]"
        out.append(tline)
        up = _num(V.get("upside_pct")); fl = _num(L.get("floor")); cov = _num(V.get("floor_coverage"))
        dtf = _num(V.get("downside_to_floor_pct")); sup = _num(V.get("support"))
        vd = "  "
        if up is not None:
            vd += f"[@click=app.explain('upside','{tk_}')][{DIM}]upside[/] [{GREEN if up >= 0 else RED}]{up:+.0f}%[/][/]   "
        if fl is not None:
            vd += f"[@click=app.explain('floor','{tk_}')][{DIM}]floor[/] [{ORANGE}]{_money(fl)}[/]"
            vd += f"[{DIM}] φ{cov:.2f}[/]" if cov is not None else ""
            vd += "[/]   "
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

    # ------------------------------------------------------------------ desk tape (→ the Hub board)
    def _tape_items(self, state) -> list:
        """The nervous-system feed as Review items (the Hub's Tape category): operator actions + agent
        work + state, newest-first, routine read-only calls (get_/list_…) folded out as noise."""
        out = []
        now = time.time()
        for a in reversed((state or {}).get("agent_activity", []) or []):
            if _routine_read(a):
                continue
            ag = str(a.get("agent", "")).lower()
            actor = "you" if (a.get("kind") in ("ran", "edited", "git", "prompt")
                              and any(k in ag for k in ("operator", "claude", "cockpit"))) else (a.get("agent") or "agent")
            glyph = {"prompt": "›", "tool": "⚙", "response": "✓", "reply": "✓", "note": "•", "proposal": "↯",
                     "alert": "⚠", "focus": "◎", "scenario": "↯", "ran": "⌘", "edited": "✎", "git": "⎇"}.get(a.get("kind"), "•")
            out.append({"cat": "tape", "glyph": glyph, "title": f"{actor}: {a.get('summary', '')}",
                        "ticker": a.get("ticker"), "age": now - float(a.get("ts", now) or now), "ref": a.get("seq", 0)})
        return out

    def _render_autonomy(self, state) -> None:
        """The agent-trust dial — manual · propose · auto (≤ posture cap). The visible boundary on
        how far agents may act on their own; clicking a segment posts a receipt. Composes with the
        book-level POSTURE cap (auto never exceeds it)."""
        try:
            box = self.screen.query_one("#autonomy", Static)
        except Exception:
            return
        posture = (state or {}).get("posture") or {}
        cap = _num(posture.get("cap"))
        # one compact line for the chrome band: Autonomy  manual · propose · auto≤Xx   <hint>
        line = Text("Autonomy ", style="bold #8C8C92")
        labels = [("manual", "manual"), ("propose", "propose"),
                  ("auto", f"auto{f'≤{cap:g}x' if cap is not None else ''}")]
        for i, (mode, label) in enumerate(labels):
            on = (self._autonomy == mode)
            line.append("  " if i else " ", style=DIM)
            if i:
                line.append("· ", style=BORDER)
            style = Style.parse(f"bold {GOLD}" if on else DIM) + Style(meta={"@click": f"app.autonomy('{mode}')"})
            line.append(("▸" if on else "") + label, style=style)
        hint = {"manual": "you drive every run",
                "propose": "agents propose, you approve",
                "auto": "alerts fire · trims & exits proposed"}.get(self._autonomy, "")
        line.append(f"    {hint}", style=DIM)
        box.update(line)

    def _render_proposals(self, state) -> None:
        """Human-gated AGENT PROPOSALS with inline ✓ approve / ✗ reject / ? why — one-click clearing
        that posts a receipt (reuses _do_confirm / _do_reject). The dial sets the default posture."""
        try:
            box = self.screen.query_one("#proposals", Static)
        except Exception:
            return
        n_prop = len(self._pending or []) + len(self._job_proposals or [])
        ph = Text("⚑ ", style=AMBER)
        ph.append("PROPOSALS", style="bold #8C8C92")
        ph.append(f"  {n_prop}", style=f"bold {GOLD}")
        ph.append("   awaiting your approval — the autonomy boundary", style=DIM)
        parts = [ph]
        for p in (self._pending or [])[:4]:                # engine param-change proposals
            pid = p.get("id")
            pl = Text(f"#{pid} ", style=AMBER)
            pl.append(f"{p.get('key')}=", style=SILVER)
            pl.append(f"{p.get('value')}", style=GOLD)
            pl.append(f"  by {p.get('proposed_by','agent')}", style=DIM)
            parts.append(pl)
            parts.append(Text(f"   {str(p.get('reason',''))[:54]}", style=DIM))
            row = Text("   ")
            row.append(" ✓ approve ",
                       style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.confirm_prop('{pid}')"}))
            row.append(" ")
            row.append(" ✗ reject ",
                       style=Style.parse(f"{RED} on #141418") + Style(meta={"@click": f"app.reject_prop('{pid}')"}))
            row.append(" ")
            row.append(" ? why ",
                       style=Style.parse(f"{TEAL} on #141418") + Style(meta={"@click": f"app.prop_why('{pid}')"}))
            parts.append(row)
        for p in (self._job_proposals or [])[:4]:          # due recurring jobs awaiting a human ✓
            jid = p.get("job_id")
            jl = Text("⏱ ", style=AMBER)
            jl.append(f"{str(p.get('kind','job'))} ", style=TEAL)
            jl.append(str(p.get("label", ""))[:28], style=SILVER)
            parts.append(jl)
            row = Text("   ")
            row.append(" ✓ run ",
                       style=Style.parse(f"{GREEN} on #141418") + Style(meta={"@click": f"app.job_run('{jid}')"}))
            row.append(" ")
            row.append(" ✕ skip ",
                       style=Style.parse(f"{DIM} on #141418") + Style(meta={"@click": f"app.job_skip('{jid}')"}))
            parts.append(row)
        if not self._pending and not self._job_proposals:
            parts.append(Text("   none pending — alerts fire on their own; trims & exits land here", style=DIM))
        box.update(Group(*parts))

    # ---- recurring agent work (the scheduler): dial-gated jobs that improve the terminal ----------
    def _jobs_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cockpit_jobs.json")

    def _drafts_dir(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "agent_drafts")

    def _load_jobs(self) -> list:
        if self._jobs is None:
            try:
                import cockpit_scheduler as sched
                self._jobs = sched.load_jobs(self._jobs_path())
            except Exception:
                self._jobs = []
        return self._jobs

    def _save_jobs(self, jobs=None) -> None:
        try:
            import cockpit_scheduler as sched
            sched.save_jobs(self._jobs_path(), jobs if jobs is not None else (self._jobs or []))
        except Exception:
            pass

    def _scheduler_tick(self) -> None:
        """Fire due recurring jobs, gated by the autonomy dial: manual skips (paused); propose queues
        a one-click ✓-able job-run proposal; auto runs headless + posts a receipt. Cheap (60 s)."""
        try:
            import cockpit_scheduler as sched
        except Exception:
            return
        jobs = self._load_jobs()
        due = sched.due_jobs(jobs)
        if not due:
            return
        mode = sched.decide(self._autonomy)
        if mode == "skip":
            return                                  # manual — paused; jobs stay due until the dial moves
        changed = False
        for job in due:
            if mode == "propose":
                if not any(p.get("job_id") == job["id"] for p in self._job_proposals):
                    self._job_proposals.append({"job_id": job["id"], "label": job.get("label", ""),
                                                "kind": job.get("kind", "job")})
                    self._receipt(f"job due: {job.get('label','')[:22]}", "⏱", AMBER)
                sched.snooze(job, job.get("every_min", 1440))   # one proposal at a time; re-due next cadence
                changed = True
            elif mode == "run":
                self._launch_job(job)
                sched.mark_ran(job)
                changed = True
        if changed:
            self._save_jobs(jobs)
            try:
                self._render_proposals(self._state or {})
            except Exception:
                pass

    def _job_argv(self, prompt: str):
        """Headless launch for a scheduled job. Configurable: CEX_JOB_CMD (else CEX_PIPELINE_CMD,
        else 'claude -p {prompt}'). The CLI's own permission flags govern how much the agent may do —
        the cockpit itself never commits/pushes; jobs emit review artifacts."""
        import shlex
        tmpl = os.environ.get("CEX_JOB_CMD") or os.environ.get("CEX_PIPELINE_CMD", "claude -p {prompt}")
        parts = shlex.split(tmpl)
        if "{prompt}" in parts:
            return [prompt if p == "{prompt}" else p for p in parts]
        return parts + [prompt]

    def _launch_job(self, job: dict) -> None:
        import cockpit_scheduler as sched
        prompt = sched.prompt_for(job)
        agent = job.get("agent")
        if agent and agent != "antigravity":               # a Claude subagent does the task
            prompt = f"@{agent} {prompt}"
        jid = self._inflight_add(agent or job.get("kind", "job"), job.get("label", ""), "")  # visible + cancellable
        self._launch_job_bg(job, prompt, jid)

    @work(thread=True, group="job")
    def _launch_job_bg(self, job: dict, prompt: str, jid: int) -> None:
        agent = job.get("agent")
        _post("/agent/activity", {"agent": agent or "scheduler", "kind": "prompt", "summary": f"⏱ {job.get('label','job')}"})
        self.call_from_thread(self._status, Text(f"⏱ scheduled job: {job.get('label','')}", style=TEAL))
        # build/implement jobs are review-only — the safety line is enforced in BOTH the prompt and the runner
        guard = ("\n\nIMPORTANT: produce a REVIEW ARTIFACT only (markdown). Do NOT edit tracked files, "
                 "commit, or push." if job.get("kind") == "build" else "")
        # an antigravity-assigned task runs through the agy CLI; everything else through CEX_JOB_CMD
        argv = self._agy_argv(prompt) if agent == "antigravity" else self._job_argv(prompt + guard)
        try:
            out = subprocess.run(argv, capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_JOB_TIMEOUT", "900")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            result = (out.stdout or "").strip() or (out.stderr or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text("job: CLI not found — set CEX_JOB_CMD", style=ORANGE)); return
        except subprocess.TimeoutExpired:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text(f"job timed out: {job.get('label','')}", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text(f"job failed: {exc}", style=ORANGE)); return
        self.call_from_thread(self._inflight_done, jid)
        result = result or "(no output — check CEX_JOB_CMD permission flags)"
        path = self._save_job_artifact(job, prompt, result)
        _post("/agent/activity", {"agent": "scheduler", "kind": "note",
            "summary": f"{job.get('label','job')} → {os.path.basename(path) if path else 'done'} ({len(result)}c)"})
        mem = self._memory()                            # a short, recallable outcome (full text = the artifact)
        if mem is not None:
            try:
                mem.write("note", text=f"[scheduled {job.get('kind')}] {job.get('label','')}: {result[:180]}",
                          ticker=None, regime=self._regime_ctx(), source="scheduler")
            except Exception:
                pass
        self.call_from_thread(self._receipt, f"ran {job.get('label','')[:20]}", "⏱", GREEN,
                              (lambda p=path: self._undo_file(p)) if path else None)
        # surface the finished job on the Hub's Done board (readable — opens the saved review draft)
        self.call_from_thread(self._record_done_run, (agent or job.get("kind", "job")),
                              job.get("label", ""), (result[:80] if result else "review draft"), "result", path)
        self.call_from_thread(self._status, Text(f"✓ job done: {job.get('label','')} → review draft", style=GREEN))

    def _save_job_artifact(self, job: dict, prompt: str, result: str):
        """Persist a job's output as a REVIEW DRAFT under data/agent_drafts/ (never applied/committed)."""
        import datetime
        try:
            d = self._drafts_dir()
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(job.get("label", "job")))[:24] or "job"
            path = os.path.join(d, f"{job.get('kind','job')}_{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Scheduled {job.get('kind')} — {job.get('label','')}\n\n"
                        f"_{datetime.datetime.now():%Y-%m-%d %H:%M} · review draft (not applied / not committed)_\n\n"
                        f"**Prompt:** {prompt}\n\n---\n\n{result}\n")
            return path
        except Exception:
            return None

    def action_job_run(self, job_id: str) -> None:
        """Approve a due job proposal → run it now (the propose-mode human ✓)."""
        self._job_proposals = [p for p in self._job_proposals if p.get("job_id") != job_id]
        jobs = self._load_jobs()
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job:
            import cockpit_scheduler as sched
            self._launch_job(job); sched.mark_ran(job); self._save_jobs(jobs)
        self._render_proposals(self._state or {})

    def action_job_skip(self, job_id: str) -> None:
        self._job_proposals = [p for p in self._job_proposals if p.get("job_id") != job_id]
        self._toast("job run skipped (re-proposes next cadence)", DIM)
        self._render_proposals(self._state or {})

    def action_job_run_now(self, job_id: str) -> None:
        jobs = self._load_jobs()
        job = next((j for j in jobs if j.get("id") == job_id), None)
        if job:
            import cockpit_scheduler as sched
            self._launch_job(job); sched.mark_ran(job); self._save_jobs(jobs)
            self._toast(f"running {job.get('label','')}", TEAL)
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def action_job_toggle(self, job_id: str) -> None:
        for j in self._load_jobs():
            if j.get("id") == job_id:
                j["enabled"] = not j.get("enabled")
        self._save_jobs()
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def action_job_del(self, job_id: str) -> None:
        self._jobs = [j for j in self._load_jobs() if j.get("id") != job_id]
        self._job_proposals = [p for p in self._job_proposals if p.get("job_id") != job_id]
        self._save_jobs(self._jobs)
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def _add_job(self, kind: str, topic: str, every_min=None, agent=None):
        import cockpit_scheduler as sched
        jobs = self._load_jobs()
        job = sched.new_job(kind, topic, every_min=every_min, agent=agent)
        jobs.append(job)
        self._jobs = jobs
        self._save_jobs(jobs)
        who = f" · {agent}" if agent else ""
        self._toast(f"scheduled {job['label']}{who} · every {job['every_min']}m (dial: {self._autonomy})", GREEN)
        return job

    def _agent_names(self) -> set:
        return {n for n, _ in self._agent_roster()} | {"antigravity"}

    def _hub_add_job(self, spec: str) -> None:
        """Parse a job spec from the Hub input. Forms (all optional bits):
          job <kind> <topic…> [by <agent>] [@minutes]     — a templated job, optionally assigned
          job <agent> <topic…> [@minutes]                 — assign a specific agent a task
        e.g. `job scout silver juniors @1440`, `job bear AGA.V dilution`, `job audit thresholds by data-integrity-auditor`."""
        import cockpit_scheduler as sched
        spec = (spec or "").strip().lstrip(":").strip()
        if not spec:
            self._toast("format: job <kind|agent> <topic> [by <agent>] [@min]  · kinds: " + " ".join(sched.JOB_KINDS), ORANGE)
            return
        parts = spec.split()
        every = agent = None
        if parts and parts[-1].startswith("@"):
            try:
                every = int(parts[-1][1:]); parts = parts[:-1]
            except ValueError:
                pass
        agents = self._agent_names()
        if len(parts) >= 2 and parts[-2].lower() == "by" and parts[-1].lower() in agents:
            agent = parts[-1].lower(); parts = parts[:-2]
        # first token: a kind (templated) wins; else if it's an agent name, assign it a generic task
        if parts and parts[0].lower() in sched.JOB_KINDS:
            kind = parts[0].lower(); topic = " ".join(parts[1:])
        elif parts and parts[0].lower() in agents:
            agent = agent or parts[0].lower(); kind = "ask"; topic = " ".join(parts[1:])
        else:
            kind = sched.DEFAULT_KIND; topic = " ".join(parts)
        self._add_job(kind, topic, every_min=every, agent=agent)

    def action_hub_assign(self, agent: str) -> None:
        """Pre-fill the Hub input to schedule a task for a specific agent — pick the agent, edit the
        task, Enter to schedule it (the autonomy dial then governs run vs propose)."""
        tk = self._focus or "<topic>"
        try:
            box = self.screen.query_one("#hub_input", Input)   # the input lives in the open Hub
            box.value = f"job ask {tk} by {agent} @1440"
            box.cursor_position = len(box.value)
            self.screen.set_focus(box)
        except Exception:
            pass
        self._toast(f"assign {agent}: edit the task, then Enter to schedule it", TEAL)

    # ---- the Review room: one reader for memory · results · research · threads -----------------
    _MEM_GLYPH = {"note": "✎", "council_verdict": "⚖", "thesis": "◆", "scenario_prior": "⊹",
                  "outcome": "✓", "regime_snapshot": "◷", "decision": "▸", "catalyst": "⛏", "thread": "↯"}

    def action_open_hub(self, tk: str = "", cat: str = "work") -> None:
        """Open the full-screen mission-control Hub (key `h`/`v`, palette, or 'review ›' on memory).
        Defaults the results board to the 'work' view — finished agent runs / research / job output,
        newest-first — so it lands on real results, not an empty filter or the noisy tape."""
        try:
            self.push_screen(HubScreen(tk or None, cat=cat))
        except Exception:
            pass

    # back-compat aliases — every old caller (palette, memory rail, agent-hub) lands on the one Hub
    def action_open_review(self, tk: str = "") -> None:
        self.action_open_hub(tk)

    def action_agent_hub(self) -> None:
        self.action_open_hub()

    def _refresh_hub(self) -> None:
        """Keep the Hub's live control cards fresh while it's open (called on the 3 s poll + on actions).
        The board itself only re-pulls on user navigation, so a poll never disrupts your reading."""
        if isinstance(self.screen, HubScreen):
            try:
                self.screen.refresh_cards()
            except Exception:
                pass

    def _clip_copy(self, text: str) -> None:
        """Put text on the OS clipboard (pbcopy / clip / xclip / xsel). The dashboard owns the mouse,
        so this is the reliable way to lift agent output & memory off the screen (the ⧉ copy action)."""
        text = str(text or "")
        for argv in (["pbcopy"], ["clip"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                p = subprocess.Popen(argv, stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"), timeout=3)
                self._toast(f"⧉ copied {len(text)} chars to the clipboard", GREEN)
                return
            except Exception:
                continue
        self._toast("clipboard tool not found (pbcopy/xclip)", ORANGE)

    @staticmethod
    def _file_title(path: str) -> str:
        import re
        base = os.path.basename(path)
        base = base[:-3] if base.endswith(".md") else base
        base = re.sub(r"_\d{8}-\d{6}$", "", base)              # drop the trailing timestamp
        return (base.replace("_", " ").strip() or base)[:52]

    @staticmethod
    def _file_ticker(path: str):
        head = os.path.basename(path).split("_")[0]
        return head if (("." in head or head.isupper()) and 1 < len(head) <= 8) else None

    def _review_items(self, cat: str = "all", tk: str | None = None) -> list:
        """Aggregate the four sources into one newest-first list (each: cat·glyph·title·ticker·age·ref)."""
        import glob as _glob
        items: list = []
        now = time.time()
        if cat in ("all", "memory"):
            mem = self._memory()
            if mem is not None:
                try:
                    pinned = mem.pinned_ids()
                    for e in mem.query(limit=80):
                        if e.get("type") == "pin" or (e.get("meta") or {}).get("retracted"):
                            continue
                        items.append({"cat": "memory", "glyph": self._MEM_GLYPH.get(e.get("type"), "·"),
                                      "title": str(e.get("text", "")), "ticker": e.get("ticker"),
                                      "age": _age_days(e.get("ts")) * 86400.0, "ref": e.get("id"),
                                      "pinned": e.get("id") in pinned})
                except Exception:
                    pass
        repo = os.path.dirname(os.path.abspath(__file__))
        # "work" is the Results board: finished agent work only — job drafts + research + threads
        # (no tape/command history, no raw memory notes). Each sub-tab narrows it.
        if cat in ("all", "result", "work"):
            for p in _glob.glob(os.path.join(self._drafts_dir(), "*.md")):
                items.append({"cat": "result", "glyph": "⏱", "title": self._file_title(p),
                              "ticker": self._file_ticker(p), "age": now - os.path.getmtime(p), "ref": p})
        if cat in ("all", "research", "work"):
            for p in _glob.glob(os.path.join(repo, "research", "*.md")):
                items.append({"cat": "research", "glyph": "🔬", "title": self._file_title(p),
                              "ticker": self._file_ticker(p), "age": now - os.path.getmtime(p), "ref": p})
            for p in _glob.glob(os.path.join(repo, "data", "decisions", "*.md")):
                items.append({"cat": "research", "glyph": "▤", "title": self._file_title(p),
                              "ticker": self._file_ticker(p), "age": now - os.path.getmtime(p), "ref": p})
        if cat in ("all", "thread", "work"):
            for r in self._roots():
                nodes = [n for n in self._conv.values() if self._branch_root(n["id"]) == r["id"]]
                if cat == "work" and not any(n.get("role") == "agent" for n in nodes):
                    continue            # the Results board shows FINISHED delegations (a reply landed)
                tip = max(nodes, key=lambda n: n["ts"], default=r)
                items.append({"cat": "thread", "glyph": "↯",
                              "title": (f"{r.get('ticker')} · " if r.get('ticker') else "") + str(r.get("text", "")),
                              "ticker": r.get("ticker"), "age": now - float(tip.get("ts", now)), "ref": r["id"]})
        if cat in ("all", "tape"):
            items += self._tape_items(self._state or {})
        if tk:
            items = [i for i in items if (i.get("ticker") or "").upper() == tk.upper()]
        items.sort(key=lambda i: i.get("age", 1e12))           # newest first
        return items

    def _review_detail(self, item: dict):
        """(content-markup, actions-markup) for the selected Review item — the FULL content rendered
        as Rich markup for the detail Static (consistent with the rest of the desk), + verify/act."""
        e_ = self._esc
        cat, ref = item.get("cat"), item.get("ref")
        if cat == "memory":
            mem = self._memory()
            ent = mem.get(ref) if mem is not None else None
            if not ent:
                return ("[#74747C]entry not found[/]", "[#74747C]‹ Esc[/]")
            typ = str(ent.get("type", "note")); etk = ent.get("ticker"); reg = ent.get("regime") or {}
            pinned = ent.get("id") in (mem.pinned_ids() if mem is not None else set())
            stale = (not pinned) and _age_days(ent.get("ts")) >= STALE_DAYS
            md = [f"[bold {GOLD}]{self._MEM_GLYPH.get(typ, '·')} {e_(typ.replace('_', ' ').upper())}[/]"
                  f"  [bold white]{e_(etk) if etk else 'book-level'}[/]", "",
                  f"[#C8C8CE]{e_(str(ent.get('text', '')))}[/]", "",
                  f"[{BORDER}]{'─' * 40}[/]",
                  f"[{DIM}]by[/] [{SILVER}]{e_(str(ent.get('source', '—')))}[/]   "
                  f"[{DIM}]{_mem_age(ent.get('ts'))} ago[/]" + ("   [bold #CF9A5C]stale[/]" if stale else "")]
            if reg.get("mri") is not None or reg.get("posture") or reg.get("net_tilt"):
                md.append(f"[{DIM}]captured under[/] [{SILVER}]MRI {_fmt(reg.get('mri'), '{:.0f}')} · "
                          f"{e_(str(reg.get('posture') or reg.get('net_tilt') or '—'))}[/]")
            if ent.get("tags"):
                md.append("  ".join(f"[{DIM}]#{e_(str(t))}[/]" for t in (ent.get("tags") or [])[:8]))
            acts = []
            if etk:
                acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(etk)}[/][/]")
            acts.append(f"[@click=app.review_do('pin')][{AMBER if pinned else DIM}]{'unpin' if pinned else '📌 pin'}[/][/]")
            if stale:
                acts.append(f"[@click=app.review_do('reaffirm')][{ORANGE}]↻ re-confirm[/][/]")
            acts.append(f"[@click=app.review_do('edit')][{DIM}]✎ edit[/][/]")
            acts.append(f"[@click=app.review_do('retract')][{DIM}]✕ retract[/][/]")
            acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]")
            return ("\n".join(md), "   ".join(acts))
        if cat in ("result", "research"):
            try:
                with open(ref, encoding="utf-8") as fh:
                    body = fh.read()
            except Exception:
                body = "could not read this file"
            head = f"[bold {GOLD}]{e_(self._file_title(ref))}[/]   [{DIM}]{e_(os.path.basename(ref))}[/]\n\n"
            acts = []
            if item.get("ticker"):
                acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(item['ticker'])}[/][/]")
            acts.append(f"[@click=app.review_do('ask')][{TEAL}]› send to chat to act on[/][/]")
            acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]")
            acts.append(f"[@click=app.review_do('discard')][{DIM}]✕ discard[/][/]")
            acts.append("[#74747C]· Esc[/]")
            return (head + f"[#C8C8CE]{e_(body)}[/]", "   ".join(acts))
        if cat == "thread":
            nodes = sorted((n for n in self._conv.values() if self._branch_root(n["id"]) == ref),
                           key=lambda n: n["ts"])
            root = self._conv.get(ref) or {}
            md = [f"[bold {GOLD}]↯ THREAD[/]  [bold white]{e_(root.get('ticker') or '—')}[/]", ""]
            for n in nodes:
                if n.get("role") == "you":
                    md.append(f"[b {TEAL}]you ›[/] [{SILVER}]{e_(str(n.get('text', '')))}[/]\n")
                else:
                    md.append(f"[b {GREEN}]{e_(str(n.get('agent', 'claude')))} ‹[/] [#C8C8CE]{e_(str(n.get('text', '')))}[/]\n")
            acts = (f"[@click=app.review_do('jump')][{TEAL}]› open in chat[/][/]   "
                    f"[@click=app.review_do('save')][{GOLD}]⇪ save as dossier[/][/]   "
                    f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]   [#74747C]· Esc[/]")
            return ("\n".join(md), acts)
        if cat == "tape":
            acts_list = (self._state or {}).get("agent_activity", []) or []
            ev = next((a for a in acts_list if str(a.get("seq")) == str(ref)), None) or {}
            rep = (self._state or {}).get("agent_reply") or {}
            md = [f"[bold {GOLD}]{e_(str(ev.get('kind', 'event')).upper())}[/]  "
                  f"[{SILVER}]{e_(str(ev.get('agent', '')))}[/]" + (f"  [{AMBER}]{e_(ev.get('ticker'))}[/]" if ev.get('ticker') else ""),
                  "", f"[#C8C8CE]{e_(str(ev.get('summary', '')))}[/]", "", f"[{DIM}]{_rel_age(ev.get('ts'))}[/]"]
            if ev.get("kind") in ("reply", "response") and rep.get("text"):
                md += ["", f"[#C8C8CE]{e_(str(rep.get('text'))[:2000])}[/]"]
            acts = []
            if ev.get("ticker"):
                acts.append(f"[@click=app.review_do('focus')][{TEAL}]› focus {e_(ev['ticker'])}[/][/]")
            acts.append(f"[@click=app.review_do('copy')][{TEAL}]⧉ copy[/][/]   [#74747C]· Esc[/]")
            return ("\n".join(md), "   ".join(acts))
        return ("[#74747C]nothing selected[/]", "[#74747C]‹ Esc[/]")

    def _review_copy_text(self, item: dict) -> str:
        """Plain text to put on the clipboard for a Review item (the desk owns the mouse in Textual,
        so ⧉ copy is the reliable way to lift agent output / memory off the screen)."""
        cat, ref = item.get("cat"), item.get("ref")
        try:
            if cat == "memory":
                ent = (self._memory().get(ref) if self._memory() else None) or {}
                return str(ent.get("text", ""))
            if cat in ("result", "research"):
                with open(ref, encoding="utf-8") as fh:
                    return fh.read()
            if cat == "thread":
                nodes = sorted((n for n in self._conv.values() if self._branch_root(n["id"]) == ref),
                               key=lambda n: n["ts"])
                return "\n\n".join(("You: " if n.get("role") == "you" else
                                    f"{n.get('agent', 'claude')}: ") + str(n.get("text", "")) for n in nodes)
            if cat == "tape":
                ev = next((a for a in ((self._state or {}).get("agent_activity") or [])
                           if str(a.get("seq")) == str(ref)), {})
                rep = (self._state or {}).get("agent_reply") or {}
                txt = str(ev.get("summary", ""))
                if ev.get("kind") in ("reply", "response") and rep.get("text"):
                    txt += "\n\n" + str(rep.get("text"))
                return txt
        except Exception:
            pass
        return str(item.get("title", ""))

    def action_review_sel(self, idx) -> None:
        if isinstance(self.screen, HubScreen):
            self.screen.select(int(idx))

    def action_review_cat(self, cat) -> None:
        if isinstance(self.screen, HubScreen):
            self.screen._tk = None                              # clicking a category also clears the filter
            self.screen.set_cat(str(cat))

    def action_review_do(self, op: str = "primary") -> None:
        """Dispatch a verify/act on the selected Review item; reload the room (or close it for nav)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        item = scr.current()
        if not item:
            return
        cat, ref, tk = item.get("cat"), item.get("ref"), item.get("ticker")
        if op == "primary":
            op = "jump" if cat == "thread" else ("focus" if tk else "open")
        if op == "copy":
            self._clip_copy(self._review_copy_text(item)); return
        if op == "focus" and tk:
            scr.dismiss(None); self._set_focus(tk, move_cursor=True); self.action_tab("book"); return
        if cat == "memory":
            if op == "pin":
                self.action_mem_pin(ref)
            elif op == "reaffirm":
                self.action_mem_reaffirm(ref)
            elif op == "retract":
                self.action_mem_del(ref)
            elif op == "edit":
                scr.dismiss(None); self.action_mem_edit(ref); return
            scr.reload()
        elif cat in ("result", "research"):
            if op == "discard":
                try:
                    os.remove(ref)
                except OSError:
                    pass
                self._toast("discarded", DIM); scr.reload()
            elif op == "ask":
                scr.dismiss(None)
                try:
                    with open(ref, encoding="utf-8") as fh:
                        content = fh.read()[:4000]
                except Exception:
                    content = ""
                self._ask_agent(f"Review this agent {cat} and tell me whether it's worth acting on, and "
                                f"the single best next step:\n\n{content}")
        elif cat == "thread":
            if op == "jump":
                scr.dismiss(None); self.action_sel_branch(ref)
            elif op == "save":
                self.action_sel_branch(ref); self.action_save_thread(); scr.reload()

    # ---- autonomy dial + one-click proposal clearing (the agent-trust model) ----------------
    def action_autonomy(self, mode: str) -> None:
        if mode not in ("manual", "propose", "auto"):
            return
        self._autonomy = mode
        self._receipt(f"autonomy → {mode}", "⚙", AMBER)
        self._render_autonomy(self._state or {})
        self._toast(f"autonomy set to {mode}", AMBER)

    def action_confirm_prop(self, pid) -> None:
        try:
            self._do_confirm(int(pid))
        except (TypeError, ValueError):
            pass

    def action_reject_prop(self, pid) -> None:
        try:
            self._do_reject(int(pid))
        except (TypeError, ValueError):
            pass

    def action_prop_why(self, pid) -> None:
        p = next((x for x in (self._pending or []) if str(x.get("id")) == str(pid)), None)
        if p:
            self._ask_agent(f"explain agent proposal #{pid}: {p.get('key')}={p.get('value')} "
                            f"(by {p.get('proposed_by', 'agent')}) — is it justified in this regime?")

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
        self._refresh_hub()                       # surface fresh agent activity in the Hub if it's open

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
        view = self._current_view()
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

    def on_collapsible_toggled(self, event: Collapsible.Toggled) -> None:
        """Summoning a lens (incl. via its title toggle) renders its body immediately and reports the
        new view to the agents — the Collapsible replacement for tab activation."""
        c = getattr(event, "collapsible", None)
        if c is not None and not c.collapsed:
            self._on_lens_opened(c.id)
        if self._focus:
            self._report_ui(self._focus)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id
        val = event.value.strip()
        if wid == "cmdbar":
            low = val.lower()
            editing = self._editing_mem              # consumed by this submit (always cleared)
            self._editing_mem = None
            if val and (not self._ask_history or self._ask_history[-1] != val):
                self._ask_history.append(val)         # remember for ↑/↓ recall (dedupe consecutive)
                del self._ask_history[:-50]
            if isinstance(event.input, ChatInput):
                event.input._hist_idx = None          # reset the recall cursor on send
            if val.startswith("/") or val.startswith(":"):
                self._run_command(val)
            elif low.startswith("note:") or low.startswith("note "):
                note_text = val.split(":", 1)[-1].strip() if ":" in val else val[5:].strip()
                if editing:                           # an in-place edit supersedes the original
                    self._edit_note(editing, note_text)
                else:
                    self._write_note(note_text)
            elif low.startswith("catalyst:"):         # Forge M1 — add a catalyst WINDOW to the calendar
                self._write_catalyst(val.split(":", 1)[1].strip())
            elif low.startswith("claim:"):            # Forge M2 — bind a load-bearing claim to the thesis
                self._amend_thesis_claim(val.split(":", 1)[1].strip())
            elif low.startswith("rule:"):             # Forge M2 — arm a pre-commitment (Ulysses) rule
                self._amend_thesis_rule(val.split(":", 1)[1].strip())
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
        elif wid == "watchsearch":
            self._watch_search(val)
            event.input.value = ""

    def _watch_search(self, q: str) -> None:
        """The watchlist search box is a door: a known holding focuses it; anything else scouts the
        theme/name onto the bench (headless) and shows a scanning row."""
        q = (q or "").strip()
        if not q:
            return
        up = q.upper()
        if up in (self._baskets_by_ticker or {}):     # a holding → just focus it on the spine
            self._set_focus(up, move_cursor=True)
            return
        self._watch_query = q
        self._render_watchlist(self._state or {})
        self._run_pipeline_bg(q, mode="scout")        # headless scout; results stream to PIPELINE + bench
        self._status(Text(f"⟳ scouting “{q[:32]}” onto the watchlist (headless)", style=TEAL))

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
    # old tab ids → always-on detail cards. council is inline; grid is hotkey-toggled; book = the spine.
    _LENS_FOR = {"book": None, "whatif": "lens_whatif", "regime_tab": "lens_regime",
                 "dossier_tab": "lens_dossier", "profile_tab": "lens_dossier"}
    _VIEW_FOR = {"whatif": "whatif", "regime_tab": "regime", "dossier_tab": "dossier",
                 "profile_tab": "dossier", "grid": "book", "book": "book"}

    def action_tab(self, tab_id: str) -> None:
        """Compat shim: the detail cards (Regime · Name · What-If) are always on the right column now,
        so 'switch a tab' means 'scroll that card into view'. Every old caller keeps working. The Book
        Grid is hotkey-toggled (`g`); council stays inline."""
        tid = str(tab_id)
        if tid in ("council_tab", "council"):
            self.action_go_council()                      # council stays inline — not a card
            return
        if tid in ("grid", "lens_grid"):
            self.action_grid(show=True)
            return
        lens_id = self._LENS_FOR.get(tid)
        if lens_id:
            self.open_lens(lens_id)
        self._active_view = self._VIEW_FOR.get(tid, "book")

    def open_lens(self, lens_id: str, *, solo: bool = False) -> None:
        """Scroll a detail card into view (the cards are always expanded) and render it fresh."""
        for c in self.query(Collapsible):
            if c.id == lens_id:
                c.collapsed = False
                try:
                    c.scroll_visible(animate=False)
                except Exception:
                    pass
        self._on_lens_opened(lens_id)

    def action_lens(self, lens_id: str) -> None:
        """Toggle a detail card collapsed/expanded (muscle-memory key + click bindings)."""
        try:
            c = self.query_one(f"#{lens_id}", Collapsible)
        except Exception:
            return
        c.collapsed = not c.collapsed
        if not c.collapsed:
            self._on_lens_opened(lens_id)
            try:
                c.scroll_visible(animate=False)
            except Exception:
                pass

    def action_grid(self, show=None) -> None:
        """Toggle the Book Grid — invisible until summoned with `g` (a dense table when you want it)."""
        try:
            grid = self.query_one("#lens_grid", Collapsible)
        except Exception:
            return
        grid.display = (not grid.display) if show is None else bool(show)
        if grid.display:
            grid.collapsed = False
            try:
                grid.scroll_visible(animate=False)
            except Exception:
                pass

    def _on_lens_opened(self, lens_id: str) -> None:
        """Render a card body the moment it's summoned (don't wait for the 3 s poll)."""
        if lens_id == "lens_dossier" and self._focus:
            self._render_profile(self._focus)
            self._render_dossier_index()
        elif lens_id == "lens_regime":
            self._render_regime(self._state or {})

    def _lens_open(self, lens_id: str) -> bool:
        try:
            return not self.query_one(f"#{lens_id}", Collapsible).collapsed
        except Exception:
            return False

    def _current_view(self) -> str:
        """The view the operator last summoned (for /ui/state reporting). The detail cards are always
        on, so this is an explicit pointer rather than derived from collapse state."""
        return getattr(self, "_active_view", "book")

    @staticmethod
    def _tab_for(view) -> str:
        return {"book": "book", "whatif": "whatif", "what-if": "whatif", "live what-if": "whatif",
                "council": "book", "council_tab": "book",   # council is merged into the Book page
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
            return not self.query_one("#lens_whatif", Collapsible).collapsed
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
        """Free-form SCENARIO: an agent turns a plain-language scenario into (a) runnable knob overrides
        AND (b) a narrative of the second-order effects BEYOND the 7 knobs (dilution/financing-window,
        catalyst timing, liquidity/ADV, regime shift, peer re-rating, thesis-integrity). The knobs run
        live; the narrative shows alongside the numbers — so the what-if isn't boxed into hard knobs."""
        tkname = ticker or self._focus or "the focused name"
        self.call_from_thread(lambda: self.query_one("#wf_result", Static).update(
            Text(f"⟳ an agent is building the scenario for {tkname}…  “{idea[:42]}”", style=TEAL)))
        prompt = (
            f"You are a resource-sector analyst building a what-if SCENARIO for {tkname} in the CommodityEx engine.\n"
            "Only these knobs are numerically runnable: silver (+/- $), gold (+/- $), ry (+/- pp real yield), "
            "dxy (+/- index pts), peer (+/-% EV/oz multiple), vol (+/-% silver vol), mri (+/- regime score).\n"
            "Return EXACTLY two lines, no fences, no extra prose:\n"
            "KNOBS: <space-separated key=value deltas using ONLY those knobs, e.g. silver=+8 ry=-0.5 peer=+20%>\n"
            f"BRIEF: <2-4 sentences on the SECOND-ORDER effects this scenario has on {tkname} that the knobs "
            "can't capture — dilution / financing-window risk, catalyst timing, liquidity / ADV, regime shift, "
            "peer re-rating, thesis-integrity.>\n"
            f"Scenario: {idea}")
        try:
            out = subprocess.run(self._ask_argv(prompt), capture_output=True, text=True,
                                 timeout=int(os.environ.get("CEX_ASK_TIMEOUT", "180")),
                                 cwd=os.path.dirname(os.path.abspath(__file__)))
            raw = (out.stdout or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._status, Text("scenario: CLI not found — set CEX_ASK_CMD", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._status, Text(f"scenario failed: {exc}", style=ORANGE)); return
        # parse KNOBS: / BRIEF: (tolerant — fall back to any line of knob tokens)
        knobs_line, brief, in_brief = "", "", False
        for line in raw.splitlines():
            s = line.strip()
            if s.upper().startswith("KNOBS:"):
                knobs_line = s.split(":", 1)[1]; in_brief = False
            elif s.upper().startswith("BRIEF:"):
                brief = s.split(":", 1)[1].strip(); in_brief = True
            elif in_brief and s:
                brief += " " + s
        if not knobs_line:
            for line in raw.splitlines():
                toks = line.replace(",", " ").split()
                if any("=" in t and t.split("=", 1)[0].strip().lower() in _ALIAS_TO_KNOB for t in toks):
                    knobs_line = line; break
        ov = " ".join(tok for tok in knobs_line.replace(",", " ").split()
                      if "=" in tok and tok.split("=", 1)[0].strip().lower() in _ALIAS_TO_KNOB)
        if not ov and not brief:
            self.call_from_thread(self._status, Text("couldn't build the scenario — try explicit overrides", style=ORANGE)); return

        def apply():
            self._wf_scenario_brief = brief
            self._wf_scenario_ov = ov
            self._wf_source = "agent"
            if ov:
                self._knobs_from_overrides(ov); self._render_wf_knobs()
                self.query_one("#wf_overrides", Input).value = ov
                self.query_one("#wf_result", Static).update(Text(f"scenario → {ov}  · running…", style=GREEN))
                self._run_whatif(ticker, ov)
            else:                       # purely qualitative scenario — show the narrative on its own
                t = Text(f"{tkname}  ", style=f"bold {GOLD}")
                t.append("agent scenario · no runnable knob move\n\n", style=DIM)
                t.append(brief, style=SILVER)
                self.query_one("#wf_result", Static).update(t)
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

    # ---- command palette + help (discoverability: the Bloomberg command line + HELP) -------
    def action_palette(self) -> None:
        """Open the discoverable command palette (Ctrl-K from anywhere, or ':')."""
        try:
            self.push_screen(PaletteScreen(self._palette_recap), self._palette_done)
        except Exception:
            pass

    def _palette_done(self, result) -> None:
        if not result:
            return
        run, q = result
        if run is None:                                  # no match → send the typed text to the agents
            if q:
                self._ask_agent(q)
                self._palette_recap = f"ask · {q[:22]}"
            return
        verb, arg = run
        if verb == "focus":
            self._set_focus(arg, move_cursor=True); self.action_tab("book"); self._palette_recap = f"focus {arg}"
        elif verb == "tab":
            self.action_tab(arg); self._palette_recap = f"open {arg}"
        elif verb == "council":
            self.action_go_council(); self._palette_recap = f"council {self._focus or ''}".strip()
        elif verb == "bear":
            self._ask_agent(f"bear case on {arg}"); self._palette_recap = f"bear · {arg}"
        elif verb == "scenario":
            self.action_tab("whatif"); self._load_scenario(arg); self._palette_recap = f"scenario {arg}"
        elif verb == "dossier":
            self.action_tab("dossier_tab")
            if arg:
                self._set_focus(arg, move_cursor=True); self._dossier_pick(arg)
            self._palette_recap = f"dossier {arg}"
        elif verb in ("review", "hub"):
            self.action_open_hub(); self._palette_recap = "hub"
        elif verb == "help":
            self.action_help()

    def action_help(self) -> None:
        """The keymap + click-grammar cheat-sheet (Bloomberg HELP), as a pop-over."""
        def keylabel(k):
            return {"left_square_bracket": "[", "right_square_bracket": "]", "equals_sign": "=",
                    "full_stop": ".", "question_mark": "?", "colon": ":", "slash": "/",
                    "backslash": "\\", "minus": "−", "comma": ",", "ctrl+k": "^K"}.get(k, k)
        rows = []
        for b in self.BINDINGS:
            k = b.key if isinstance(b, Binding) else b[0]
            desc = (b.description if isinstance(b, Binding) else b[2]) or ""
            if desc:
                rows.append((keylabel(k), desc))
        half = (len(rows) + 1) // 2
        # '[' is the only markup-opener (neutralize it); the trailing space before [/] keeps a
        # literal '\' from abutting a bracket and breaking the parse.
        def cell(kv):
            key = str(kv[0]).replace("[", r"\[")
            return f"[{GOLD}]{key:>3} [/] [{SILVER}]{kv[1]:<13}[/]"
        body = [f"[bold {AMBER}]KEYS[/]"]
        for i in range(half):
            left = rows[i]
            right = rows[i + half] if i + half < len(rows) else None
            body.append(f"  {cell(left)}   {cell(right) if right else ''}")
        body.append("")
        body.append(f"[bold {AMBER}]CLICK GRAMMAR[/]  [{DIM}](the desk is clickable)[/]")
        for glyph, what in (("a name", "focus it on the Book page"),
                            ("a metric φ/ρ/T/Q/V", "pop its grounded breakdown"),
                            ("‹full debate ⌄›", "expand the inline Council"),
                            ("a desk-tape / memory row", "open its detail"),
                            ("v  ·  Review room", "read & verify memory · results · research · threads"),
                            ("‹✦ new›", "start a fresh research thread")):
            body.append(f"  [{TEAL}]›[/] [{SILVER}]{glyph:<22}[/] [{DIM}]{what}[/]")
        body.append("")
        body.append(f"[{DIM}]Plain text is a question to the agents — no command needed. "
                    f"Ctrl-K opens the command palette; v opens the Review room.[/]")
        try:
            self.push_screen(InspectScreen("KEYS & CLICK GRAMMAR", "\n".join(body),
                                           "[#74747C]‹ Esc or click outside to close[/]"))
        except Exception:
            pass

    # ---- agent hub (mission control: set up agent work — a lens over existing data) ----------
    _AGENT_PROMPT = {
        "conviction-analyst": "@conviction-analyst why is {tk} rated this? Ground in the live engine state.",
        "catalyst-verifier": "@catalyst-verifier are {tk}'s catalysts real and correctly attributed (straight-to-source)?",
        "data-integrity-auditor": "@data-integrity-auditor sweep the book for ticker / company / archetype / alias mis-IDs.",
        "bull": "@bull build the strongest asymmetric bull case for {tk}, grounded in engine ρ / φ / upside.",
        "bear": "@bear build the strongest invalidation case for {tk}; set the hard stop, attack φ/ρ at the base leg.",
        "arbiter": "@arbiter reconcile the bull and bear on {tk} into one verdict.",
        "scout": "scout for overlooked names adjacent to {tk}.",
        "synthesis": "deep dive on {tk} — full structured analysis, valuation what-ifs, regime fit.",
        "verifier": "verify / red-team {tk} — accounting integrity (JSF), catalysts, dilution, regime vulnerability.",
        "calibration": "how are my calls doing? show the expectancy scorecard (Druckenmiller objective).",
    }
    _AGENT_BOOK_LEVEL = {"data-integrity-auditor", "calibration"}
    _HUB_DEFAULT_COMMANDS = {
        "bear": "Red-team {ticker}: valuation, dilution / financing risk, jurisdiction, and the signals that invalidate the bull.",
        "catalysts": "Verify {ticker}'s catalysts straight-to-source (issuer PR / SEDAR+ / EDGAR) — flag stale or misattributed.",
        "floor": "What is {ticker}'s REP floor, and how much margin of safety does the current price give?",
        "peers": "Compare {ticker} to its closest book peer on ρ / φ / upside and regime fit.",
    }

    def action_agent_hub(self) -> None:
        """Open the Agent Hub (Ctrl-K → 'agent hub', or 'manage ›' on the agent column header)."""
        try:
            self.push_screen(HubScreen())
        except Exception:
            pass

    def _agent_roster(self):
        """The cockpit's agents (.claude/agents/*.md → name + one-line role). Cached."""
        if getattr(self, "_roster_cache", None) is not None:
            return self._roster_cache
        roster = []
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude", "agents")
        try:
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".md"):
                    continue
                name, desc = fn[:-3], ""
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as fh:
                        head = fh.read(1400)
                    for line in head.splitlines():
                        if line.strip().startswith("description:"):
                            desc = line.split(":", 1)[1].strip()
                            break
                except Exception:
                    pass
                roster.append((name, desc.split(". ")[0][:52]))
        except Exception:
            roster = []
        self._roster_cache = roster
        return roster

    def action_hub_run_agent(self, name: str) -> None:
        if name == "antigravity":                          # the independent red-team — headless via agy
            if not self._focus:
                self._toast("focus a name first", ORANGE); return
            try:
                self.pop_screen()
            except Exception:
                pass
            self.action_ask("bear"); return
        tmpl = self._AGENT_PROMPT.get(name)
        if not tmpl:
            return
        tk = self._focus or ""
        if "{tk}" in tmpl and not tk and name not in self._AGENT_BOOK_LEVEL:
            self._toast("focus a name first", ORANGE); return
        try:
            self.pop_screen()
        except Exception:
            pass
        self._ask_agent(tmpl.replace("{tk}", tk))

    def _hub_commands_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cockpit_commands.json")

    def _user_commands(self) -> dict:
        try:
            with open(self._hub_commands_path(), encoding="utf-8") as fh:
                return {str(k): str(v) for k, v in ((json.load(fh) or {}).get("commands") or {}).items()}
        except Exception:
            return {}

    def _load_commands(self) -> dict:
        cmds = dict(self._HUB_DEFAULT_COMMANDS)
        cmds.update(self._user_commands())                 # user templates override / extend the defaults
        return cmds

    def _hub_save_command(self, line: str) -> None:
        line = (line or "").strip()
        low = line.lower()
        if low.startswith("job ") or low.startswith("job:"):     # 'job <kind> <topic> [@min]' → schedule
            self._hub_add_job(line[4:] if low.startswith("job ") else line[3:])
            return
        if "=" not in line:
            if line:
                self._toast("format: name = prompt with {ticker}  ·  or  job <kind> <topic> [@min]", ORANGE)
            return
        name, tmpl = line.split("=", 1)
        name = "".join(c for c in name.strip() if c.isalnum() or c in "-_")[:24]   # markup-safe id
        tmpl = tmpl.strip()
        if not name or not tmpl:
            return
        user = self._user_commands(); user[name] = tmpl
        try:
            os.makedirs(os.path.dirname(self._hub_commands_path()), exist_ok=True)
            with open(self._hub_commands_path(), "w", encoding="utf-8") as fh:
                json.dump({"commands": user}, fh, indent=2)
            self._toast(f"saved command '{name}'", GREEN)
        except Exception as exc:
            self._toast(f"save failed: {exc}", ORANGE)

    def action_hub_del_command(self, name: str) -> None:
        user = self._user_commands()
        if name in user:
            del user[name]
            try:
                with open(self._hub_commands_path(), "w", encoding="utf-8") as fh:
                    json.dump({"commands": user}, fh, indent=2)
            except Exception:
                pass
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    def action_hub_run_command(self, name: str) -> None:
        tmpl = self._load_commands().get(name)
        if not tmpl:
            return
        tk = self._focus or ""
        try:
            self.pop_screen()
        except Exception:
            pass
        self._ask_agent(tmpl.replace("{ticker}", tk).replace("{tk}", tk))

    # ---- the Hub's left control cards (built from app state; rendered by HubScreen.refresh_cards) ----
    _ANTIGRAVITY_DESC = "Independent red-team / bear case — runs headless via the Gemini-backed agy CLI."

    def _hub_roster_status(self, agent_id: str) -> str:
        """Live status for a roster agent: working if it has an in-flight run, scheduled if it owns an
        enabled job, the Sentinel watches, else its default (idle)."""
        if any(j.get("kind") == agent_id and not j.get("cancelled") for j in self._inflight.values()):
            return "working"
        if any((j.get("agent") == agent_id and j.get("enabled")) for j in (self._jobs or [])):
            return "scheduled"
        return _hub_meta(agent_id)[2]

    def _card_roster_markup(self) -> str:
        """TEAM — the roster, grouped by FUNCTION in a COLLAPSIBLE sidebar (click a group header to
        fold/unfold it — keeps the column uncluttered). Each agent is a compact one-line row: status
        dot · name · runtime-lane chip · ▶ run · ⏱ assign; click the name to inspect it (role + detail
        live in the FOCUS inspector). Each row shows the agent's model (◇) + runtime lane (▪)."""
        e = self._esc
        self._load_jobs()                                   # ensure self._jobs is populated for status
        extras = [nm for nm, _ in self._agent_roster() if nm not in HUB_AGENT_META]   # forward-compat
        n = len(HUB_AGENT_META) + len(extras)
        collapsed = self.screen._collapsed_groups if isinstance(self.screen, HubScreen) else set()
        lines = [f"[{AMBER}]Roster[/]  [{DIM}]{n} agents · claude + gemini · click a group to fold[/]"]
        # agents grouped by function (sentinel · council · research · audit · independent)
        for gid, gtitle, gnote in HUB_GROUPS:
            members = [a for a in HUB_AGENT_META if _hub_meta(a)[0] == gid]
            if gid == "audit":
                members += extras                           # any new .claude/agents land in Audit
            if not members:
                continue
            folded = gid in collapsed
            caret = "▸" if folded else "▾"
            lines.append(f"[@click=app.hub_toggle_group('{gid}')][{DIM}]{caret}[/] [bold #8C8C92]{gtitle}[/] "
                         f"[{DIM}]· {len(members)}[/][/]" + (f"  [{FAINT}]{gnote}[/]" if not folded else ""))
            if folded:
                continue
            for name in members:
                _g, lane, _st, _can = _hub_meta(name)
                status = self._hub_roster_status(name)
                sel = (self.screen._insp_agent == name and self.screen._insp_task is None) if isinstance(self.screen, HubScreen) else False
                nm_style = f"bold {AMBER}" if sel else "bold #FFFFFF"
                bl = f" [{DIM}]·bk[/]" if name in self._AGENT_BOOK_LEVEL else ""
                lines.append(
                    f"  {_status_dot(status)} [@click=app.hub_inspect_agent('{name}')][{nm_style}]{e(name)}[/][/] "
                    f"{_model_chip(name)} {_lane_chip(lane)}{bl}"
                    f"   [@click=app.hub_run_agent('{name}')][{GREEN}]▶[/][/]"
                    f" [@click=app.hub_assign('{name}')][{AMBER}]⏱[/][/]")
                tag = HUB_AGENT_DOC.get(name, {}).get("tag")     # a clear one-line 'what it does'
                if tag:
                    lines.append(f"     [@click=app.hub_inspect_agent('{name}')][{DIM}]{e(tag)}[/][/]")
        lines.append("[bold #8C8C92]PANES[/]  [{}]which CLIs are live[/]".format(DIM))
        for label, kw in (("🤖 claude", "CLAUDE"), ("🪐 antigravity", "ANTIGRAVITY"), ("🛠 operator", "OPERATOR")):
            live = bool(self._find_pane(kw))
            lines.append(f"  [{GREEN if live else DIM}]{'●' if live else '○'}[/] "
                         f"[{SILVER if live else DIM}]{label}[/] [{DIM}]{'live' if live else 'not in session'}[/]")
        return "\n".join(lines)

    def _card_recurring_markup(self) -> str:
        e = self._esc
        try:
            import cockpit_scheduler as sched
            jobs = self._load_jobs()
        except Exception:
            sched, jobs = None, []
        enabled = sum(1 for j in jobs if j.get("enabled"))
        lines = [f"[{AMBER}]⏲[/] [bold #8C8C92]SCHEDULED[/]  [bold {GOLD}]{enabled}[/]  [{DIM}]recurring · dial: {self._autonomy}[/]"]
        for j in jobs:
            jid = e(str(j.get("id", ""))); en = j.get("enabled"); nd = j.get("next_due"); when = ""
            if nd:
                mins = max(0, int((nd - time.time()) / 60))
                when = f"· in {mins}m" if mins < 90 else (f"· in {mins // 60}h" if mins < 2880 else f"· in {mins // 1440}d")
            dot = f"[{GREEN if en else DIM}]{'●' if en else '○'}[/]"
            who = f" [{TEAL}]by {e(j['agent'])}[/]" if j.get("agent") else ""
            lines.append(f"  {dot} [@click=app.job_run_now('{jid}')][{TEAL}]▶[/][/] "
                         f"[{SILVER if en else DIM}]{e(_clip(j.get('label', ''), 22))}[/]{who} [{DIM}]{j.get('every_min')}m {when}[/]"
                         f"  [@click=app.job_toggle('{jid}')][{DIM}]{'pause' if en else 'on'}[/][/]"
                         f" [@click=app.job_del('{jid}')][{DIM}]✕[/][/]")
        if not jobs:
            lines.append(f"  [{DIM}]none — e.g.[/] [{TEAL}]job scout silver @1440[/] [{DIM}]or[/] [{TEAL}]job bear AGA.V[/]")
            lines.append(f"  [{DIM}]assign an agent: ⏱ on the roster, or add[/] [{SILVER}]by <agent>[/]")
        return "\n".join(lines)

    def _card_commands_markup(self) -> str:
        e = self._esc
        user = self._user_commands()
        lines = [f"[bold #8C8C92]COMMANDS[/]  [{DIM}]{{ticker}} → focus[/]"]
        for name, tmpl in self._load_commands().items():
            row = (f"  [@click=app.hub_run_command('{e(name)}')][{TEAL}]›[/] [{SILVER}]{e(name)[:12].ljust(12)}[/][/] "
                   f"[{DIM}]{e(_clip(str(tmpl), 40))}[/]")
            if name in user:
                row += f"  [@click=app.hub_del_command('{e(name)}')][{DIM}]✕[/][/]"
            lines.append(row)
        return "\n".join(lines)

    def _card_audit_markup(self) -> str:
        """ENGINE AUDIT — the fetch · verify · review council over the engine itself (the numbers that
        feed it, the thresholds, the valuation formulas). Run on demand or schedule `job audit …`."""
        import glob as _glob
        e = self._esc
        lines = [f"[bold #8C8C92]ENGINE AUDIT[/]  [{DIM}]fetch · verify · review[/]",
                 f"  [@click=app.run_audit][{GOLD}]▶ run audit[/][/] [{DIM}]inputs · thresholds · formulas[/]"]
        files = sorted(_glob.glob(os.path.join(self._drafts_dir(), "audit_*.md")), reverse=True)
        if files:
            lines.append(f"  [{DIM}]last:[/] [@click=app.review_cat('result')][{TEAL}]{e(_clip(self._file_title(files[0]), 28))}[/][/]")
        else:
            lines.append(f"  [{DIM}]evaluates the data, thresholds & valuation formulas → a methodology report[/]")
        return "\n".join(lines)

    def action_run_audit(self) -> None:
        """Launch the engine-audit council now (fetch the inputs/thresholds/formulas, verify, review)."""
        try:
            import cockpit_scheduler as sched
            self._launch_job(sched.new_job("audit", "inputs · thresholds · valuation formulas"))
            self._toast("⏱ engine audit running — fetch · verify · review", TEAL)
        except Exception as exc:
            self._toast(f"audit failed to launch: {exc}", ORANGE)
        if isinstance(self.screen, HubScreen):
            self.screen.refresh_cards()

    # ======================================================================================
    # The Agent Hub — WORK column (delegate composer + board) & FOCUS column (inspector)
    # handoff: redesign/design_handoff_agent_hub. The fleet is uniformly Opus 4.8 — the chip
    # carries the runtime LANE, not the model; the autonomy boundary is concrete (alerts fire,
    # trims/exits/swaps are proposed). Every surface binds to live state / the Forge modules.
    # ======================================================================================
    def _hub_compose_lab_markup(self) -> str:
        return (f"[{AMBER}]Delegate a task[/]  [{DIM}]say it in plain words — it routes to the right agent and "
                f"hands over your whole request · ⏎ to send · a bare ticker sets the subject[/]")

    def _hub_composer_markup(self) -> str:
        """The composer line — agent · do-what · subject · when — then the Go button, whose label
        follows the verb/when (Delegate ⏎ / Schedule ⏲ / Arm rule ⏎ / File claim ⏎). Click a field's
        ▾ to cycle it. claim/rule hide 'when' (they file to the Ledger, not the scheduler)."""
        e = self._esc
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return ""
        a = scr._c_agent; verb = scr._c_verb; subj = (scr._c_subject or "").strip(); when = scr._c_when
        _g, lane, _st, _can = _hub_meta(a)
        ledger = verb in HUB_LEDGER_VERBS
        ready = bool(a and subj and subj != "—")
        fields = [f"[{DIM}]agent[/] [@click=app.hub_cycle('agent')][bold {SILVER}]{e(a)}[/] {_lane_chip(lane)} [{DIM}]▾[/][/]",
                  f"[{DIM}]do[/] [@click=app.hub_cycle('verb')][{GOLD}]{e(verb)}[/] [{DIM}]▾[/][/]",
                  f"[{DIM}]subject[/] [@click=app.hub_cycle('subject')][{AMBER}]{e(subj or '—')}[/] [{DIM}]▾[/][/]"]
        if not ledger:
            fields.append(f"[{DIM}]when[/] [@click=app.hub_cycle('when')][{SILVER}]{when}[/] [{DIM}]▾[/][/]")
        line = f"  [{FAINT}]·[/]  ".join(fields)
        if ledger:
            label = "Arm rule ⏎" if verb == "rule" else "File claim ⏎"; note = "files to the Thesis Ledger · validated at save"
        elif when == "schedule":
            label = "Schedule ⏲"; note = f"runs respect autonomy: {self._autonomy}"
        else:
            label = "Delegate ⏎"; note = f"runs on {_agent_model(a)[1]} · you'll be notified"
        go = (f"[@click=app.hub_go][bold {AMBER_BRIGHT} on #141418] {label} [/][/]" if ready
              else f"[{DIM}] {label} [/]")
        # ＋ step — add this (agent + instruction) to the Workflow chain instead of firing it now
        step = (f"[@click=app.hub_wf_add][{TEAL}]＋ step[/][/]" if (a and not ledger)
                else f"[{DIM}]＋ step[/]")
        return f"{line}\n  [{DIM}]{note}[/]   {go}    [{DIM}]or chain it →[/] {step}"

    def _hub_calendar_windows(self, n: int = 3) -> list:
        """Up to n upcoming catalyst windows for the header strip → (ticker, event, 'in Nd', is_macro).
        Grounded-or-silent: empty when the calendar module/data is unavailable (never invented)."""
        cal = self._calendar()
        if cal is None:
            return []
        try:
            import catalyst_calendar as cc
            from datetime import datetime, timezone
            rows = [r for r in (cal.query(within_days=120) or []) if r.get("window_start")]
            rows.sort(key=lambda r: str(r.get("window_start")))
            now = datetime.now(timezone.utc)
            out = []
            for r in rows[:n]:
                tk = r.get("ticker") or "macro"
                ev = r.get("title") or r.get("kind") or "event"
                macro = (str(r.get("kind")) == "macro") or not r.get("ticker")
                din = "soon"
                d = cc._parse(r.get("window_start"))
                if d is not None:
                    if d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    din = f"in {max(0, (d - now).days)}d"
                out.append((str(tk), _clip(str(ev), 14), din, macro))
            return out
        except Exception:
            return []

    def _hub_status_counts(self):
        """(awaiting, working, scheduled) for the header pips — all from live state."""
        awaiting = len(self._pending or []) + len(self._job_proposals or [])
        pipe = (self._state or {}).get("pipeline") or {}
        working = sum(1 for j in self._inflight.values() if not j.get("cancelled")) + (1 if pipe.get("status") == "running" else 0)
        scheduled = sum(1 for j in (self._load_jobs() or []) if j.get("enabled"))
        return awaiting, working, scheduled

    def _hub_done_markup(self) -> str:
        """✓ Done today — finished agent runs & research as READABLE cards: agent → subject + a one-line
        result, click to open the full output in the FOCUS reader (a Book thread or a saved draft)."""
        e = self._esc
        runs = list(self._done_runs or [])[:6]
        lines = [f"[{GREEN}]✓[/] [bold #8C8C92]DONE TODAY[/]  [bold {GOLD}]{len(self._done_runs or [])}[/]  "
                 f"[{DIM}]finished work · click to read[/]"]
        if not runs:
            lines.append(f"  [{DIM}]nothing yet — delegated & scheduled runs land here when they finish[/]")
        for r in runs:
            rid = r.get("id")
            click = f"@click=app.hub_open_done('{rid}')"
            glyph = "↯" if r.get("cat") == "thread" else "✎"
            lines.append(f"  [{GREEN}]{glyph}[/] [{click}][bold {SILVER}]{e(r.get('agent', ''))}[/] "
                         f"[{DIM}]→[/] [{AMBER}]{e(_clip(r.get('subject', '—'), 12))}[/][/] "
                         f"[{DIM}]· {_rel_age(r.get('ts'))}[/]")
            if r.get("summary"):
                lines.append(f"     [{click}][{DIM}]{e(_clip(r.get('summary', ''), 52))}[/][/]")
        return "\n".join(lines)

    def action_hub_open_done(self, run_id) -> None:
        """Open a finished run's full output in the FOCUS reader (the board → read flow)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        run = next((r for r in (self._done_runs or []) if str(r.get("id")) == str(run_id)), None)
        if not run:
            return
        scr.open_ref(run.get("cat", "thread"), run.get("ref"))

    # ======================================================================================
    # Workflows — composable agent CHAINS. A workflow is a list of stages; each stage is one or
    # more agents (>1 = a parallel fan-out) + an instruction. Each stage's OUTPUT is handed to the
    # next as context, so the team works as a line — scout → [value ∥ balance-sheet] → verifier →
    # package — and you get one assembled dossier on the Results board. (No bubbles.)
    # ======================================================================================
    def _workflows_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cockpit_workflows.json")

    def _load_workflows(self) -> dict:
        if self._workflows is None:
            try:
                with open(self._workflows_path(), encoding="utf-8") as fh:
                    self._workflows = {str(k): v for k, v in ((json.load(fh) or {}).get("workflows") or {}).items()}
            except Exception:
                self._workflows = {}
        return self._workflows

    def _save_workflows(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._workflows_path()), exist_ok=True)
            with open(self._workflows_path(), "w", encoding="utf-8") as fh:
                json.dump({"workflows": self._workflows or {}}, fh, indent=2)
        except Exception as exc:
            self._toast(f"save failed: {exc}", ORANGE)

    @staticmethod
    def _wf_stage_label(step: dict) -> str:
        return " ∥ ".join(step.get("agents", []) or ["?"])

    def _hub_workflow_markup(self) -> str:
        """⛓ WORKFLOW — the chain being composed (or running): each stage = agent(s) + instruction;
        outputs flow stage→stage; the last stage is packaged to the Results board."""
        e = self._esc
        steps = self._workflow or []
        running = self._wf_running
        n = len(steps)
        head = (f"[{TEAL}]⛓[/] [bold #8C8C92]WORKFLOW[/]  [bold {GOLD}]{n}[/]  "
                f"[{DIM}]{'running…' if running else 'chain · outputs flow stage→stage → packaged'}[/]")
        lines = [head]
        if not steps:
            lines.append(f"  [{DIM}]Build a chain: set agent + a plain-language instruction below, then[/] "
                         f"[{TEAL}]＋ step[/][{DIM}].  e.g. scout (fit) → value ∥ balance-sheet → verifier.[/]")
        for i, st in enumerate(steps):
            par = len(st.get("agents", [])) > 1
            agents = "  ∥  ".join(f"[{AMBER}]{e(x)}[/]" for x in st.get("agents", []))
            arrow = f"  [{DIM}]↓ passes output to[/]" if i < n - 1 else f"  [{DIM}]↓ packaged → Results board[/]"
            ctl = "" if running else (f"   [@click=app.hub_wf_merge('{i}')][{TEAL}]∥+agent[/][/] "
                                      f"[@click=app.hub_wf_del('{i}')][{DIM}]✕[/][/]")
            lines.append(f"  [{GOLD}]{i + 1}.[/] {agents}{'  [{}]∥ parallel[/]'.format(TEAL) if par else ''}{ctl}")
            if st.get("note"):
                lines.append(f"      [{SILVER}]{e(_clip(st['note'], 60))}[/]")
            lines.append(arrow)
        # action row + saved workflows
        if steps and not running:
            run = f"[@click=app.hub_wf_run][bold {AMBER_BRIGHT} on #141418] ▶ Run workflow [/][/]"
            lines.append(f"  {run}   [@click=app.hub_wf_save][{TEAL}]⊹ save…[/][/]   "
                         f"[@click=app.hub_wf_clear][{DIM}]✕ clear[/][/]")
        saved = self._load_workflows()
        if saved and not running:
            row = f"  [{DIM}]load:[/] " + "  ".join(
                f"[@click=app.hub_wf_load('{e(nm)}')][{TEAL}]▸ {e(nm)}[/][/]" for nm in list(saved)[:5])
            lines.append(row)
        return "\n".join(lines)

    def _paint_workflow(self) -> None:
        if isinstance(self.screen, HubScreen):
            try:
                self.screen.query_one("#hub_workflow", Static).update(self._hub_workflow_markup())
            except Exception:
                pass

    def action_hub_wf_add(self) -> None:
        """Append the current composer (agent + instruction) as a new workflow stage."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        note = ""
        try:
            note = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        note = note or f"{scr._c_verb} {scr._c_subject}".strip()
        self._workflow.append({"agents": [scr._c_agent], "note": note})
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        self._paint_workflow()
        self._toast(f"added step {len(self._workflow)}: {scr._c_agent} — set the next one, or ▶ Run", TEAL)

    def action_hub_wf_merge(self, idx) -> None:
        """Add the current composer agent to stage idx — making it a PARALLEL fan-out (same input,
        several agents at once)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        try:
            st = self._workflow[int(idx)]
        except Exception:
            return
        if scr._c_agent not in st["agents"]:
            st["agents"].append(scr._c_agent)
        self._paint_workflow()
        self._toast(f"stage {int(idx) + 1} now runs {' ∥ '.join(st['agents'])} in parallel", TEAL)

    def action_hub_wf_del(self, idx) -> None:
        try:
            self._workflow.pop(int(idx))
        except Exception:
            return
        self._paint_workflow()

    def action_hub_wf_clear(self) -> None:
        self._workflow = []
        self._paint_workflow()

    def action_hub_wf_save(self) -> None:
        """Save the current chain as a named workflow (name comes from the NL line, else auto)."""
        scr = self.screen
        if not isinstance(scr, HubScreen) or not self._workflow:
            return
        name = ""
        try:
            name = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        name = "".join(c for c in name if c.isalnum() or c in " -_").strip()[:32] or f"workflow-{len(self._load_workflows()) + 1}"
        self._load_workflows()[name] = [dict(s) for s in self._workflow]
        self._save_workflows()
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        self._paint_workflow()
        self._toast(f"saved workflow '{name}'", GREEN)

    def action_hub_wf_load(self, name: str) -> None:
        wf = self._load_workflows().get(name)
        if not wf:
            return
        self._workflow = [dict(s) for s in wf]
        self._paint_workflow()
        self._toast(f"loaded '{name}' — edit it, or ▶ Run workflow", TEAL)

    def action_hub_wf_run(self) -> None:
        """Run the composed chain headless (stages in order; parallel agents within a stage; outputs
        flow forward; the result is packaged to the Results board)."""
        if self._wf_running:
            self._toast("a workflow is already running", ORANGE); return
        if not self._workflow:
            self._toast("build a chain first (＋ step)", ORANGE); return
        scr = self.screen
        subject = (scr._c_subject if isinstance(scr, HubScreen) else None) or self._focus or "book"
        steps = [dict(s) for s in self._workflow]
        self._wf_running = True
        self._paint_workflow()
        self._toast(f"▶ workflow running ({len(steps)} stages) — watch Working; the package lands on the board", GREEN)
        self._run_workflow_bg(steps, subject)

    @work(thread=True, group="workflow", exclusive=True)
    def _run_workflow_bg(self, steps: list, subject: str) -> None:
        """Execute the chain. Each stage's agents run via the configured CLI; their output is appended
        to a running context handed to the next stage. A final package (every stage's output) is saved
        as a Result draft and surfaced on the board."""
        import concurrent.futures as _cf
        _post("/pipeline/event", {"status": "running", "stage": self._wf_stage_label(steps[0]),
                                  "theme": subject, "message": f"workflow · {len(steps)} stages"})
        context = ""                                        # accumulated prior-stage output (the flow)
        transcript = []
        for si, st in enumerate(steps):
            agents = st.get("agents", []) or ["scout"]
            note = st.get("note", "") or "proceed"
            _post("/pipeline/event", {"status": "running", "stage": self._wf_stage_label(st),
                                      "message": f"stage {si + 1}/{len(steps)}"})

            def _run_one(agent):
                prov = self._agent_provider(agent)           # route each stage to its provider's CLI
                jid = None
                try:
                    jid = self.call_from_thread(self._inflight_add, agent, note, subject, agent, prov)
                except Exception:
                    pass
                prior = (f"\n\n--- Prior stage output to build on (do not repeat it; advance it) ---\n{context}"
                         if context.strip() else "")
                if prov == "gemini":
                    argv = self._agy_argv(self._gemini_prompt(agent, note + prior, subject))
                else:
                    argv = self._pipeline_argv(f"@{agent} {note}\n\nSubject / book context: {subject}.{prior}")
                try:
                    out = subprocess.run(argv, capture_output=True, text=True,
                                         timeout=int(os.environ.get("CEX_PIPELINE_TIMEOUT", "900")),
                                         cwd=os.path.dirname(os.path.abspath(__file__)))
                    res = (out.stdout or "").strip() or (out.stderr or "").strip()
                except Exception as exc:
                    res = f"(stage error: {exc})"
                if jid is not None:
                    try:
                        self.call_from_thread(self._inflight_done, jid)
                    except Exception:
                        pass
                return agent, (res or "(no output — check the agent CLI permission flags)")

            results = []
            if len(agents) > 1:                             # parallel fan-out
                with _cf.ThreadPoolExecutor(max_workers=min(4, len(agents))) as ex:
                    results = list(ex.map(_run_one, agents))
            else:
                results = [_run_one(agents[0])]

            stage_block = "\n\n".join(f"### {ag} — {note}\n{txt}" for ag, txt in results)
            transcript.append((si + 1, self._wf_stage_label(st), note, results))
            context = (context + "\n\n" + stage_block).strip()   # flows into the next stage

        path = self._save_workflow_package(subject, steps, transcript)
        _post("/pipeline/event", {"status": "done", "stage": "package", "message": "workflow complete",
                                  "result": (context[-3500:] if context else "")})
        self.call_from_thread(self._record_done_run, "workflow", subject,
                              f"{len(steps)}-stage chain → packaged", "result", path)
        self.call_from_thread(self._wf_finish)

    def _wf_finish(self) -> None:
        self._wf_running = False
        self._receipt("workflow complete → Results board", "⛓", GREEN)
        self._paint_workflow()
        self._toast("✓ workflow complete — the package is on the Results board", GREEN)

    def _save_workflow_package(self, subject: str, steps: list, transcript: list):
        """Assemble the chain's output into ONE dossier (the 'nice package at the end') under
        data/agent_drafts/, where the Results board reads it."""
        import datetime
        try:
            d = self._drafts_dir()
            os.makedirs(d, exist_ok=True)
            safe = "".join(c if c.isalnum() else "_" for c in str(subject))[:24] or "book"
            path = os.path.join(d, f"workflow_{safe}_{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
            chain = "  →  ".join(self._wf_stage_label(s) for s in steps)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"# Workflow package — {subject}\n\n_{datetime.datetime.now():%Y-%m-%d %H:%M} · "
                         f"chain: {chain} · review draft (not applied / not committed)_\n\n")
                for num, label, note, results in transcript:
                    fh.write(f"\n## Stage {num} · {label}\n_{note}_\n\n")
                    for ag, txt in results:
                        fh.write(f"### {ag}\n\n{txt}\n\n")
            return path
        except Exception:
            return None

    # ---- the FOCUS column: the agent / task inspectors -----------------------------------------
    def _agent_role(self, agent_id: str) -> str:
        """A clear, full 'what it does' line — the curated copy first (HUB_AGENT_DOC), falling back to
        the .claude/agents blurb only for agents we haven't documented yet (never the 52-char stub)."""
        doc = HUB_AGENT_DOC.get(agent_id, {})
        if doc.get("what"):
            return doc["what"]
        return dict(self._agent_roster()).get(agent_id, "")

    def _agent_recent(self, agent_id: str, n: int = 3) -> list:
        """Recent outputs/alerts for an agent → (level, text, meta), from Living Memory entries whose
        source names the agent. Grounded; empty if none."""
        mem = self._memory()
        if mem is None:
            return []
        out = []
        try:
            for ent in mem.query(limit=60):
                if agent_id.lower() not in str(ent.get("source", "")).lower():
                    continue
                low = str(ent.get("text", "")).lower()
                typ = str(ent.get("type", "note"))
                level = ("warn" if any(w in low for w in ("flag", "stale", "risk", "below", "dilut"))
                         else ("good" if typ in ("council_verdict", "outcome") else "info"))
                out.append((level, _clip(str(ent.get("text", "")), 44), f"{_mem_age(ent.get('ts'))} ago"))
                if len(out) >= n:
                    break
        except Exception:
            return []
        return out

    def _sentinel_watch_rows(self) -> list:
        """The Sentinel's four checks → (name, status, note, value). If a recent sweep wrote to memory
        we surface its read (warn); otherwise we describe what each check watches — never an invented
        per-name number (grounded-or-silent, per the Forge spec)."""
        rows = [("liquidity-runway", "days of ADV to exit the position", "≥ 5d floor"),
                ("financing-window", "price vs last placement · death-spiral", "dilution ≤ 2% QoQ"),
                ("thesis-integrity", "load-bearing claims vs the tape", "claims tracked"),
                ("Ulysses rules", "armed pre-commitments · parsed at save", "fail-closed")]
        latest = None
        mem = self._memory()
        if mem is not None:
            try:
                for ent in mem.query(limit=40):
                    if "sentinel" in str(ent.get("source", "")).lower() or str(ent.get("type")) == "sentinel":
                        latest = ent; break
            except Exception:
                latest = None
        out = []
        for k, note, v in rows:
            status, n = "ok", note
            if latest is not None and k.split("-")[0].split()[0] in str(latest.get("text", "")).lower():
                status, n = "warn", _clip(str(latest.get("text", "")), 40)
            out.append((k, status, n, v))
        return out

    def _agent_inspector_markup(self, agent_id: str):
        """The selected agent's detail — what it does · WHEN to reach for it · its Can-do verbs · example
        briefs you can click to pre-fill (then edit for specifics) · the Sentinel's Watching panel ·
        standing jobs · recent outputs. The whole request you type is handed through, verbatim."""
        e = self._esc
        _g, lane, _st, can = _hub_meta(agent_id)
        r = HUB_RUNTIMES.get(lane, {})
        doc = HUB_AGENT_DOC.get(agent_id, {})
        status = self._hub_roster_status(agent_id)
        prov = self._agent_provider(agent_id)
        provnote = "gemini · agy CLI" if prov == "gemini" else f"claude · {r.get('sub', '')}"
        md = [f"[bold #FFFFFF]{e(agent_id)}[/]   {_status_dot(status)} [{DIM}]{status}[/]",
              f"{_model_chip(agent_id)} {_lane_chip(lane)} [{DIM}]{provnote}[/]",
              f"[{SILVER}]{e(_clip(self._agent_role(agent_id), 200))}[/]", ""]
        if doc.get("when"):
            md.append(f"[bold #8C8C92]USE WHEN[/]")
            md.append(f"  [{DIM}]{e(doc['when'])}[/]")
            md.append("")
        if agent_id == "sentinel":
            md.append(f"[bold #8C8C92]WATCHING[/] [{DIM}]· every 6h sweep[/]")
            for k, st, note, v in self._sentinel_watch_rows():
                dot = f"[{GREEN}]●[/]" if st == "ok" else f"[{ORANGE}]◔[/]"
                md.append(f"  {dot} [{SILVER}]{e(k)}[/]  [{DIM}]{e(note)}[/]  [{DIM}]{e(v)}[/]")
            md.append("")
        md.append(f"[bold #8C8C92]CAN DO[/] [{DIM}]· click to set the verb[/]")
        md.append("  " + "  ".join(f"[@click=app.hub_pick('verb','{e(k)}')][{TEAL}]{e(k)}[/][/]" for k in can))
        md.append("")
        if doc.get("eg"):
            md.append(f"[bold #8C8C92]TRY[/] [{DIM}]· click to load, then edit for specifics[/]")
            for i, ex in enumerate(doc["eg"]):
                md.append(f"  [{AMBER}]›[/] [@click=app.hub_example('{agent_id}', {i})][{SILVER}]{e(ex)}[/][/]")
            md.append("")
        myjobs = [j for j in (self._load_jobs() or []) if j.get("agent") == agent_id]
        md.append(f"[bold #8C8C92]RECURRING[/] [{DIM}]· {len(myjobs) or 'none'}[/]")
        for j in myjobs[:4]:
            md.append(f"  [{AMBER}]⏲[/] [{SILVER}]{e(_clip(j.get('label', ''), 28))}[/] [{DIM}]{j.get('every_min')}m[/]")
        md.append("")
        md.append(f"[bold #8C8C92]{'RECENT ALERTS' if agent_id == 'sentinel' else 'RECENT OUTPUTS'}[/]")
        recent = self._agent_recent(agent_id, 3)
        if recent:
            for level, txt, meta in recent:
                md.append(f"  [{_level_color(level)}]●[/] [{SILVER}]{e(txt)}[/] [{DIM}]{e(meta)}[/]")
        else:
            md.append(f"  [{DIM}]no runs yet — delegate one below[/]")
        acts = (f"[@click=app.hub_delegate_agent('{e(agent_id)}')][bold {AMBER}]▶ Delegate to {e(agent_id)}[/][/]   "
                f"[@click=app.hub_schedule('{e(agent_id)}')][{DIM}]⏲ Schedule…[/][/]   [{DIM}]· Esc[/]")
        return ("\n".join(md), acts)

    def _task_inspector_markup(self, jid):
        """A running task's detail — who's doing it, the task itself, elapsed, and a live note."""
        e = self._esc
        j = self._inflight.get(int(jid))
        if not j:
            return (f"[bold {GOLD}]task ended[/]\n\n[{DIM}]it finished — see Done today.[/]", f"[{DIM}]· Esc[/]")
        el = max(0, int(time.time() - j.get("started", time.time())))
        who, task = self._task_label(j)
        prov = j.get("provider") or self._agent_provider(who)
        model = _run_model_label(who, prov)
        md = [f"[bold #FFFFFF]{e(who)}[/] [{DIM}]is running[/]" + (f" [{DIM}]·[/] [{AMBER}]{e(j['ticker'])}[/]" if j.get("ticker") else ""),
              f"{_model_chip(who) if who in HUB_AGENT_MODEL else ''} [{DIM}]working · {el}s · {model}[/]",
              f"[{SILVER}]{e(_clip(task or j.get('label', ''), 160))}[/]", "",
              f"[bold #8C8C92]LIVE[/]",
              f"  [{TEAL}]$[/] [{DIM}]{e(who)} · grounding context…[/]",
              f"  [{GREEN}]⟳[/] [{SILVER}]running — the result will land on the Results board[/]"]
        acts = (f"[@click=app.cancel_job('{jid}')][{ORANGE}]✕ Cancel run[/][/]   "
                f"[@click=app.hub_clear_inspect][{DIM}]Close detail[/][/]   [{DIM}]· Esc[/]")
        return ("\n".join(md), acts)

    # ---- composer / inspector actions (clicked from the Hub markup) ----------------------------
    def action_hub_inspect_agent(self, agent_id: str) -> None:
        """Select an agent → focus it in the inspector AND load it into the composer (the verb resets
        to its first capability if the current verb isn't one of its own)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._insp_agent = agent_id
        scr._insp_task = None
        scr._sel = -1                                  # leave the reader → show the inspector
        scr._c_agent = agent_id
        can = _hub_meta(agent_id)[3]
        if scr._c_verb not in can:
            scr._c_verb = can[0] if can else "ask"
        scr.refresh_cards()
        scr._paint()

    def action_hub_inspect_task(self, jid) -> None:
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._insp_task = int(jid)
        scr._sel = -1
        scr.refresh_cards()
        scr._paint()

    def action_hub_clear_inspect(self) -> None:
        scr = self.screen
        if isinstance(scr, HubScreen):
            scr._insp_task = None
            scr.refresh_cards()
            scr._paint()

    def action_hub_toggle_group(self, gid: str) -> None:
        """Fold / unfold a roster group (the collapsible TEAM sidebar)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._collapsed_groups ^= {gid}                  # toggle membership
        try:
            scr.query_one("#hub_roster", Static).update(self._card_roster_markup())
        except Exception:
            pass

    def action_hub_cycle(self, field: str) -> None:
        """Cycle a composer field forward (agent · verb · subject · when)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        if field == "agent":
            ids = list(HUB_AGENT_META.keys())
            i = ids.index(scr._c_agent) if scr._c_agent in ids else -1
            scr._c_agent = ids[(i + 1) % len(ids)]
            can = _hub_meta(scr._c_agent)[3]
            if scr._c_verb not in can:
                scr._c_verb = can[0] if can else "ask"
        elif field == "verb":
            can = _hub_meta(scr._c_agent)[3] or HUB_VERBS
            i = can.index(scr._c_verb) if scr._c_verb in can else -1
            scr._c_verb = can[(i + 1) % len(can)]
        elif field == "when":
            scr._c_when = "schedule" if scr._c_when == "now" else "now"
        elif field == "subject":
            opts = ["book"] + sorted(self._baskets_by_ticker or {}) + ["silver universe"]
            i = opts.index(scr._c_subject) if scr._c_subject in opts else -1
            scr._c_subject = opts[(i + 1) % len(opts)]
        scr.refresh_cards()

    def action_hub_pick(self, field: str, value: str) -> None:
        """Set a composer field directly (e.g. from the inspector's Can-do chips)."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        if field == "agent":
            self.action_hub_inspect_agent(value)
            return
        if field == "verb":
            scr._c_verb = value
        elif field == "subject":
            scr._c_subject = value
        scr.refresh_cards()

    def action_hub_example(self, agent_id: str, idx) -> None:
        """Load an example brief into the NL line (then the operator edits it for specifics and sends).
        This is the granular path — the example is a starting point, not a fixed template."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        try:
            ex = HUB_AGENT_DOC.get(agent_id, {}).get("eg", [])[int(idx)]
        except Exception:
            return
        scr._c_agent = agent_id
        tk = self._detect_ticker(ex)
        if tk:
            scr._c_subject = tk
        try:
            box = scr.query_one("#hub_input", Input)
            box.value = ex
            box.cursor_position = len(ex)
            scr.set_focus(box)
        except Exception:
            pass
        scr.refresh_cards()
        self._toast("loaded — edit for specifics, then ⏎ to send it through to the agent", TEAL)

    def action_hub_delegate_agent(self, agent_id: str) -> None:
        """Delegate to this agent using whatever is typed in the NL line as the FULL brief (pass-through).
        Empty line → prefill it so you can write a specific request rather than fire a template."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        scr._c_agent = agent_id
        scr._c_when = "now"
        brief = ""
        try:
            brief = scr.query_one("#hub_input", Input).value.strip()
        except Exception:
            pass
        if not brief:
            try:
                box = scr.query_one("#hub_input", Input)
                box.value = ""
                scr.set_focus(box)
            except Exception:
                pass
            self._toast(f"type what you want {agent_id} to do, then ⏎ — your words go through verbatim", TEAL)
            return
        tk = self._detect_ticker(brief) or (scr._c_subject if scr._c_subject not in ("book", "—") else None)
        self._delegate(agent_id, brief, subject=tk, verb=scr._c_verb)
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        scr.refresh_cards()

    def action_hub_schedule(self, agent_id: str) -> None:
        scr = self.screen
        if isinstance(scr, HubScreen):
            scr._c_agent = agent_id
            scr._c_when = "schedule"
            scr.refresh_cards()
        self._toast(f"composer set to schedule {agent_id} — pick a verb/subject, then Schedule ⏲", TEAL)

    def action_hub_go(self, nl: str = None) -> None:
        """Send the composer. claim/rule → file to the Thesis Ledger (parsed/validated at save);
        schedule → add a recurring job (dial-gated); now → delegate to the agent as a background run
        (visible in the Working lane). The route follows verb + when."""
        scr = self.screen
        if not isinstance(scr, HubScreen):
            return
        a = scr._c_agent; verb = scr._c_verb; subj = (scr._c_subject or "").strip(); when = scr._c_when
        if nl is None:
            try:
                nl = scr.query_one("#hub_input", Input).value.strip()
            except Exception:
                nl = ""
        if not subj or subj == "—":
            self._toast("set a subject first (click subject ▾, or type a ticker)", ORANGE)
            return
        is_name = subj not in ("book", "silver universe")
        if verb in HUB_LEDGER_VERBS:
            if is_name:
                self._focus = subj                     # claims/rules attach to the named thesis
            if verb == "rule":
                if "->" in (nl or ""):
                    self._amend_thesis_rule(nl)
                else:
                    self._toast("rule: type the trigger in the line — e.g. phi < 1.0 -> trim_to 0.4", ORANGE)
                    return
            else:
                self._amend_thesis_claim(nl or f"{subj}: thesis claim")
        elif when == "schedule":
            import cockpit_scheduler as sched
            kind = verb if verb in getattr(sched, "JOB_KINDS", ()) else "ask"
            agent = a if a in self._agent_names() else None
            self._add_job(kind, (f"{subj} — {nl}" if nl else subj), agent=agent)
        else:
            self._delegate(a, nl or f"{verb} {subj}", subject=subj, verb=verb)
        try:
            scr.query_one("#hub_input", Input).value = ""
        except Exception:
            pass
        scr.refresh_cards()

    # ---- the intent router + pass-through delegation (the NL bar reads your words, the agent gets
    #      your WHOLE request — no template flattening) ------------------------------------------
    def _detect_ticker(self, text: str):
        """Pull a ticker out of free text — a known holding first, else an EXCHANGE-suffixed symbol
        (URC.TO, AGA.V). Conservative: a bare uppercase word is NOT treated as a ticker."""
        import re
        up = (text or "").upper()
        for tk in sorted(self._baskets_by_ticker or {}, key=len, reverse=True):
            if re.search(rf"\b{re.escape(tk)}\b", up):
                return tk
        m = re.search(r"\b[A-Z]{1,5}\.[A-Z]{1,2}\b", up)
        return m.group(0) if m else None

    def _route_intent(self, text: str):
        """Map a natural-language request → (agent, verb, ticker). agent/verb are None when no keyword
        matches (→ hand to the general orchestrator). The ticker is best-effort."""
        low = f" {(text or '').lower()} "
        tk = self._detect_ticker(text)
        for keywords, agent, verb in HUB_INTENT_RULES:
            if any(kw in low for kw in keywords):
                return agent, verb, tk
        return None, None, tk

    def _has_gemini(self) -> bool:
        """Is the Gemini (agy) CLI actually available? Cached. If not, gemini-routed agents fall back
        to Claude so nothing breaks when agy isn't configured."""
        if getattr(self, "_agy_ok", None) is None:
            import shutil
            binary = os.environ.get("CEX_AGY_CMD", "agy")
            self._agy_ok = bool(shutil.which(binary)) or bool(os.environ.get("CEX_AGY_HEADLESS"))
        return self._agy_ok

    def _agent_provider(self, agent: str) -> str:
        """Effective provider for an agent — the registry's choice, but falling back to Claude when the
        Gemini (agy) CLI isn't installed/configured."""
        prov = _agent_model(agent)[0]
        if prov == "gemini" and not self._has_gemini():
            return "claude"
        return prov

    def _gemini_prompt(self, agent: str, brief: str, subject: str = None) -> str:
        """Wrap a brief for a Gemini seat — the agent's role + a Google Finance grounding nudge (its
        edge for accurate prices/data), since Gemini doesn't carry the .claude subagent definition."""
        role = self._agent_role(agent) or f"the {agent}"
        subj = f"  Subject / book context: {subject}." if subject and subject not in ("book", "—") else ""
        return (f"You are {agent} — {role}\n\nUse Google Finance / Google Search grounding for accurate, "
                f"current prices and figures; cite sources; never invent a number.{subj}\n\nTask: {brief}")

    def _delegate(self, agent: str, brief: str, subject: str = None, verb: str = None) -> None:
        """Hand a FULL natural-language brief to an agent — the whole request, verbatim. Routes to the
        agent's provider: Claude (claude -p @agent) or Gemini (the agy CLI), per HUB_AGENT_MODEL."""
        brief = (brief or "").strip()
        subj = (subject or "").strip()
        prov = self._agent_provider(agent)
        label = brief or f"{verb or ''} {subj}".strip()
        if prov == "gemini":
            self._ask_agent(self._gemini_prompt(agent, brief, subj), provider="gemini", agent=agent, label=label)
            self._toast(f"delegated → {agent} (gemini-flash) — watch the Working lane, result lands on the board", GREEN)
            return
        ctx = (f"  (subject: {subj})" if subj and subj not in ("book", "silver universe", "—")
               and subj.lower() not in brief.lower() and agent not in self._AGENT_BOOK_LEVEL else "")
        model = _agent_model(agent)[1]
        if agent == "sentinel":
            body = brief or ("Run a Sentinel sweep on the book — liquidity-runway, financing-window / "
                             "death-spiral, thesis-integrity, and armed Ulysses rules.")
            self._ask_agent(f"As the Sentinel (the book's risk watcher), {body}{ctx}", agent=agent, label=label)
        elif agent in self._agent_names():
            self._ask_agent(f"@{agent} {brief}{ctx}", agent=agent, label=label)
        else:
            self._ask_agent(brief)                          # no specific agent → the orchestrator routes
            model = "claude"
        self._toast(f"delegated → {agent} ({model}) — watch the Working lane, result lands on the board", GREEN)

    def _hub_scenario(self, idea: str) -> None:
        """Run a free-form what-if SCENARIO from the Hub — close to the desk, focus the what-if, and let
        an agent build the knob move + a narrative of the effects beyond the knobs."""
        idea = (idea or "").strip()
        if not idea:
            self._toast("scenario: describe it — e.g. 'uranium spot doubles on a supply shock'", ORANGE)
            return
        try:
            self.pop_screen()                               # leave the Hub so the desk what-if is visible
        except Exception:
            pass
        try:
            self.action_whatif_focus()
            tk = self._detect_ticker(idea) or self._focus or ""
            if tk:
                self.query_one("#wf_ticker", Input).value = tk
            self.query_one("#wf_overrides", Input).value = idea
        except Exception:
            pass
        self._do_whatif()
        self._toast("scenario → an agent is building the knobs + a brief beyond them", TEAL)

    def action_focus_tk(self, tk: str) -> None:
        """Click a ticker anywhere (desk tape, notes, memory) -> focus it on the spine."""
        self._pop_if_modal()                          # if invoked from a detail pop-over, close it
        if tk and tk != "_book":
            self.action_tab("book")
            self._set_focus(str(tk), move_cursor=True)

    def _ask_agent(self, text: str, provider: str = "claude", agent: str = None, label: str = None) -> None:
        """Plain-text query → a *background* headless agent. Hangs off the active conversation node
        (None → a fresh thread). Context sent to the agent is ONLY the active branch's lineage, so
        research threads stay isolated. Both query and reply land in the CONVERSATION tree (Book).
        `provider` picks the CLI (claude / gemini-agy); `agent`/`label` make the run self-describing."""
        text = text.strip()
        if not text:
            return
        self._asked = text
        low = text.lower()
        if "convene" in low or "council" in low:     # convening expands the inline council (merged view)
            self._council_open = True
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
        jid = self._inflight_add("ask", label or text, self._focus or "", agent=agent, provider=provider)
        self._ask_agent_bg(text, uid, jid, provider)

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
        self._receipt(f"dossier {os.path.basename(path)}", "⇪", GOLD, undo=lambda p=path: self._undo_file(p))
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
    def _ask_agent_bg(self, text: str, uid: str, jid: int = 0, provider: str = "claude") -> None:
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
        # prepend the shared situational frame (Forge #3) so the agent never starts blind — regime,
        # posture, what you're looking at + doing, the book's verdicts, recent memory.
        frame = ""
        try:
            import world_state
            frame = world_state.render_brief(
                world_state.build(self._state or {}, focus=self._focus)) + "\n\n"
        except Exception:
            frame = ""
        prompt = f"{frame}{ctx}{bind}{text}"
        # Popen (not run) so a cancel from the AGENTS strip can terminate the child mid-flight.
        argv = self._agy_argv(prompt) if provider == "gemini" else self._ask_argv(prompt)
        proc = None
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    cwd=os.path.dirname(os.path.abspath(__file__)))
            if jid in self._inflight:
                self._inflight[jid]["proc"] = proc
            out, err = proc.communicate(timeout=int(os.environ.get("CEX_ASK_TIMEOUT", "300")))
            reply = (out or "").strip() or (err or "").strip()
        except FileNotFoundError:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text("ask: CLI not found — set CEX_ASK_CMD", style=ORANGE)); return
        except subprocess.TimeoutExpired:
            try:
                proc.kill(); proc.communicate()
            except Exception:
                pass
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text("ask timed out — raise CEX_ASK_TIMEOUT", style=ORANGE)); return
        except Exception as exc:
            self.call_from_thread(self._inflight_done, jid)
            self.call_from_thread(self._status, Text(f"ask failed: {exc}", style=ORANGE)); return
        cancelled = self._inflight.get(jid, {}).get("cancelled", False)
        self.call_from_thread(self._inflight_done, jid)
        if cancelled:                                  # the operator stopped this run — drop the reply
            return
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
            # surface the finished run on the Hub's Done board (readable — opens this thread)
            root = self._branch_root(aid)
            tk = (self._conv.get(root) or {}).get("ticker") or self._focus or "—"
            summary = (str(rep["text"]).strip().splitlines() or [""])[0]
            self._record_done_run(rep.get("agent", "claude"), tk, summary, cat="thread", ref=root)
            try:
                self.query_one("#spine", VerticalScroll).scroll_end(animate=False)
            except Exception:
                pass
        self.query_one("#agent_reply", Static).update(self._conversation_markup())

    def _council_strip(self, tk) -> list:
        """The Dialectic Council reconciliation for the focused name — inline on the Book page,
        sharing THIS conversation (no separate tab). Collapsed: the verdict + φ/ρ/invalidation +
        a click to expand. Expanded (``self._council_open``): the full Bull / Bear / Arbiter
        debate, action buttons that post into this same chat, and the living research thread.
        Empty when no name is focused."""
        tk = (tk or "").strip()
        b = self._baskets_by_ticker.get(tk) if tk else None
        if not b:
            return []
        pil = b.get("pillars", {}) if isinstance(b.get("pillars"), dict) else {}
        V = pil.get("V", {}) or {}
        T = pil.get("T", {}) or {}
        gate = b.get("gate", {}) or {}
        L = b.get("ladder", {}) or {}
        rating = b.get("rating")
        hc = health_color(rating)
        rule = f"[{BORDER}]{'─' * 52}[/]"

        def g(x, s="{:.2f}"):
            v = _num(x)
            return s.format(v) if v is not None else "—"

        # reconciled verdict from Living Memory (None until a /council run lands) → else engine directive
        verdict_txt, vcol, verdict = str(b.get("directive", "—")), SILVER, None
        contested = False
        mem = self._memory()
        if mem is not None:
            try:
                verdict = mem.latest(ticker=tk, type="council_verdict")
            except Exception:
                verdict = None
            if verdict:
                meta = verdict.get("meta", {}) or {}
                conv = meta.get("convergence", {}) or {}
                contested = bool(conv.get("contested"))
                verdict_txt = f"{meta.get('stance','')} · {conv.get('bull','?')}/{conv.get('bear','?')}"
                vcol = ORANGE if contested else GREEN

        caret = "hide debate ⌃" if self._council_open else "full debate ⌄"
        badge = f"  [{ORANGE}]⚖ contested[/]" if contested else ""
        out = [
            f"[b {GOLD}]⚖ COUNCIL[/] [b white]{self._esc(tk)}[/] [{hc}]{_fmt(rating)}/10[/]"
            f"  [{vcol}]{self._esc(verdict_txt)}[/]{badge}"
            f"   [@click=app.toggle_council][{TEAL}]{caret}[/][/]",
            f"[@click=app.explain('phi')][{DIM}]φ[/] {g(V.get('floor_coverage'))}[/]  "
            f"[@click=app.explain('rho')][{DIM}]ρ[/] {g(V.get('rho'))}[/]  "
            f"[@click=app.explain('upside')][{DIM}]upside[/] {g(V.get('upside_pct'),'{:.0f}%')}[/]  "
            f"[{DIM}]invalidation[/] [{RED}]{_money(L.get('floor'))}[/]   [{DIM}]regime composes posture[/]",
        ]
        if not self._council_open:
            out.append(rule)
            return out

        # ── expanded: the full debate (formerly the Council tab), inline above the chat ──
        out.append(rule)
        out.append(f"[bold {GREEN}]BULL — asymmetry (engine-grounded)[/]")
        out.append(f"  φ floor-coverage [{GREEN if (_num(V.get('floor_coverage')) or 0) >= 1 else SILVER}]"
                   f"{g(V.get('floor_coverage'))}[/]   ρ payoff [{SILVER}]{g(V.get('rho'))}[/]"
                   f"   upside [{SILVER}]{g(V.get('upside_pct'),'{:.0f}%')}[/]")
        out.append(f"  tailwind [{SILVER}]{g(T.get('score'),'{:.1f}')}[/] [{DIM}]({self._esc(str(T.get('commodity','—')))})[/]"
                   f"   ladder [{DIM}]floor[/] {_money(L.get('floor'))} [{DIM}]· base[/] "
                   f"{_money(L.get('base'))} [{DIM}]· bull[/] {_money(L.get('bull'))}")
        out.append("")
        out.append(f"[bold {RED}]BEAR + LIQUIDITY SENTINEL — invalidation[/]")
        out.append(f"  hard invalidation [{RED}]{_money(L.get('floor'))}[/] [{DIM}](floor leg)[/]")
        gcap = gate.get("cap")
        cap_str = "" if gcap is None else f" — cap {g(gcap, '{:.1f}')}"
        if gate.get("applied"):
            out.append(f"  [{ORANGE}]⚠ forensic gate active{cap_str}: {self._esc(str(gate.get('reason',''))[:40])}[/]")
        else:
            out.append(f"  [{DIM}]forensic gate clear (JSF){cap_str} · dilution / liquidity / exit-friction "
                       f"surface on a live /council run[/]")
        out.append(rule)
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
                           f"{posture['cap']:g}x[/]")
            out.append(f"  [{DIM}]No Council verdict yet — run[/] [{TEAL}]/council {self._esc(tk)}[/] "
                       f"[{DIM}]to convene the full debate.[/]")
        # action buttons — they post into THIS shared conversation (the merge: book + council = one chat)
        out.append(f"  [@click=app.council_ask('rerun')][{GOLD} on #141418] ↻ Re-run with memory [/]   "
                   f"[@click=app.council_ask('save')][{SILVER} on #141418] ⇪ Save as prior [/]   "
                   f"[@click=app.council_ask('outcomes')][{TEAL} on #141418] ⊹ Pull outcomes [/]")
        # the name's LIVING research thread (notes / verdicts / outcomes) — type "note: …" to add one
        if mem is not None:
            try:
                thread = [e for e in mem.query(ticker=tk, limit=8)
                          if e.get("type") != "pin" and not (e.get("meta") or {}).get("retracted")][:6]
            except Exception:
                thread = []
            out.append(rule)
            out.append(f"[bold {TEAL}]RESEARCH THREAD[/]  [{DIM}]living memory[/]")
            if thread:
                glyphs = {"note": "✎", "council_verdict": "⚖", "thesis": "◆", "scenario_prior": "⊹",
                          "outcome": "✓", "regime_snapshot": "◷", "decision": "▸", "catalyst": "⛏",
                          "thread": "↯", "pin": "📌"}
                for e in thread:
                    gl = glyphs.get(e.get("type"), "·")
                    when = str(e.get("ts", ""))[:10]
                    out.append(f"  [{DIM}]{when}[/] {gl} [{SILVER}]{self._esc(str(e.get('text',''))[:54])}[/]"
                               f"  [{DIM}]{self._esc(str(e.get('source','')))}[/]")
            else:
                out.append(f"  [{DIM}]empty — type[/] [{TEAL}]note: <your observation>[/] "
                           f"[{DIM}]to start this name's thread.[/]")
        out.append(rule)
        return out

    def action_toggle_council(self) -> None:
        """Expand / collapse the inline Council debate on the Book page — no tab switch."""
        self._council_open = not self._council_open
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
            if self._council_open:
                self.query_one("#spine", VerticalScroll).scroll_home(animate=False)
        except Exception:
            pass

    def action_council_ask(self, kind: str) -> None:
        """The Council action buttons route into the shared conversation (one chat for book+council)."""
        tk = self._focus or ""
        text = {"rerun": f"re-run the council on {tk} with latest memory",
                "save": f"save the council verdict on {tk} as a scenario prior",
                "outcomes": f"pull related outcomes for {tk}"}.get(kind)
        if text:
            self._ask_agent(text)

    def action_go_council(self) -> None:
        """Convene the Council — expands the debate INLINE on the Book page (the shared chat),
        rather than opening a separate tab."""
        self._council_open = True
        self.action_tab("book")
        try:
            self.query_one("#agent_reply", Static).update(self._conversation_markup())
            self.query_one("#spine", VerticalScroll).scroll_home(animate=False)
        except Exception:
            pass

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
            self.query_one("#cmdbar", Input).value = ""
            self.set_focus(None)            # blur → app-level single-key binds (q/w/e/d/g) fire again
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

    def _show_whatif(self, res: dict, overrides: str, record: bool = True) -> None:
        out = self.query_one("#wf_result", Static)
        if not res or res.get("error"):
            out.update(Text(f"⚠ {res.get('error','no result') if res else 'no result'}", style=ORANGE))
            return
        base, scen, delta = res.get("base", {}), res.get("scenario", {}), res.get("delta", {})
        tk = res.get("ticker", "?")
        bi, si = _num(base.get("intrinsic")), _num(scen.get("intrinsic"))
        price = _num(res.get("price"))
        dp = _num(delta.get("intrinsic_pct"))
        # remember this run so it can be pinned as the A/B baseline (and re-rendered on pin/unpin)
        self._wf_last = {"overrides": overrides, "intrinsic": si,
                         "upside_pct": _num(scen.get("upside_pct")), "ticker": tk}
        self._wf_last_res = (res, overrides)

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

        # A/B: pin a scenario as baseline A, step knobs to B, see B vs A (not just vs base)
        ab = Text()
        pin = self._wf_pinned
        if pin and _num(pin.get("intrinsic")):
            pa = _num(pin["intrinsic"])
            dA = ((si - pa) / pa * 100.0) if (si is not None and pa) else None
            su, pu = _num(scen.get("upside_pct")), _num(pin.get("upside_pct"))
            ab.append("\nA/B  ", style=f"bold {AMBER}")
            ab.append(f"vs A [{pin.get('overrides') or '(base)'}]  ", style=DIM)
            ab.append(f"Δ {_fmt(dA)}%", style=(GREEN if (dA or 0) >= 0 else RED))
            ab.append_text(_delta_bar(dA, 15))
            if su is not None and pu is not None:
                ab.append(f"   Δ upside {su - pu:+.1f}pp", style=SILVER)
            ab.append("   ")
            ab.append("✕ unpin", style=Style.parse(DIM) + Style(meta={"@click": "app.wf_unpin"}))
        else:
            ab.append("\n")
            ab.append("⊹ pin this as A/B baseline", style=Style.parse(TEAL) + Style(meta={"@click": "app.wf_pin"}))

        bar, legend = _ladder([("F", (base.get("legs") or {}).get("cost"), ORANGE),
                               ("●", price, "white"),
                               ("◆", bi, GOLD),
                               ("✦", si, GREEN)])
        ladder = Group(Text("\nvalue ladder  (F floor · ● price · ◆ base intrinsic · ✦ scenario)", style=DIM),
                       bar, legend)

        groups = [head, applied, cols, dl] + ([legs_txt] if legs_txt else []) + [ab, ladder]
        # the agent-proposed scenario narrative — effects beyond the 7 knobs (shown only for its own run)
        if self._wf_scenario_brief and overrides == self._wf_scenario_ov:
            sc = Text("\n\nSCENARIO  ", style=f"bold {TEAL}")
            sc.append("agent-proposed · effects beyond the knobs\n", style=DIM)
            sc.append(self._wf_scenario_brief, style=SILVER)
            groups.append(sc)
        out.update(Group(*groups))
        if record:
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

    def action_wf_pin(self) -> None:
        """Pin the current what-if result as the A/B baseline (scenario A) — runs then show Δ vs A,
        so you can pin a thesis, step the knobs to a variant, and read the difference directly."""
        if not self._wf_last or self._wf_last.get("intrinsic") is None:
            self._toast("run a what-if first, then pin it as A", ORANGE); return
        self._wf_pinned = dict(self._wf_last)
        self._toast(f"⊹ pinned A: {self._wf_pinned.get('overrides') or '(base)'} — runs now show Δ vs A", TEAL)
        if self._wf_last_res:
            self._show_whatif(self._wf_last_res[0], self._wf_last_res[1], record=False)

    def action_wf_unpin(self) -> None:
        self._wf_pinned = None
        self._toast("unpinned A/B baseline", DIM)
        if self._wf_last_res:
            self._show_whatif(self._wf_last_res[0], self._wf_last_res[1], record=False)

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
        if ok:
            self.call_from_thread(self._receipt, f"scenario '{name}'", "⇪", AMBER)
        self.refresh_data()

    @work(thread=True, group="confirm")
    def _do_confirm(self, pid) -> None:
        res = _post("/config/confirm", {"id": pid, "source": "cockpit"})
        ok = res.get("ok")
        self.call_from_thread(self._status,
                              Text((f"confirmed #{pid}" if ok else f"confirm failed: {res.get('error')}"),
                                   style=(GREEN if ok else ORANGE)))
        if ok:                                         # engine-applied — receipt records it (no undo)
            self.call_from_thread(self._receipt, f"applied proposal #{pid}", "✓", GREEN)
        self.refresh_data()

    @work(thread=True, group="reject")
    def _do_reject(self, pid) -> None:
        _post("/config/reject", {"id": pid})
        self.call_from_thread(self._receipt, f"rejected proposal #{pid}", "✗", ORANGE)
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
            if rest:
                self._set_focus(rest[0].upper(), move_cursor=True)
            self.action_go_council()                      # expand the debate inline on the Book page
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
