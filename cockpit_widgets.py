#!/usr/bin/env python3
"""
cockpit_widgets.py — the cockpit's shared visual vocabulary + modal screens.

Split out of ``commodityex_tui.py`` (which keeps the ``Cockpit`` App orchestrator — and with it
``CSS_PATH``/``cockpit.tcss`` resolution). This module holds everything *below* the App:

- the engine transport (``_get``/``_post``) and the amber/silver/gold palette constants,
- the pure formatting helpers (``_bar``/``_rating``/``_ladder`` … rich-only, unit-testable),
- ``METRIC_HELP`` + the hub/blend constant tables (HUB_*, BLEND_*, JOBNAV_*),
- the modal screens: ``InspectScreen`` · ``ChangeReviewScreen`` · ``ChatInput`` ·
  ``PaletteScreen`` · ``HubScreen``.

No import of ``commodityex_tui`` (or ``cockpit_surfaces``) at module level — screens reach the
running App only via ``self.app`` at runtime, so the dependency graph stays a clean DAG:
``cockpit_widgets`` ← ``cockpit_surfaces`` ← ``commodityex_tui``.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                                  # health/score -> colour (shared visual language)
    from conviction_health import health_color
except Exception:                                     # pragma: no cover - graceful if module moves
    def health_color(_): return "#C0C0C8"

from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from hub_gist import is_run_expanded   # pure hub helper (testable sans textual)

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
TEAL   = "#6FA8A6"   # research accent
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
# docs/archive/tmux-textual-theme.md. Solid █ fill over a hairline track for the hero card;
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


def _arch_short(archetype, code=None, subarchetype=None):
    # context-aware: a project-generator / royalty-generator HOLDCO is valued via asset_light_yield but
    # it is NOT a royalty — its value is NAV + discovery optionality. Show it as a holdco, not "ROYALTY".
    sub = str(subarchetype or "").lower()
    if "holdco" in sub or "generator" in sub:
        return "HOLDCO"
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


def _native_ladder(basket):
    """The basket's price ladder in its NATIVE display currency, plus a currency suffix.

    Every valuation leg (price/floor/base/bull) reaches the cockpit CAD-normalized for the blended-
    book math, but each name is shown beside its native-currency fundamentals (FMP 52-wk range,
    mcap). Mixing them made a USD name read price $2.88 (USD) next to floor $4.38 (CAD) — a
    contradiction, even though φ/upside (ratios) were right. The engine attaches ``ladder_native``
    (the same CAD legs ÷ the fx used) for non-CAD names so the absolute points reconcile with both
    the native fundamentals and the ratios. CAD names use the CAD ladder unchanged.

    Returns (ladder, ccy_suffix) — suffix e.g. ' USD' for a non-CAD name, else ''."""
    if not isinstance(basket, dict):
        return {}, ""
    ccy = str(basket.get("display_ccy") or "").upper()
    nat = basket.get("ladder_native")
    if isinstance(nat, dict) and nat:
        return nat, (f" {ccy}" if ccy and ccy != "CAD" else "")
    return (basket.get("ladder") or {}), ""


def _disp_price(basket, node=None):
    """The name's last price in the SAME native currency as ``_native_ladder`` — so the price, the
    floor, and the ladder dot all reconcile with the displayed φ/upside. Prefers the native ladder
    price; falls back to the live node price (CAD names: identical) then the CAD ladder price."""
    lad, _sfx = _native_ladder(basket)
    p = _num(lad.get("price"))
    if p is None and isinstance(node, dict):
        p = _num(node.get("price"))
    if p is None:
        p = _num((basket.get("ladder") or {}).get("price")) if isinstance(basket, dict) else None
    return p


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
        lad, _sfx = _native_ladder(basket)
        fl = _num(lad.get("floor"))
        if fl is not None:
            return Text(_money(fl), style=SILVER)
    if dtf is None:
        return Text("—", style=DIM) if phi is None else Text(f"φ{phi:.2f}", style=SILVER)
    style = GREEN if dtf <= 15 else (AMBER if dtf <= 35 else ORANGE)
    return Text(f"-{dtf:.0f}%", style=style)


def _directive_action(directive) -> tuple[str, str]:
    """Compact, colour-coded ACTION token from the engine's directive string. The rail shows the
    RATING (conviction: T·Q·V) and this shows the STANCE — and the two are orthogonal by design: a
    cheap name trading below its REP floor is ACCUMULATE even at a *lower* rating, while a name sitting
    at fair value is HOLD even at a *higher* one. So 6.8/ACCUM next to 6.9/HOLD is correct, not a bug —
    this token makes that legible at a glance instead of hiding it in the detail card. Pure; the verbs
    mirror asymmetry_rating._directive. Returns (token, colour)."""
    d = str(directive or "").upper()
    if "ACCUMULATE" in d:                                  # BELOW FLOOR / BELOW FAIR VALUE — accumulate
        return ("ACCUM", GREEN)
    if "FORENSIC" in d or "AVOID" in d or "DE-RISK" in d:  # severe forensic / de-risk
        return ("AVOID", RED)
    if "TRIM" in d:                                        # RICH — TRIM / UPSIDE SPENT — HOLD / TRIM
        return ("TRIM", ORANGE)
    if "VERIFY" in d:                                      # BELOW PROXY FLOOR — verify before adding
        return ("VERIFY", AMBER)
    if "STAND ASIDE" in d:                                 # WEAK SETUP — stand aside
        return ("STAND", DIM)
    if "WATCH" in d:                                       # STRONG ASYMMETRY — watch closely
        return ("WATCH", AMBER)
    if "MONITOR" in d:                                     # THESIS INTACT — monitor
        return ("MON", SILVER)
    if "HOLD" in d:                                        # QUALITY — CORE HOLD / FAIR VALUE — HOLD
        return ("HOLD", SILVER)
    tail = d.split("—")[-1].strip()
    return (tail[:5], DIM) if tail else ("—", DIM)


def _clean_convo_title(raw: str, words: int = 9) -> str:
    """A Claude-'Recents'-style title from a conversation's opening message: drop a leading slash-command
    or @agent sigil (chrome, not title), keep the first few words, sentence-case it. Pure.
    '/promote to eval OGN.V' → 'Promote to eval OGN.V'; '@synthesis deep-dive…' → 'Synthesis deep-dive…'."""
    s = " ".join(str(raw or "").split())
    if not s:
        return ""
    if s[0] in "/@":                                   # a command / agent sigil reads as chrome
        s = s[1:].lstrip()
    s = " ".join(s.split()[:max(1, int(words))]).strip(" -–—·:")
    return (s[:1].upper() + s[1:]) if s else ""


#: Concise hover help per clickable-metric key (the @click=app.explain('KEY') targets), so every metric
#: is self-describing on HOVER, not only on click. A pure map — unit-tested, no engine dependency.
METRIC_HELP = {
    "rating": "Conviction rating 0–10 — the blended T·Q·V score.",
    "T": "T · Macro Tailwind — the regime / commodity wind at the name's back.",
    "Q": "Q · Quality — management, balance-sheet integrity, execution.",
    "V": "V · Valuation Asymmetry — upside vs the REP-floor downside.",
    "rho": "ρ · Payoff ratio — upside ÷ downside-to-floor (>1 = asymmetric).",
    "phi": "φ · Floor coverage — price vs the REP floor (≥1 = under liquidation).",
    "floor": "REP floor — the asset-backed margin-of-safety price.",
    "upside": "Upside — % to the bull-case valuation leg.",
    "gate": "JSF forensic gate — accounting-integrity cap on conviction.",
    "band": "Conviction band — the directive bucket for this rating.",
    "directive": "Directive — the engine's stance (accumulate / hold / trim …).",
    "mri": "MRI · Macro Regime Index — the book-level regime temperature.",
    "posture": "Regime posture — the size dial (exploit / balanced / defensive).",
}

_EXPLAIN_META_RE = re.compile(r"app\.explain\(\s*['\"]([^'\"]+)['\"]")


def metric_hover_help(click_action):
    """Hover help for a clickable metric: parse a ``@click=app.explain('KEY'…)`` action string and return
    a concise one-liner from METRIC_HELP. None for a non-metric clickable (so ONLY metrics get a tooltip).
    Pure — drives the on-hover explanation without re-instrumenting every metric span."""
    if not isinstance(click_action, str) or "explain(" not in click_action:
        return None
    m = _EXPLAIN_META_RE.search(click_action)
    return METRIC_HELP.get(m.group(1)) if m else None


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



def _provenance_tell(basket):
    """Glance-level provenance tells for a holding row (2026-07-02 reassessment finding #2: the engine
    computes ``floor_degraded`` / ``quality_proxy_only`` on every rating and the cockpit rendered
    NEITHER — a proxy/unsourced floor looked identical to a sourced one, a market-confidence-proxy Q
    identical to an earned one, exactly the OGN.V mislead these flags exist to prevent). A margin-of-
    safety cockpit that hides when the margin is a guess mis-sells its core promise. Pure → the rail is
    a thin consumer; returns the marker text (or "") plus the raw booleans for styling decisions."""
    b = basket or {}
    fd = bool(b.get("floor_degraded"))
    qp = bool(b.get("quality_proxy_only"))
    return {"floor_marker": " ~proxy" if fd else "",
            "q_marker": " Q~proxy" if qp else "",
            "floor_degraded": fd, "quality_proxy_only": qp}


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


def _stream_lines(stream, on_update, *, throttle_s: float = 0.25, clock=time.monotonic) -> str:
    """Read a text stream line-by-line as it lands, accumulating, and call ``on_update(full_text,
    n_lines)`` at most every ``throttle_s`` (plus once at EOF) — the H1 live-tape mechanism. Uses
    ``readline()`` (not iteration) to dodge Python's read-ahead buffering, so a flushing child shows
    its reasoning progressively instead of all at once. Pure I/O over the stream — tested with any
    object exposing ``readline()`` (a real pipe, a StringIO). Returns the full accumulated text."""
    buf: list = []
    last = 0.0
    while True:
        try:
            line = stream.readline()
        except (ValueError, OSError):                      # stream closed mid-read (kill/cancel)
            break
        if not line:
            break
        buf.append(line)
        now = clock()
        if now - last >= throttle_s:
            last = now
            try:
                on_update("".join(buf), len(buf))
            except Exception:
                pass
    full = "".join(buf)
    try:
        on_update(full, len(buf))                          # final flush so the last lines always land
    except Exception:
        pass
    return full


def _readline_iter(stream):
    """Yield a stream's lines via ``readline()`` (no read-ahead buffering — the live-tape requirement),
    stopping cleanly when the stream closes (kill/cancel). Feeds ``reduce_stream_json`` the same way
    ``_stream_lines`` consumes a pipe."""
    while True:
        try:
            line = stream.readline()
        except (ValueError, OSError):                      # stream closed mid-read
            break
        if not line:
            break
        yield line


def _parse_workflow_signals(text: str) -> dict:
    """Pull the structured signals a workflow gate keys off from a stage's accumulated output —
    the verdict tokens (APPROVE / CONDITIONAL / REJECT) and the first JSF score. Best-effort and
    text-based (the agents write prose); absence is reported honestly, never guessed."""
    import re
    up = str(text or "").upper()
    verdicts = [v for v in ("APPROVE", "CONDITIONAL", "REJECT") if v in up]
    jsf = None
    m = re.search(r"JSF[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)", up)
    if m:
        try:
            jsf = float(m.group(1))
        except ValueError:
            jsf = None
    return {"verdicts": verdicts, "jsf": jsf}


def _eval_workflow_gate(gate: dict, text: str) -> tuple:
    """Evaluate ONE conditional-workflow gate against the prior stages' output. Returns
    ``(passed: bool, reason: str)``. Vocabulary (declarative, on ``gate['require']``):
      • ``any_approve`` — at least one APPROVE verdict upstream.
      • ``no_reject``   — no REJECT verdict upstream.
      • ``jsf_at_least`` / ``jsf_below`` (+ ``value``) — the parsed JSF clears / breaks the bar.
      • ``contains`` / ``not_contains`` (+ ``value``) — a phrase is / isn't present.
    Honest defaults: a numeric gate whose signal is ABSENT does not silently halt — it passes with a
    'signal not found' reason (``on_missing='halt'`` flips that). An unknown predicate passes (a
    typo'd gate must never wedge a chain). The caller halts the chain when ``passed`` is False."""
    if not isinstance(gate, dict) or not gate.get("require"):
        return True, "no gate"
    sig = _parse_workflow_signals(text)
    req = str(gate.get("require")).strip().lower()
    val = gate.get("value")
    miss_halts = str(gate.get("on_missing", "pass")).lower() == "halt"

    if req == "any_approve":
        ok = "APPROVE" in sig["verdicts"]
        return ok, ("an APPROVE verdict cleared the gate" if ok
                    else "no APPROVE upstream — nothing advanced")
    if req == "no_reject":
        ok = "REJECT" not in sig["verdicts"]
        return ok, ("no REJECT — clear" if ok else "a REJECT verdict halts the chain")
    if req in ("jsf_at_least", "jsf_below"):
        thr = None
        try:
            thr = float(val)
        except (TypeError, ValueError):
            return True, "gate has no numeric threshold — skipped"
        if sig["jsf"] is None:
            return (not miss_halts), f"JSF not found in the output ({'halt' if miss_halts else 'pass'} on missing)"
        if req == "jsf_at_least":
            ok = sig["jsf"] >= thr
            return ok, f"JSF {sig['jsf']:g} {'≥' if ok else '<'} {thr:g}"
        ok = sig["jsf"] < thr
        return ok, f"JSF {sig['jsf']:g} {'<' if ok else '≥'} {thr:g}"
    if req in ("contains", "not_contains"):
        needle = str(val or "").upper()
        present = needle in str(text or "").upper()
        ok = present if req == "contains" else (not present)
        return ok, f"{'found' if present else 'absent'}: {val!r}"
    return True, f"unknown gate {req!r} — passed (never wedge a chain on a typo)"


# ── Agent Hub — the fleet, Forge-layer aligned (handoff: docs/archive/design_handoff_agent_hub) ──
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
]

# id → (group, runtime lane, default status, can[] verbs). The Sentinel is a MODULE (sentinel.py),
# not a .claude subagent — it leads the roster.
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
}
HUB_VERBS = ["ask", "explain", "sweep", "swap", "catalyst", "rule", "claim", "red-team",
             "verify", "compare", "scout", "audit", "council", "calibrate", "bias-scan"]
HUB_LEDGER_VERBS = {"claim", "rule"}   # file to the Thesis Ledger — parsed/validated at save, no scheduler

# Per-agent provider + model. Every seat runs the Claude CLI (`claude -p "@agent …"`; the model is
# pinned in the agent's .claude/agents/*.md AND ridden as a --model flag on headless spawns). The
# Gemini (agy) lane is RETIRED — subscription cancelled 2026-07 — its seats (scout,
# catalyst-verifier, the antigravity outside red-team) moved to Claude; the independent-foil role
# folds into @bear.
# Rationale (Claude Max → opus where reasoning matters; sonnet where speed does):
#   opus   — deep judgment: the Council (arbiter/bull/bear), value, balance-sheet, synthesis, the
#            forensic gate (verifier), conviction explanations. PINNED to Opus 4.8 via
#            CLAUDE_MODEL_IDS — the desk does NOT ride the alias up to Opus 5.
#   sonnet — speed-sensitive periodic / rules / structured / data-aggregation work: the Sentinel
#            sweep, calibration, the data-integrity audit, scout, catalyst-verifier. The bare
#            alias resolves to Sonnet 5 — approved. (Never haiku — opus or sonnet only.)
HUB_AGENT_MODEL = {
    "sentinel":               ("claude", "sonnet"),
    "arbiter":                ("claude", "opus"),
    "bull":                   ("claude", "opus"),
    "bear":                   ("claude", "opus"),
    "scout":                  ("claude", "sonnet"),
    "value-analyst":          ("claude", "opus"),
    "balance-sheet-analyst":  ("claude", "opus"),
    "synthesis":              ("claude", "opus"),
    "verifier":               ("claude", "opus"),
    "calibration":            ("claude", "sonnet"),
    "catalyst-verifier":      ("claude", "sonnet"),
    "data-integrity-auditor": ("claude", "sonnet"),
    "conviction-analyst":     ("claude", "opus"),
}
_MODEL_COLORS = {"opus": AMBER_BRIGHT, "sonnet": SILVER, "gemini-flash": TEAL}

# Registry tier labels are DISPLAY names; the claude CLI gets an explicit ID where the bare alias
# would drift. Operator directive (2026-07-28, post Claude-5 launch): the terminal STAYS on
# Opus 4.8 — never let `opus` float up to Opus 5. `sonnet` deliberately rides the alias
# (currently Sonnet 5 — approved).
CLAUDE_MODEL_IDS = {"opus": "claude-opus-4-8"}


def _model_cli_id(label):
    """Registry tier label → the model id passed to the claude CLI's --model flag."""
    return CLAUDE_MODEL_IDS.get(str(label or ""), label)


def _agent_model(agent_id: str):
    """(provider, model) for an agent — the registry, default claude/sonnet."""
    return HUB_AGENT_MODEL.get(agent_id, ("claude", "sonnet"))


def _model_chip(agent_id: str) -> str:
    """A small model badge for the roster/inspector (now the fleet is mixed, the model matters)."""
    _prov, model = _agent_model(agent_id)
    return f"[{_MODEL_COLORS.get(model, SILVER)}]◇{model}[/]"


def _run_model_label(agent: str, provider: str) -> str:
    """The model a run is ACTUALLY on. The fleet is all-Claude since the Gemini lane retired —
    only a HISTORICAL run record can still carry provider='gemini', and it stays honest."""
    if provider == "gemini":
        return "gemini-flash"
    prov, model = _agent_model(agent)
    return model if prov == "claude" else "sonnet"


# ── The operator's command manual (the `m` quick-look) — every wired verb, grouped by job. ──
# Grounded in _run_command's dispatcher + the .claude/commands skills + scripts/bootstrap; if a verb
# isn't wired, it doesn't belong here (the glossary must never advertise a command that won't run).
COMMAND_GLOSSARY = (
    ("BOOK & VIEWS", (
        ("/focus TK  (f)", "land the cockpit on a name — 'this' in chat then means TK"),
        ("/profile   (prof)", "open the focused name's dossier/profile view"),
        ("/dossier TK", "render TK's research dossier"),
        ("/tab id", "jump to a view: book · council · whatif · regime · dossier"),
        ("/refresh   (r)", "re-pull engine state now"),
        ("keys: w/e/d/g/h", "What-If · Council · Detail · Book grid · Hub"),
    )),
    ("VALUATION & SCENARIOS", (
        ("/whatif TK silver=+8 ry=-0.5", "revalue TK under macro/peer overrides — runs visibly in the What-If lens"),
        ("/scenario name", "load a saved scenario"),
        ("/save name", "save the current what-if as a named scenario"),
        ("/explain TK  (decouple)", "explain today's move — factor vs idiosyncratic"),
    )),
    ("RESEARCH & AGENTS", (
        ("/council TK  (debate)", "Dialectic Council: bull → bear → arbiter → ONE verdict, written to Memory"),
        ("/pipeline theme", "headless scout → synthesis → verifier chain; watch the PIPELINE canvas"),
        ("/scout theme", "scout alone — grounded finds feed the universe via add_candidate"),
        ("/note text…", "persist a typed research note to Living Memory (regime-stamped)"),
        ("@agent question", "ask any seat directly: @bear, @value-analyst, @catalyst-verifier, …"),
        ("plain text", "no verb needed — the router reads intent and picks the seat"),
    )),
    ("DISCOVERY FUNNEL (find → vet → rate)", (
        ("/screen slot", "slot-fit-first hard gates over the universe (silver · gold · holdco · uranium · ⟂)"),
        ("/replace TK", "whole rotation flow from a held name: slot → screen → rank → /rotate"),
        ("/gauntlet TK  (vet)", "verifier + anti-scout + forensic receipts, then graduate — the disconfirmation gate"),
        ("/rotate INC CHL  (swap)", "rotation gate: slot-fit first, then friction-adjusted ρ-edge → SWAP/REJECT/DEFER"),
    )),
    ("GOVERNANCE (nothing moves the book on its own)", (
        ("/confirm id  (c)", "apply an agent-proposed param change — the human gate"),
        ("/reject id", "refuse a pending proposal"),
        ("/change cut TK · rotate OUT IN · reweight TK=.6", "stage a book diff for review"),
    )),
    ("OPERATOR SCRIPTS (shell, from repo root)", (
        ("./cockpit.sh", "launch everything: engine + TUI + agent panes (kill · --focus · --desk)"),
        ("python scripts/bootstrap/backfill_price_history.py", "backfill the price cache so ρ/replay grade on real history"),
        ("python ingestion_pipeline.py --force", "force a live data re-ingest (fixes stale marks)"),
        ("python scripts/bootstrap/seed_living_memory.py", "re-index data/decisions/*.md into Living Memory"),
    )),
)

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

# ══════════════════════════════════════════════════════════════════════════════════════
#  Agent Hub v2 — "THE BLEND" (spec: Agent Hub — Build Plan · wf/blend*.jsx · tmux-honest)
#
#  One surface, five strengths, no clutter. The QUEST LOG is home — a live feed of past
#  and current research events. Everything else opens out of it and closes back into it:
#  LAUNCH (left rail — target + chains + 1v1, launching is a verb), the WORKING LANE
#  (right rail — every in-flight run, AUTO/MANUAL tagged, model on each), focus surfaces
#  (Pipeline / Matchup / Thread / Compare as modals), the ROSTER drawer, and an ambient
#  read-only CONCIERGE docked on every hub screen.
#
#  Terminal re-encoding of the HTML mock: hierarchy = color + bold + UPPERCASE + space
#  (one cell size); live = amber border + ~2 Hz pulse (no glow exists in a cell grid);
#  graph edges are hand-painted box glyphs (Textual routes nothing). Every action ships
#  BOTH a clickable affordance and a key — the key is the accelerator, the click is the
#  floor (the interaction-matrix review gate).
# ══════════════════════════════════════════════════════════════════════════════════════
CONCIERGE_C = "#8B90C8"   # the Concierge's own quiet periwinkle-slate — never agent chrome

BLEND_FILTERS = (("all", "ALL"), ("working", "WORKING"), ("flagged", "FLAGGED"), ("matchups", "MATCHUPS"))

# The top navigation bar (the wireframe's approach-tab strip): THE BLEND is the unified hub; the
# lettered tabs A–E open ONE focused feature full-screen. (key, badge, name, tagline) — keys 1-6.
# Tabs SET UP, they never fire; quick execution stays on the Launch rail.
# Taglines are deliberately terse: the whole 7-tab strip must fit the surface box's 150-col
# max-width or the rightmost tabs silently clip off the edge (test_predict_desk pins the budget).
BLEND_NAV = (
    ("blend",    "★", "THE BLEND",      "the hub"),
    ("quest",    "A", "QUEST LOG",      "the feed"),
    ("pipeline", "B", "PIPELINE CANVAS", "chains, not boxes"),
    ("matchup",  "C", "MATCHUP DESK",   "hold vs bench"),
    ("roster",   "D", "ROSTER TRIAGE",  "the fleet learns"),
    ("thread",   "E", "THREAD MAP",     "threads that flow"),
    ("predict",  "F", "PREDICT DESK",   "arb, net of fees"),
)


def _blend_nav_markup(active: str):
    """The persistent top bar, two aligned rows (name over tagline) like the wireframe: the hero
    ★ THE BLEND, then A–E focused features. The active tab's badge fills amber; whole cell clicks;
    keys 1-6 mirror. Returns a Rich Group of two Text lines."""
    names, tags = Text(), Text()
    for i, (key, badge, name, tag) in enumerate(BLEND_NAV, 1):
        on = (key == active)
        cellw = max(len(name) + 4, len(tag) + 4) + 3
        click = f"@click=app.blend_nav('{key}')"
        bchip = ("bold #08080A on " + AMBER) if on else ("bold " + AMBER + " on #141418")
        nm = (f"[{click}][{bchip}] {badge} [/] "
              f"[{'bold ' + GOLD if on else DIM}]{name}[/][/]")
        names.append_text(Text.from_markup(nm + " " * (cellw - (len(name) + 4))))
        tg = f"[{click}]    [{AMBER if on else FAINT}]{tag}[/][/]"
        tags.append_text(Text.from_markup(tg + " " * (cellw - (len(tag) + 4))))
    return Group(names, tags)


# The three-JOB nav (the reframe): Watch · Screen · Change up front by rising consequence, then the
# old mechanism tabs demoted to drawers (log / fleet / concierge). Whole cells click → app.jobnav.
JOBNAV_JOBS = (("watch",  "◆", "WATCH",  GREEN, "the book · glance & go"),
               ("screen", "▲", "SCREEN", AMBER, "the kill-funnel"),
               ("change", "⇄", "CHANGE", RED,   "the book diff"))
JOBNAV_DRAWERS = (("log", "log ›"), ("fleet", "fleet ›"), ("predict", "predict ›"),
                  ("concierge", "concierge ›"))


def _jobnav_markup():
    """The hub's primary nav, re-cast around the operator's three JOBS (rising consequence) instead
    of the machine's mechanisms — which become drawers, not deletions. Two rows (name over tag) to
    fit the nav band; whole cells click via app.jobnav(...). Keys 1-6 still reach the demoted
    surfaces, so nothing is lost."""
    names, tags = Text(), Text()
    for key, glyph, name, col, tag in JOBNAV_JOBS:
        click = f"@click=app.jobnav('{key}')"
        cell = max(len(name) + 5, len(tag)) + 4
        names.append_text(Text.from_markup(
            f"[{click}][bold #08080A on {col}] {glyph} [/] [bold {col}]{name}[/][/]"))
        names.append(" " * max(1, cell - (len(name) + 5)))
        tags.append_text(Text.from_markup(f"[{click}]    [{FAINT}]{tag}[/][/]"))
        tags.append(" " * max(1, cell - (len(tag) + 4)))
    names.append_text(Text.from_markup(f"[{DIM}]│[/]  "))
    tags.append("    ")
    for key, lbl in JOBNAV_DRAWERS:
        names.append_text(Text.from_markup(f"[@click=app.jobnav('{key}')][{DIM}]{lbl}[/][/]  "))
        tags.append(" " * (len(lbl) + 2))
    return Group(names, tags)

# Saved chains seeded on first run (through the existing workflow store, so the operator's own
# saved chains appear as Launch buttons right alongside these).
BLEND_SEED_WORKFLOWS = {
    "deep dossier": [
        {"agents": ["scout"], "note": "ground the name: what it is, stage, jurisdiction, portfolio fit"},
        {"agents": ["value-analyst", "balance-sheet-analyst"],
         "note": "value it (REP floor, fair-value range) ∥ survivability (runway, dilution, JSF)"},
        {"agents": ["verifier"], "note": "forensic gate: verify every claim above; downgrade or reject"},
        {"agents": ["synthesis"], "note": "package the chain into one dossier"},
    ],
    "quick red-team": [
        {"agents": ["bear"], "note": "independent red-team — what breaks this?"},
        {"agents": ["arbiter"], "note": "reconcile the red-team into one verdict + the invalidation level"},
    ],
    "convene council": [
        {"agents": ["bull", "bear"], "note": "argue it — strongest long case vs the invalidation case"},
        {"agents": ["arbiter"], "note": "one reconciled verdict; dissent survives as a flagged caveat"},
    ],
    # a CONDITIONAL chain (H2): each later stage carries a GATE checked against the prior output, so
    # the pipeline aborts early and cheaply instead of running every stage regardless.
    "gated dossier": [
        {"agents": ["scout"], "note": "ground the name; END with an explicit APPROVE / CONDITIONAL / "
         "REJECT on slot-fit + asymmetry"},
        {"agents": ["value-analyst", "balance-sheet-analyst"],
         "note": "value it (REP floor, fair-value) ∥ survivability — STATE the JSF score explicitly",
         "gate": {"require": "any_approve"}},          # only value a name the scout advanced
        {"agents": ["verifier"], "note": "forensic gate: verify every claim; end with a verdict",
         "gate": {"require": "jsf_at_least", "value": 3.5}},   # only verify a name that can survive
        {"agents": ["synthesis"], "note": "package the chain into one dossier",
         "gate": {"require": "no_reject"}},            # a REJECT upstream halts before packaging
    ],
}

# THREE calm groups for the Quest Log — RUN (work the desk is/was doing: asks, dossiers,
# matchups, chains) · FLAG (needs your eyes: proposals, sentinel flags) · NOTE (ambient memory).
# The old per-kind identity survives as a dim sub-tag after the badge, so a long feed scans by
# what-it-is in three colors instead of six competing ones.
_BLEND_KIND_GROUP = {"dossier": "run", "matchup": "run", "ask": "run", "flag": "flag", "note": "note"}
_BLEND_GROUP_STYLE = {"run": (AMBER, "⚙", "RUN"), "flag": (RED, "⚑", "FLAG"), "note": (TEAL, "✎", "NOTE")}


def _blend_kind_style(kind: str, status: str = "", level: str = ""):
    """(color, glyph, label, sub) for a Quest-Log event under the 3-group scheme. A live run is
    the one bright thing on the surface (AMBER_BRIGHT ⚙ RUN · live); a finished run earns a ✓;
    a flag takes its level color (risk red · warn orange) with the level as its sub-tag; the
    original kind (ask/dossier/matchup) rides along as the dim sub-tag."""
    grp = _BLEND_KIND_GROUP.get(kind, "note")
    if status == "running":
        return AMBER_BRIGHT, "⚙", "RUN", "live"
    if grp == "flag":
        return {"risk": RED, "warn": ORANGE}.get(level, RED), "⚑", "FLAG", str(level or "")
    kc, glyph, label = _BLEND_GROUP_STYLE[grp]
    if grp == "run" and status == "done":
        glyph = "✓"
    sub = "" if str(kind or "") == grp else str(kind or "")
    return kc, glyph, label, sub
_BLEND_OPEN_HINT = {"pipeline": "open chain", "matchup": "open matchup", "thread": "open thread",
                    "detail": "open"}
_MATCHUP_LENSES = ("Value", "Balance sheet", "Council", "Full")


def _council_convergence(meta: dict):
    """Read a council verdict's convergence ROBUSTLY across both schemas, so one variant can't crash
    the card. council.py stores ``convergence`` as a dict ``{bull, bear, contested}``; agent-written
    verdicts store a display STRING like ``'58/42'`` with ``contested`` / ``convergence_label`` as
    sibling meta keys. Returns ``(conv_str, contested)``. Pure."""
    meta = meta if isinstance(meta, dict) else {}
    raw = meta.get("convergence")
    conv = raw if isinstance(raw, dict) else {}
    contested = bool(meta.get("contested", conv.get("contested")))
    conv_str = (f"{conv.get('bull', '?')}/{conv.get('bear', '?')}" if conv
                else raw if (isinstance(raw, str) and raw)
                else str(meta.get("convergence_label", "") or ""))
    return conv_str, contested


def _blend_feed_row(it: dict, i: int, sel: int, expanded: set,
                    title_w: int = 50, wrap_w: int = 92, show_hint: bool = True) -> list:
    """Render ONE Quest-Log event to a list of Rich renderables — the shared per-item body used by
    BOTH the single-stream feed (``_blend_feed_parts``) and the three-lane grid (``_blend_feed_lanes``),
    so the two layouts can never drift. ``i`` is the GLOBAL index into the items list, so the
    click/expand metas (``blend_open(i)`` / ``blend_expand(i)``) stay correct in either layout."""
    import textwrap
    parts: list = []
    on = (i == sel)
    # a LIVE run streams its feed (expanded); a finished run settles to a collapsed result line —
    # user toggles still win (is_run_expanded honours the `expanded` set).
    exp = is_run_expanded(it, expanded)
    kind = it.get("kind")
    kc, glyph, label, sub = _blend_kind_style(kind, it.get("status", ""), it.get("level", ""))
    hint = _BLEND_OPEN_HINT.get(it.get("opens", "detail"), "open")
    # Resolve a click by the row's STABLE uid, never its positional index: the feed is rebuilt and
    # re-sorted (newest-first) on a 1s timer, so an index captured at render time can resolve to the
    # WRONG (drifting toward the most-recent) row by the time the click dispatches. uid survives the
    # rebuild. (Keyboard nav still passes its live _sel index, resolved positionally in the same tick —
    # no race there; _blend_item_by_ref accepts either.)
    _ref = repr(str(it.get("uid", "")))
    click = Style(meta={"@click": f"app.blend_open({_ref})"})
    caret = Style(meta={"@click": f"app.blend_expand({_ref})"})

    def gutter(head):
        g = Text("▸" if (head and on) else " ", style=(AMBER if on else FAINT))
        g.append("▌" if head else "│", style=Style.parse(f"bold {kc}" if head else kc)
                 + (click if head else caret))
        g.append(" ")
        return g

    row = gutter(True)
    row.append("▾ " if exp else "▸ ", style=Style.parse(f"bold {AMBER}" if exp else FAINT) + caret)
    # the type badge — a CALM tinted chip (group-colored text on the dark chip), not a
    # saturated fill: the group-colored ▌ left rule already carries the color. The dim
    # sub-tag (ask/dossier/matchup/live/risk) rides the same chip so the old kind survives.
    row.append(f" {glyph} {label} ", style=Style.parse(f"bold {kc} on #141418") + click)
    if sub:
        row.append(f"{sub} ", style=Style.parse(f"{FAINT} on #141418") + click)
    row.append(" ")
    title = str(it.get("title", ""))
    tk_ = str(it.get("ticker") or "")
    # dedup: don't print the ticker chip when the title already opens with it (no "URC.TO URC.TO …")
    dup = tk_ and title.upper().lstrip("◆●⑂ ").startswith(tk_.upper())
    if tk_ and not dup and " " not in tk_ and len(tk_) <= 10:
        row.append(f"{tk_} ", style=Style.parse(GOLD) + click)
    row.append(_clip(title, title_w),
               style=Style.parse("bold white" if on else SILVER) + click)
    if it.get("ts"):
        row.append(f"  {_rel_age(it.get('ts'))}", style=FAINT)
    if show_hint:
        row.append(f"   ↗ {hint}", style=Style.parse(DIM) + click)
    parts.append(row)
    if exp:
        full = str(it.get("full") or it.get("summary") or "").strip()
        # preserve line structure (the live agent feed and markdown results read as lines, not one
        # reflowed blob): wrap each source line, keep blank lines as paragraph breaks.
        for src in (full.split("\n") if full else []):
            for ln in (textwrap.wrap(src, wrap_w) or [""]):
                s = gutter(False)
                s.append(ln, style=SILVER)
                parts.append(s)
        if it.get("detail"):
            d = gutter(False)
            for di, (lbl, val) in enumerate(it["detail"][:5]):
                if di:
                    d.append("  ·  ", style=FAINT)
                d.append(f"{lbl} ", style=FAINT)
                d.append(str(val), style=DIM)
            parts.append(d)
    elif it.get("summary"):
        s = gutter(False)
        s.append(_clip(str(it.get("summary", "")), wrap_w), style=Style.parse(DIM) + click)
        parts.append(s)
    # the party line is signal for multi-agent runs; for single-source notes/flags it's just
    # noise ("party agent" / "party sentinel") — show it only when expanded, or when it's a chain
    show_party = it.get("party") and (exp or len(it["party"]) > 1 or kind in ("dossier", "matchup", "ask"))
    if show_party:
        pl = gutter(False)
        pl.append("party ", style=FAINT)
        for pi, p in enumerate(it["party"][:5]):
            if pi:
                pl.append(" → ", style=FAINT)
            prov, model = _agent_model(p)
            pl.append(f"{p}", style=f"{TEAL if prov == 'gemini' else DIM}")
            if p in HUB_AGENT_META:
                pl.append(f" ◇{model}", style=_MODEL_COLORS.get(model, DIM))
        parts.append(pl)
    if it.get("actions"):
        av = gutter(False)
        av.append_text(Text.from_markup(it["actions"]))
        parts.append(av)
    return parts


def _blend_feed_parts(items: list, sel: int, expanded: set, title_w: int = 50, wrap_w: int = 92) -> list:
    """Render the Quest-Log feed as ONE single stream of Rich renderables — SHARED by the Blend
    home's center column and the focused QUEST LOG surface (so they can never drift). Newest
    first, a blank line between events."""
    parts: list = []
    for i, it in enumerate(items[:40]):
        if i:
            parts.append(Text(""))
        parts.extend(_blend_feed_row(it, i, sel, expanded, title_w, wrap_w))
    return parts


# The three lanes, left→right, with their group key and header identity (color · glyph · label).
_BLEND_LANES = (("run", AMBER, "⚙", "RUN"), ("flag", RED, "⚑", "FLAG"), ("note", TEAL, "✎", "NOTE"))


def _blend_feed_lanes(items: list, sel: int, expanded: set, lane_w: int = 36, cap: int = 40):
    """Render the Quest-Log feed as THREE VERTICAL LANES — RUN · FLAG · NOTE side by side — so the
    event types are separated at a glance instead of interleaved in one stream. Reuses
    ``_blend_feed_row`` per item (preserving each event's GLOBAL index, so click/expand/selection
    stay correct), partitions by ``_BLEND_KIND_GROUP``, and lays the lanes out in a 3-column grid.
    Returns a single Rich renderable (a Table.grid)."""
    title_w = max(14, lane_w - 12)
    wrap_w = max(18, lane_w - 4)
    buckets: dict = {"run": [], "flag": [], "note": []}
    for i, it in enumerate(items[:cap]):
        grp = _BLEND_KIND_GROUP.get(it.get("kind"), "note")
        buckets.setdefault(grp, []).append((i, it))

    columns = []
    for grp, kc, glyph, label in _BLEND_LANES:
        rows = buckets.get(grp) or []
        head = Text()
        head.append(f" {glyph} {label} ", style=Style.parse(f"bold {kc} on #141418"))
        head.append(f"  {len(rows)}", style=FAINT)
        col_parts: list = [head, Text("")]
        if not rows:
            col_parts.append(Text("— none —", style=FAINT))
        for n, (gi, it) in enumerate(rows):
            if n:
                col_parts.append(Text(""))
            col_parts.extend(_blend_feed_row(it, gi, sel, expanded,
                                             title_w=title_w, wrap_w=wrap_w, show_hint=False))
        columns.append(Group(*col_parts))

    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(*columns)
    return grid


def _prop_label(p: dict) -> str:
    """A readable one-liner for a pending engine proposal — prefers an explicit label, else builds
    one from the structured fields (#id · key → value · proposer) so the feed never says just
    'proposal' while the actual change is invisible."""
    if p.get("label") or p.get("text"):
        return str(p.get("label") or p.get("text"))
    bits = []
    if p.get("id") is not None:
        bits.append(f"#{p.get('id')}")
    if p.get("key") or p.get("param"):
        bits.append(str(p.get("key") or p.get("param")))
    if p.get("value") is not None:
        bits.append(f"→ {p.get('value')}")
    if p.get("proposed_by"):
        bits.append(f"· {p.get('proposed_by')}")
    return " ".join(bits) or "proposal"

BLEND_NODE_W = 24          # chain-node card width in cells (border to border)
BLEND_NODE_H = 5           # card height: ╭─╮ · title · purpose · status · ╰─╯


def _provider_color(agent_id: str) -> str:
    """Provider lane color — amber = the Claude lane; teal only for a historical Gemini record."""
    return TEAL if _agent_model(agent_id)[0] == "gemini" else AMBER


def paint_fan(rows: list, trunk_row: int, direction: str = "out") -> list:
    """Hand-paint a fan-out / fan-in junction as box-glyph strings (5 cells wide) — Textual
    won't route edges. ``rows`` are the middle rows of the parallel nodes; ``trunk_row`` is the
    incoming (out) / outgoing (in) line. Fan-out splits with ┤, fan-in merges with ├; corners
    ╭ ╰ ╮ ╯ turn the lanes. Pure + deterministic — a function of the topology only (§05)."""
    rows = sorted(int(r) for r in rows)
    trunk_row = int(trunk_row)
    height = max(rows + [trunk_row]) + 1
    grid = [[" "] * 5 for _ in range(height)]
    lo, hi = min(rows + [trunk_row]), max(rows + [trunk_row])
    for r in range(lo, hi + 1):
        grid[r][2] = "│"                                   # the vertical trunk
    if direction == "out":
        grid[trunk_row][0] = "─"; grid[trunk_row][1] = "─"
        grid[trunk_row][2] = "┤"                           # left-in, splits up/down
        for r in rows:                                     # turn into each lane
            if r == trunk_row:
                grid[r][2] = "┼"
            else:
                grid[r][2] = "╭" if r < trunk_row else "╰"
            grid[r][3] = "─"; grid[r][4] = "→"
    else:                                                  # fan-in (mirror)
        for r in rows:
            grid[r][0] = "─"; grid[r][1] = "─"
            if r != trunk_row:
                grid[r][2] = "╮" if r < trunk_row else "╯"
        grid[trunk_row][2] = "┼" if trunk_row in rows else "├"
        grid[trunk_row][3] = "─"; grid[trunk_row][4] = "→"
    return ["".join(r) for r in grid]


def _blend_node_card(agent_id: str, state: str, pct=None, pulse: bool = False,
                     sel: bool = False, width: int = BLEND_NODE_W,
                     model: str = None, provider: str = None) -> list:
    """One chain node as ``BLEND_NODE_H`` Rich Text lines: a ╭╮╰╯-bordered card with
    title + model chip · purpose · status/live bar. Border color IS the state — mint done,
    amber/teal running (provider lane, dimmed every other pulse frame), faint queued.
    ``model``/``provider`` are the run's ACTUAL seat (the working-lane truth — e.g. a Gemini
    seat that fell back to Claude reads ◇sonnet); the static registry is only the fallback."""
    reg_prov, reg_model = _agent_model(agent_id)
    prov, model = (provider or reg_prov), (model or reg_model)
    base = TEAL if prov == "gemini" else AMBER
    ring = {"done": GREEN, "running": (DIM if pulse else base)}.get(state, BORDER)
    if sel:
        ring = GOLD
    inner = width - 2

    def _fit(s, n):                                       # exact-width fit (truncate w/ … or pad)
        s = str(s)
        return (s[: max(0, n - 1)].rstrip() + "…").ljust(n) if len(s) > n else s.ljust(n)

    doc = HUB_AGENT_DOC.get(agent_id, {})
    purpose = _fit(str(doc.get("tag", "") or agent_id), inner - 2)
    chip = f"◇{model}"
    title = _fit(agent_id.upper(), inner - 2 - len(chip) - 1)
    lines = []
    top = Text(f"╭{'─' * inner}╮", style=ring)
    bot = Text(f"╰{'─' * inner}╯", style=ring)
    t = Text("│ ", style=ring)
    t.append(title, style=f"bold {TEAL if prov == 'gemini' else GOLD}")
    t.append(" ")
    t.append(chip, style=_MODEL_COLORS.get(model, SILVER))
    t.append(" │", style=ring)
    p = Text("│ ", style=ring)
    p.append(purpose, style=DIM)
    p.append(" │", style=ring)
    s = Text("│ ", style=ring)
    if state == "done":
        s.append("✓ done".ljust(inner - 2), style=f"bold {GREEN}")
    elif state == "running":
        barw = inner - 5
        fill = max(0, min(barw, round(barw * float(pct if pct is not None else 0.5))))
        s.append("⚙ ", style=f"bold {base}")
        s.append("█" * fill, style=base)
        s.append("░" * (barw - fill), style=BORDER)
        s.append(" ")
    else:
        s.append("queued".ljust(inner - 2), style=FAINT)
    s.append(" │", style=ring)
    lines.extend([top, t, p, s, bot])
    return lines


def _vpad_center(lines: list, height: int, width: int) -> list:
    """Vertically center a block of Text lines inside ``height`` rows, right-padding every
    line to ``width`` cells so columns to the right stay aligned in the canvas."""
    padded = []
    for ln in lines:
        ln = ln.copy()
        if ln.cell_len < width:
            ln.append(" " * (width - ln.cell_len))
        padded.append(ln)
    blank = Text(" " * width)
    top = max(0, (height - len(padded)) // 2)
    out = [blank.copy() for _ in range(top)] + padded
    while len(out) < height:
        out.append(blank.copy())
    return out


def _hcat(cols: list) -> list:
    """Row-wise concatenation of columns of Text lines — the canvas assembler. Shorter columns
    pad with blanks of their own width so everything to their right stays aligned."""
    height = max((len(c) for c in cols if c), default=0)
    out = []
    for r in range(height):
        row = Text()
        for c in cols:
            if r < len(c):
                row.append_text(c[r])
            else:
                row.append(" " * (c[0].cell_len if c else 0))
        out.append(row)
    return out


def _blend_chain_canvas(stages: list, states: dict, pulse: bool = False, sel: int = -1,
                        target: str = "", target_role: str = "") -> Group:
    """Paint the whole pipeline strip — target ◆ → nodes → painted fan-out/fan-in junctions →
    DOSSIER — as one Rich Group (lives in a HorizontalScroll). ``stages`` is the workflow shape
    ([{agents:[…], note}, …]); ``states[(si, agent)]`` → done|running|queued (+ optional pct in
    ``states[(si, agent, 'pct')]``). v1 topology: single-depth splits only (the build-plan scope)."""
    n_lanes = max((len(s.get("agents", [])) for s in stages), default=1)
    height = max(BLEND_NODE_H, n_lanes * BLEND_NODE_H + (n_lanes - 1))
    trunk = height // 2
    cols: list = []

    # target block (◆ spear / ● ballast / name)
    glyph = _ROLE_GLYPH.get(target_role, "◈")
    tgt = [Text(f" {glyph} ", style=f"bold {AMBER}").append_text(Text(target or "book", style=f"bold {GOLD}")),
           Text("   target", style=FAINT)]
    width_t = max(len(target or "book") + 4, 10)
    cols.append(_vpad_center(tgt, height, width_t))

    prev_n = 1
    for si, st in enumerate(stages):
        agents = st.get("agents", []) or ["?"]
        # ── connector from the previous column ──
        def _fan_col(n_par: int, direction: str) -> list:
            painted = paint_fan(_lane_rows(n_par, height), trunk, direction)
            return [Text(painted[r] if r < len(painted) else "     ", style=AMBER) for r in range(height)]
        if prev_n == 1 and len(agents) == 1:
            cols.append([Text("──→", style=AMBER) if r == trunk else Text("   ") for r in range(height)])
        elif prev_n == 1:                                  # single → parallel: fan-out
            cols.append(_fan_col(len(agents), "out"))
        elif len(agents) == 1:                             # parallel → single: fan-in
            cols.append(_fan_col(prev_n, "in"))
        else:                                              # multi → multi: merge, then split (v1 honest)
            cols.append(_fan_col(prev_n, "in"))
            cols.append(_fan_col(len(agents), "out"))
        # ── the stage's node card(s) ──
        if len(agents) == 1:
            a = agents[0]
            card = _blend_node_card(a, states.get((si, a), "queued"), states.get((si, a, "pct")),
                                    pulse=pulse, sel=(sel == si),
                                    model=states.get((si, a, "model")),
                                    provider=states.get((si, a, "provider")))
            cols.append(_vpad_center(card, height, BLEND_NODE_W))
        else:
            stack: list = []
            for i, a in enumerate(agents):
                if i:
                    stack.append(Text(" " * BLEND_NODE_W))
                stack.extend(_blend_node_card(a, states.get((si, a), "queued"), states.get((si, a, "pct")),
                                              pulse=pulse, sel=(sel == si),
                                              model=states.get((si, a, "model")),
                                              provider=states.get((si, a, "provider"))))
            cols.append(_vpad_center(stack, height, BLEND_NODE_W))
        prev_n = len(agents)

    # ── final connector + the dossier endpoint ──
    if prev_n > 1:
        rows = _lane_rows(prev_n, height)
        painted = paint_fan(rows, trunk, "in")
        cols.append([Text(painted[r] if r < len(painted) else "     ", style=AMBER) for r in range(height)])
    else:
        cols.append([Text("──→", style=AMBER) if r == trunk else Text("   ") for r in range(height)])
    done_all = stages and all(states.get((si, a)) == "done"
                              for si, s in enumerate(stages) for a in (s.get("agents") or ["?"]))
    dc = GREEN if done_all else FAINT
    cols.append(_vpad_center([Text(" ❖ ", style=f"bold {dc}"), Text(" DOSSIER", style=f"bold {dc}"),
                              Text(" → log", style=FAINT)], height, 9))
    return Group(*_hcat(cols))


def _lane_rows(n: int, height: int) -> list:
    """Middle rows of ``n`` parallel node cards stacked (gap 1) and centered in ``height``."""
    block = n * BLEND_NODE_H + (n - 1)
    top = max(0, (height - block) // 2)
    return [top + i * (BLEND_NODE_H + 1) + BLEND_NODE_H // 2 for i in range(n)]


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


def _esc_change(s) -> str:
    """Escape Rich markup in untrusted text (council/bear bodies) for the CHANGE review."""
    return str(s or "").replace("[", r"\[")


def _change_title(p: dict) -> str:
    return f"[bold {AMBER}]⇄ CHANGE[/]  [{DIM}]·[/]  [bold {GOLD}]{p.get('kind','')} {p.get('subject','')}[/]"


def _change_body(p: dict) -> str:
    """The book change rendered as a BEFORE→AFTER diff + the deltas that matter + council/bear — the
    reframe's job 2. Cut names strike red; added names are green; the spear/ceiling warnings show."""
    d = p.get("deltas", {})
    before = {r["ticker"]: r for r in p.get("before", [])}
    after = {r["ticker"]: r for r in p.get("after", [])}
    removed = {t for t in before if t not in after}
    added = {t for t in after if t not in before}

    def _line(rows):
        parts = []
        for t, r in rows.items():
            w = f"{r['weight']*100:.0f}%"
            if t in removed:
                parts.append(f"[{RED} strike]{t} {w}[/]")
            elif t in added:
                parts.append(f"[{GREEN}]{t} {w}[/]")
            else:
                parts.append(f"[{SILVER}]{t}[/] [{GOLD}]{w}[/]")
        return "  ".join(parts) or f"[{DIM}]—[/]"

    L = [f"[{DIM}]BOOK — before[/]", "  " + _line(before),
         f"[{AMBER}]⇄[/] [{DIM}]BOOK — after[/]", "  " + _line(after), ""]
    sp = d.get("spear_share", {}) or {}
    dl = [f"weight freed [{GOLD}]{d.get('weight_freed',0)*100:.0f}%[/]",
          f"spear [{GOLD}]{sp.get('before',0)*100:.0f}→{sp.get('after',0)*100:.0f}%[/]"]
    bc_ = d.get("book_conviction")
    if bc_:
        col = GREEN if bc_["delta"] >= 0 else RED
        dl.append(f"conviction [{col}]{bc_['before']}→{bc_['after']} ({bc_['delta']:+})[/]")
    mr = d.get("min_runway")
    if mr:
        col = RED if mr["delta"] < 0 else GREEN
        dl.append(f"min runway [{col}]{mr['before']}→{mr['after']}mo ({mr['delta']:+}mo)[/]")
    L += ["  " + "  ·  ".join(dl), ""]
    if p.get("council"):
        L.append(f"[{TEAL}]Council[/]  [{SILVER}]{_esc_change(p['council'].get('text',''))}[/]")
    else:
        L.append(f"[{DIM}]Council — none on record; run /council {p.get('subject')} for a verdict[/]")
    if p.get("bear"):
        L.append(f"[{RED}]Bear ★[/]  [{SILVER}]invalidation preserved: {_esc_change(p['bear'].get('text',''))}[/]")
    if p.get("warnings"):
        L.append(f"[{ORANGE}]⚑ {_esc_change('; '.join(p['warnings']))}[/]")
    return "\n".join(L)


def _screen_funnel_markup(slot: str, result: dict, incumbent, pips: dict) -> str:
    """SCREEN as a SLOT-SCOPED kill-funnel (the reframe's job 3). Only names TAGGED for this slot are
    candidates; names tagged for OTHER slots aren't disconfirmations, they're irrelevant — counted
    quietly, never shown as 'cause of death'. The archive holds names that fit the slot but were
    killed on SUBSTANCE (stage / jurisdiction / mcap / survival / REP-floor) — real disproof.
    Survivors carry the incumbent they must beat + their disproof pips. Empty slot ⇒ a scout CTA."""
    survivors = result.get("survivors") or []
    killed = result.get("killed") or []
    mismatch = [k for k in killed if k.get("gate") == "slot_fit"]      # wrong slot — not a candidate here
    substantive = [k for k in killed if k.get("gate") != "slot_fit"]   # fit the slot, failed on merit
    n_cand = len(survivors) + len(substantive)
    try:
        import discovery_screen as _ds
        off = _ds.is_off_slot(slot)
    except Exception:
        off = False
    inc = incumbent or "the slot incumbent"
    skipped = (f"   [{FAINT}]({len(mismatch)} other-slot name{'s' if len(mismatch) != 1 else ''} "
               f"skipped)[/]" if mismatch else "")
    L = [f"[{DIM}]{'off-slot' if off else 'this slot'}[/]  [{SILVER}]{n_cand} candidate{'s' if n_cand != 1 else ''}[/]  ·  "
         f"[{RED}]{len(substantive)} killed[/]  ·  [bold {GREEN}]{len(survivors)} survived[/]{skipped}",
         (f"[{FAINT}]off-slot · no incumbent — calculated asymmetric bets that DON'T fit a slot; "
          f"◆ a survivor into its own new slot[/]" if off else
          f"[{FAINT}]built to kill, not collect — a card advances only by surviving disproof · "
          f"slot-fit: every candidate must beat {inc}[/]"), ""]

    # No candidates are even tagged for this slot — a clean, actionable empty-state, not a kill dump.
    if n_cand == 0:
        L.append(f"[{AMBER}]No candidates tagged for[/] [bold {GOLD}]{slot}[/] [{AMBER}]in the universe yet.[/]")
        L.append(f"[{SILVER}]The funnel is fed by the scout→universe loop — populate it:[/]")
        L.append(f"  [@click=app.funnel('scout','{slot}')][{TEAL}]› /scout {slot}[/][/]  "
                 f"[{DIM}]find names; add_candidate writes them here for the next screen[/]")
        if mismatch:
            names = ", ".join(k.get("ticker", "?") for k in mismatch[:10])
            L += ["", f"[{DIM}]{len(mismatch)} universe name(s) are tagged for OTHER slots (not "
                  f"{slot}): {names}[/]"]
        return "\n".join(L)

    def _pips(tk):
        got = pips.get(tk, set()) or set()
        cells = "".join("✓" if r in got else "·" for r in ("verifier", "anti_scout", "forensic"))
        return f"[{GREEN}]{cells}[/]" if got else f"[{DIM}]···[/]"

    def _surv(s):
        tk = s.get("ticker", "?")
        arch = " · ".join(x for x in [s.get("vehicle"), s.get("stage")] if x)
        gaps = s.get("data_gaps") or []
        row = (f"  [@click=app.funnel('open','{tk}')][bold {GOLD}]{tk}[/][/]  [{FAINT}]{arch}[/]"
               + (f"    [{TEAL}]vs {inc}[/]" if not off else "")
               + f"    disproof {_pips(tk)}")
        if gaps:
            row += f"    [{ORANGE}]gaps: {','.join(gaps)}[/]"
        if off:                                            # off-slot: turn this find into its own slot
            row += f"    [@click=app.new_slot_from('{tk}')][{AMBER}]◆ new slot from this[/][/]"
        else:
            row += f"    [@click=app.funnel('disconfirm','{tk}')][{AMBER}]⚑ disconfirm[/][/]"
        return row

    clean = [s for s in survivors if not s.get("data_gaps")]
    gappy = [s for s in survivors if s.get("data_gaps")]
    if clean:
        L.append(f"[bold {GREEN}]▲ SLOT-FIT — survived clean[/]  [{FAINT}]{len(clean)}[/]")
        L += [_surv(s) for s in clean] + [""]
    if gappy:
        L.append(f"[bold {AMBER}]⚑ DISCONFIRM — survived, gaps to close[/]  [{FAINT}]{len(gappy)}[/]")
        L += [_surv(s) for s in gappy] + [""]
    if substantive:
        L.append(f"[bold {RED}]† ARCHIVE — killed on substance (cause of death)[/]  [{FAINT}]{len(substantive)}[/]")
        for k in substantive[:40]:
            L.append(f"  [{DIM} strike]{k.get('ticker','?')}[/]  "
                     f"[{RED}]† {k.get('gate')}: {_esc_change(k.get('reason',''))}[/]")
    return "\n".join(L)


def _correlation_screen_markup(macro: dict, uncorr: dict) -> str:
    """SCREEN ⟂ — the macro-correlation section. TOP: is this a portfolio or one bet wearing different
    tickers? (avg pairwise ρ · each ballast's ρ to the spear · drift). BOTTOM: the universe ranked by
    INDEPENDENCE from the book — measured ρ where price history exists, factor-class proxy otherwise.
    Pure render over correlation_monitor.book_macro_summary + screen_uncorrelated."""
    macro = macro or {}
    uncorr = uncorr or {}

    def _cc(v):                                            # ρ-to-spear colour by magnitude
        return RED if v >= 0.6 else ORANGE if v >= 0.3 else GREEN

    L = [f"[bold {AMBER}]◮ PORTFOLIO MACRO-CORRELATION[/]  [{DIM}]a portfolio, or one bet wearing different tickers?[/]"]
    if not macro.get("available"):
        L.append(f"  [{FAINT}]{macro.get('read') or 'n/a — start the engine so the 60d correlation matrix caches'}[/]")
    else:
        avg, sf = _num(macro.get("avg_pairwise")), macro.get("single_factor")
        spear = macro.get("spear") or "AGA.V"
        if avg is not None:
            L.append(f"  avg pairwise ρ [bold {ORANGE if sf else GREEN}]{avg:.2f}[/]  "
                     + (f"[{ORANGE}]SINGLE-FACTOR — diversified by name, not by risk[/]" if sf
                        else f"[{GREEN}]genuinely multi-factor[/]"))
        sc = macro.get("spear_corr") or {}
        if sc:
            cells = "    ".join(f"[{GOLD}]{tk}[/] [{_cc(v)}]ρ{v:+.2f}[/]" for tk, v in sc.items())
            L.append(f"  vs the spear [{GOLD}]{spear}[/]:   {cells}")
        for d in (macro.get("drift") or []):
            L.append(f"  [{ORANGE}]⟂ drift[/] [{GOLD}]{d.get('ticker')}[/] "
                     f"[{ORANGE}]ρ {(_num(d.get('rho_long')) or 0):+.2f}→{(_num(d.get('rho_short')) or 0):+.2f}[/] "
                     f"[{DIM}]creeping toward the spear — ballast ceasing to diversify[/]")
    L.append("")

    cands = uncorr.get("candidates") or []
    nd, nm = uncorr.get("n_diversifiers", 0), uncorr.get("n_measured", 0)
    L.append(f"[bold {AMBER}]⟂ UNCORRELATED CANDIDATES[/]  [{SILVER}]{nd} potential diversifier(s)[/]  "
             f"[{DIM}]· {nm} measured by ρ, the rest factor-proxy[/]")
    if not cands:
        L.append(f"  [{FAINT}]{uncorr.get('read') or 'universe empty — feed it via /scout or add_candidate'}[/]")
        return "\n".join(L)

    colour = {"INDEPENDENT": GREEN, "DISTINCT-FACTOR": TEAL, "PARTIAL": ORANGE,
              "SAME-FACTOR": DIM, "REDUNDANT": RED}

    def _row(c):
        tk, v = c.get("ticker", "?"), c.get("verdict", "")
        col = colour.get(v, SILVER)
        if c.get("basis") == "measured":
            metric, tag = f"ρ→spear [{col}]{(_num(c.get('rho_to_spear')) or 0):+.2f}[/]", f"[{TEAL}]measured[/]"
        else:
            metric, tag = f"factor [{col}]{c.get('factor') or 'none'}[/]", f"[{DIM}]proxy[/]"
        meta = " · ".join(x for x in [c.get("vehicle"), c.get("commodity")] if x)
        return (f"  [@click=app.funnel('open','{tk}')][bold {GOLD}]{tk}[/][/]  [{col}]{v}[/]  {metric}  {tag}"
                + (f"  [{FAINT}]{meta}[/]" if meta else ""))

    div = [c for c in cands if c.get("verdict") in ("INDEPENDENT", "PARTIAL", "DISTINCT-FACTOR")]
    rest = [c for c in cands if c not in div]
    if div:
        L += [_row(c) for c in div]
    else:
        L.append(f"  [{AMBER}]none — the universe loads the book's single factor.[/]")
        L.append(f"  [{SILVER}]source diversifiers with[/] [{TEAL}]/counterweight[/][{SILVER}] — non-resource "
                 f"names that decorrelate from the spear + fill your scenario holes — then price them with[/] "
                 f"[{TEAL}]dual_sided_valuation[/][{SILVER}]; they land here tagged[/] [{AMBER}]lane: conventional[/]")
    if rest:
        L += ["", f"[{DIM}]same-factor / correlated ({len(rest)}) — not diversifiers:[/]"]
        L += [f"  [{DIM} strike]{c.get('ticker', '?')}[/]  [{FAINT}]{str(c.get('verdict', '')).lower()}[/]"
              for c in rest[:30]]
    L += ["", f"[{FAINT}]measured = ρ of returns to the spear/book · proxy = factor class (backfill prices to "
          f"measure). the 'different reasons' test, not 'different sector'.[/]"]
    return "\n".join(L)


class ChangeReviewScreen(ModalScreen):
    """⇄ CHANGE — review a book change as a DIFF before it touches the book (the reframe's job 2).

    Renders a ``book_change`` proposal: the before→after barbell diff, the deltas that matter, the
    Council verdict + the Bear's preserved invalidation, a MANDATORY pre-mortem, and a deliberate
    commit that files the change through the EXISTING gated path (never a direct mutation). Additive
    — a pushed modal; it does not touch WATCH, the cockpit ticker, or the engine."""

    BINDINGS = [("escape", "dismiss", "Close")]
    # Mirror the proven InspectScreen modal exactly (the one every working surface uses): a
    # max-width-clamped box that never overflows a narrow pane, and a bounded-scroll body. The
    # earlier hardcoded `width: 90` with no max-width overflowed real terminals and broke the layout.
    DEFAULT_CSS = """
    ChangeReviewScreen { align: center middle; background: #08080A 70%; }
    #change_box { width: 92; max-width: 94%; height: auto; max-height: 90%;
                  border: round #D6A24A; background: #0E0E10; padding: 1 2; }
    #change_title { height: auto; text-style: bold; color: #D9C27E; padding-bottom: 1; }
    ChangeReviewScreen VerticalScroll { height: auto; max-height: 60vh; }
    #change_diff { height: auto; color: #CBCBD2; padding: 1 0; }
    #change_premortem { height: auto; margin: 1 0 0 0; border: round #CF9A5C; }
    #change_actions { height: auto; padding-top: 1; }
    #change_commit { background: #D6A24A; color: #08080A; min-width: 18; }
    """

    def __init__(self, proposal: dict, spec: dict) -> None:
        super().__init__()
        self._p = proposal
        self._spec = spec

    def compose(self) -> ComposeResult:
        with Vertical(id="change_box"):
            yield Static(_change_title(self._p), id="change_title")
            yield VerticalScroll(Static(_change_body(self._p), id="change_diff"))
            yield Input(placeholder="pre-mortem — it's 90 days out and this was wrong. why?  (required to commit)",
                        id="change_premortem")
            with Horizontal(id="change_actions"):
                yield Button("commit change ⏎", id="change_commit", variant="warning")
                yield Static(f"  [{DIM}]esc closes · two-step · files a gated change you then /confirm[/]")

    def on_button_pressed(self, event) -> None:
        if event.button.id == "change_commit":
            pm = self.query_one("#change_premortem", Input).value.strip()
            if not pm:
                self.app._status(Text("pre-mortem required — name how this is wrong at 90 days, then commit",
                                      style=ORANGE))
                return
            self.app._change_apply(self._spec, self._p, pm)
            self.dismiss()

    def action_dismiss(self, result=None) -> None:
        self.dismiss(result)


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
        items.append(("hub", "Agent Hub — the Blend", "quest log · launch · matchups · concierge", ("hub", "")))
        items.append(("hub", "Mission control (classic)", "reader board · composer · memory · audit", ("hubclassic", "")))
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
    """The Agent Hub — full-screen mission control (handoff: docs/archive/design_handoff_agent_hub).
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
        Binding("t", "toggle_left", "Team"),
        Binding("1", "catset('archive')", "Archive", show=False),
        Binding("2", "catset('threads')", "Threads", show=False),
        Binding("3", "catset('activity')", "Activity", show=False),
        Binding("0", "catset('all')", "All", show=False),
    ]
    # Archive = living memory + saved files (notes/verdicts/decisions/catalysts)
    # Threads = auto-saved + session threads
    # Activity = agent activity log (renamed from Tape)
    CATS = [("archive", "Archive"), ("threads", "Threads"), ("activity", "Activity"), ("all", "All")]

    def __init__(self, tk: str | None = None, cat: str = "archive") -> None:
        super().__init__()
        self._cat = cat if cat in dict(self.CATS) else "archive"
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
        self._left = "chats"                   # colA: 'chats' (conversations sidebar) | 'team' (roster)

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
                    yield Static("", id="hub_recurring")    # ⏲ SCHEDULED — the recurring jobs
                    yield Static("", id="hub_audit")        # ENGINE AUDIT — fetch · verify · review
                # ── FEED + COMPOSE — chronological research feed above a context-aware compose box ──
                with Vertical(id="hub_colB"):
                    with VerticalScroll(id="hub_feed_scroll"):   # chronological thread feed (main area)
                        yield Static("", id="hub_feed")
                    with Vertical(id="hub_compose_area"):        # compose docked to bottom
                        yield Static("", id="hub_compose_ctx")   # context bar (shown when following up)
                        yield Input(placeholder='Ask anything — plain English, @agent, or a command…', id="hub_input")
                        yield Static("", id="hub_composer")      # agent · verb · subject · go
                        yield Static("", id="hub_commands")      # saved command pills
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
        self.app._render_hub_compose_ctx()      # restore follow-up context bar if one was set
        self._timer = self.set_interval(1.0, self._tick)    # live elapsed / proposals while open

    def _tick(self) -> None:
        a = self.app
        try:
            a._render_hub_feed()                            # unified feed (working + proposals + threads)
            a._render_autonomy(a._state or {})
            a._render_flags()
            self._paint_head(); self._paint_foot()
            if self._insp_task is not None and self.current() is None:
                self._paint_inspector()
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
    def action_toggle_left(self) -> None:
        """Flip colA between the conversations sidebar (default) and the agent roster (TEAM)."""
        self._left = "team" if self._left == "chats" else "chats"
        self.refresh_cards()
        self.app._toast("TEAM roster — click an agent to inspect" if self._left == "team"
                        else "CONVERSATIONS — your chats", TEAL)

    def refresh_cards(self) -> None:
        a = self.app; st = a._state or {}
        try:
            a._render_hub_feed(); a._render_autonomy(st); a._render_flags()
        except Exception:
            pass
        for wid, builder in (("#hub_roster", a._card_roster_markup),
                             ("#hub_recurring", a._card_recurring_markup),
                             ("#hub_audit", a._card_audit_markup),
                             ("#hub_commands", a._card_commands_markup),
                             ("#hub_composer", a._hub_composer_markup)):
            try:
                self.query_one(wid, Static).update(builder())
            except Exception:
                pass
        self._paint_head()
        self._paint_foot()
        if self.current() is None:                       # no reader item selected → repaint the inspector
            self._paint_inspector()

    def _paint_head(self) -> None:
        """The header chrome: brand · FLEET (the model mix — claude opus/sonnet) · catalyst windows ·
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
        through the composer (the typed text becomes the task's natural-language brief).
        When a follow-up context is set (hub_compose_ctx), the ask resumes from that thread node."""
        event.stop()
        app = self.app
        val = (event.value or "").strip(); low = val.lower()
        if not val:
            return
        # Follow-up context: resume from the thread node set by "↩ follow up"
        ctx = app._hub_compose_ctx
        if ctx and not any(low.startswith(p) for p in ("note:", "catalyst:", "claim:", "rule:", "job ", "scenario:")):
            app._active = ctx.get("tail") or ctx.get("root")   # resume from thread tail
            app._hub_compose_ctx = None
            app._render_hub_compose_ctx()
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
                    app._delegate(agent, val, subject=(tk or self._c_subject), verb=verb,
                                  continue_thread=True)      # the composer continues the open chat
                else:
                    app._ask_agent(val, continue_thread=True)  # no keyword → the orchestrator routes it
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




# ---------------------------------------------------------------------------------------------------
# PREDICT lens — the Wealthsimple Predict / Kalshi arb scanner's live board. Pure (state-slice →
# Text) so the card renders identically in tests and in the cockpit; the TUI only places it.
# ---------------------------------------------------------------------------------------------------

def render_predict_arb(pa) -> Text:
    """Render the ``predict_arb`` state slice: feed status + universe counts, then the ranked
    opportunity lines — L1 structural (green, riskless if filled) vs L2 value (labeled a BET) —
    each with its NET (post fee + FX) edge. Clean is a rendered result, not an empty box."""
    pa = pa or {}
    out = Text()
    if not pa.get("available"):
        out.append(str(pa.get("summary") or "PREDICT scanner warming up…"), style=DIM)
        return out
    uni = pa.get("universe") or {}
    status = str(pa.get("status") or "")
    out.append("Kalshi ", style=DIM)
    out.append(status or "?", style=(GREEN if status == "LIVE" else ORANGE))
    out.append(f"  {uni.get('events', 0)} ev · {uni.get('markets', 0)} mkt · "
               f"{uni.get('quoted', 0)} quoted", style=DIM)
    out.append("\n")
    opps = pa.get("opportunities") or []
    if not opps:
        out.append("clean — no net-positive mispricing after the fee stack\n", style=GREEN)
    for o in opps[:6]:
        lane = str(o.get("lane") or "")
        net = _num(o.get("net")) or 0.0
        out.append(f"{lane} ", style=(GREEN if lane == "L1" else SILVER))
        out.append(f"{str(o.get('kind') or ''):<13}", style=DIM)
        out.append(f"{net * 100:+5.1f}¢ ", style=(GREEN if net >= 0.03 else SILVER))
        out.append(str(o.get("event_ticker") or o.get("ticker") or "")[:24], style=AMBER)
        if lane == "L2":
            out.append(f" p̂={o.get('p_hat')} ({str(o.get('source') or 'model')[:14]}) — a bet",
                       style=DIM)
        out.append("\n")
    n_more = max(0, len(opps) - 6)
    if n_more:
        out.append(f"…+{n_more} more (predict_opportunities)\n", style=DIM)
    out.append("alerts only — execute in the Predict app · full desk: h → 7", style=FAINT)
    return out


# ---------------------------------------------------------------------------------------------------
# PREDICT DESK — the full-screen surface's section builders. All PURE (plain data → rich.Text,
# built with .append so tickers/bands can never be mis-parsed as markup) — the surface only does
# the IO (engine state, the fair-value store, the fired-ledger tail) and places these.
# ---------------------------------------------------------------------------------------------------

def _predict_ts(ts):
    """Epoch → compact UTC clock for the desk header ('' when unknown)."""
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).strftime("%H:%M:%SZ")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def predict_desk_status(dash) -> Text:
    """The feed strip: status · universe counts · graph shape · sweep time, then the fee model
    (placeholders until Predict launches — said out loud, never buried)."""
    d = dash or {}
    out = Text()
    status = str(d.get("status") or ("WARMING UP" if not d.get("available") else "?"))
    out.append("Feed ", style=DIM)
    out.append(status, style=("bold " + GREEN) if status == "LIVE" else ("bold " + ORANGE))
    uni = d.get("universe") or {}
    if uni:
        out.append(f"   {uni.get('events', 0)} events · {uni.get('markets', 0)} markets · "
                   f"{uni.get('quoted', 0)} quoted", style=SILVER)
        out.append(f" · {uni.get('ladders', 0)} ladders · {uni.get('partitions', 0)} partitions",
                   style=DIM)
    ts = _predict_ts(d.get("as_of"))
    if ts:
        out.append(f"   swept {ts}", style=FAINT)
    out.append("\n")
    f = d.get("fees_model") or {}
    if f:
        fx = f"{(_num(f.get('fx_spread_oneway')) or 0) * 100:.1f}%/way FX" \
            if f.get("fx_applies", True) else "no FX (USD)"
        out.append("Fees ", style=DIM)
        out.append(f"WS ${_num(f.get('ws_commission_per_contract')) or 0:.02f}/ct + "
                   f"Kalshi ~{(_num(f.get('kalshi_fee_rate')) or 0) * 100:.0f}%·P(1−P) + {fx}",
                   style=SILVER)
        out.append("   placeholders until launch — calibrate from the first real fills",
                   style=FAINT)
    for err in (d.get("errors") or [])[:2]:
        out.append(f"\n⚠ {err.get('series')}: {err.get('error')}", style=ORANGE)
    return out


def predict_desk_lane(dash, lane) -> Text:
    """One lane's board. L1 = structural Dutch books (riskless IF filled — green, legs spelled
    out, depth verdict shown); L2 = model-vs-market value (labeled a BET, p̂ + source + Kelly cap).
    An empty lane renders its meaning — clean IS a result, not a blank box."""
    d = dash or {}
    opps = [o for o in (d.get("opportunities") or []) if o.get("lane") == lane]
    out = Text()
    if lane == "L1":
        out.append("L1 STRUCTURAL", style="bold " + GREEN)
        out.append("  Dutch books inside the source book — riskless if filled, net of fees\n",
                   style=DIM)
        if not opps:
            out.append("  clean — the book is internally consistent net of the fee stack "
                       "(this is the normal, honest result)\n", style=GREEN)
        for o in opps[:8]:
            net = _num(o.get("net")) or 0.0
            out.append(f"  {str(o.get('kind') or ''):<14}", style=SILVER)
            out.append(f"net {net * 100:+5.1f}¢/$1  ", style="bold " + GREEN)
            cap = o.get("size_cap")
            out.append(f"≤{cap:g} ct  " if isinstance(cap, (int, float)) else "size ?  ", style=DIM)
            out.append(str(o.get("event_ticker") or "")[:28], style=AMBER)
            if o.get("depth_validated"):
                nas = o.get("net_at_size")
                out.append("  depth✓", style=GREEN)
                if isinstance(nas, (int, float)):
                    out.append(f" ({nas * 100:+.1f}¢ walked)", style=DIM)
            else:
                out.append("  top-of-book", style=FAINT)
            out.append("\n")
            legs = o.get("legs") or []
            if legs:
                out.append("      " + " + ".join(
                    f"{str(l.get('side') or '').upper()} {str(l.get('ticker') or '')[-14:]}"
                    f"@{l.get('ask')}" for l in legs[:5])
                    + (f"  (+{len(legs) - 5})" if len(legs) > 5 else "") + "\n", style=DIM)
    else:
        out.append("L2 VALUE", style="bold " + SILVER)
        out.append("  sourced p̂ vs market — a BET, never arb; band-gated, Kelly-capped\n",
                   style=DIM)
        if not opps:
            out.append("  no live edge — either no sourced p̂ yet (set one below) or every price "
                       "sits inside its model's band\n", style=FAINT)
        for o in opps[:8]:
            net = _num(o.get("net")) or 0.0
            out.append(f"  {str(o.get('ticker') or '')[:28]:<30}", style=AMBER)
            out.append(f"{str(o.get('side') or '').upper()}@{o.get('ask')}  ", style=SILVER)
            out.append(f"p̂={o.get('p_hat')} ", style=SILVER)
            out.append(f"({str(o.get('source') or 'model')[:16]})  ", style=DIM)
            out.append(f"edge {net * 100:+5.1f}%  ", style="bold " + (GREEN if net >= 0.08 else SILVER))
            out.append(f"Kelly≤{o.get('kelly')}\n", style=DIM)
    return out


def predict_desk_fv(fv) -> Text:
    """The p̂ book — every sourced fair value feeding the L2 sweep, provenance on the line."""
    out = Text()
    out.append("p̂ BOOK", style="bold " + TEAL)
    out.append("  the sourced probabilities the L2 sweep prices against\n", style=DIM)
    fv = fv if isinstance(fv, dict) else {}
    if not fv:
        out.append("  none yet — predict_fair_value(ticker, p_hat, band, source) from the chat "
                   "(a p̂ REQUIRES a source)\n", style=FAINT)
    for tk, e in sorted(fv.items())[:12]:
        e = e or {}
        out.append(f"  {str(tk)[:30]:<32}", style=AMBER)
        out.append(f"p̂={e.get('p_hat')}", style=SILVER)
        band = e.get("band")
        if isinstance(band, (list, tuple)) and len(band) == 2:
            out.append(f" band {band[0]}–{band[1]}", style=DIM)
        out.append(f"  {str(e.get('source') or '')[:24]}", style=DIM)
        out.append(f"  {str(e.get('as_of') or '')}\n", style=FAINT)
    return out


def predict_desk_ledger(rows) -> Text:
    """The fired ledger's tail — the scanner's own append-only track record (what it alerted,
    when, at what net), the raw material replay-grading will consume."""
    out = Text()
    out.append("FIRED LEDGER", style="bold " + ORANGE)
    out.append("  every alert, immutably — the scanner's own track record\n", style=DIM)
    rows = list(rows or [])
    if not rows:
        out.append("  empty — nothing has cleared the net threshold yet (the ledger fills "
                   "itself; an empty ledger under honest fees is signal too)\n", style=FAINT)
    for r in rows[-8:][::-1]:
        r = r or {}
        out.append(f"  {str(r.get('date') or '')[:10]}  ", style=FAINT)
        out.append(f"{str(r.get('lane') or ''):<3}", style=(GREEN if r.get('lane') == 'L1' else SILVER))
        out.append(f"{str(r.get('kind') or ''):<14}", style=DIM)
        out.append(str(r.get("event_ticker") or "")[:28], style=AMBER)
        net = _num(r.get("net"))
        if net is not None:
            out.append(f"  net {net * 100:+.1f}¢", style=SILVER)
        out.append("\n")
    return out
