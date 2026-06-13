"""
Cockpit event detection — semantic state-change events from the engine's snapshots (Forge nervous
system #1).

Today consumers diff a giant JSON blob to notice change; nobody is *told* "posture flipped to
DEFENSIVE" or "JSF tripped on AGA.V" — they re-derive it. This turns the meaningful deltas into
typed events the desk tape can show and Living Memory can subscribe to.

The architectural rule (the one correction to the roadmap's "one log"): there are TWO streams.
- The **ephemeral event bus** (the existing /agent/activity ring) carries ALL of these — high
  frequency, short retention, the nervous system.
- **Living Memory** (the immutable, git-versioned audit record) persists ONLY the signal-worthy
  ones (``persist=True``) — a posture flip, a tripped forensic gate — never the chatter. So the
  track record stays clean.

Pure stdlib, fully testable. The engine calls ``detect_events(prev, curr)`` each cycle with a small
snapshot and routes the results: every event to the bus, the ``persist`` ones to memory.
"""
from __future__ import annotations

from typing import Any


def snapshot(state: dict) -> dict:
    """Reduce the engine terminal_state to the small comparable shape the detector needs."""
    conv = (state or {}).get("conviction_mode") or {}
    baskets = conv.get("baskets") or []
    posture = (state or {}).get("posture") or {}
    gates, directives = {}, {}
    for b in baskets:
        tk = b.get("ticker")
        if not tk:
            continue
        gate = b.get("gate") or {}
        gates[tk] = bool(gate.get("applied"))
        if b.get("directive"):
            directives[tk] = b.get("directive")
    return {
        "posture": {"code": posture.get("code"), "label": posture.get("label"),
                    "cap": posture.get("cap")},
        "gates": gates,
        "directives": directives,
    }


def detect_events(prev: dict, curr: dict) -> list:
    """Diff two snapshots (from ``snapshot``) into semantic events, each:
    ``{kind, summary, ticker?, level, persist}``. ``persist=True`` => Living-Memory-worthy.

    No prior snapshot (cold start) => no events (we don't fire on first sight)."""
    if not prev:
        return []
    events: list = []

    # posture flip — a book-level regime change (always signal-worthy)
    pc = (prev.get("posture") or {}).get("code")
    cc = (curr.get("posture") or {}).get("code")
    if pc and cc and pc != cc:
        label = (curr.get("posture") or {}).get("label") or cc
        tightening = {"spear_exploit": 0, "balanced": 1, "defensive": 2}
        worse = tightening.get(cc, 1) > tightening.get(pc, 1)
        events.append({"kind": "posture", "summary": f"posture → {label}",
                       "level": ("warn" if worse else "good"), "persist": True})

    # JSF gate transitions per name (trip = signal-worthy; clear = informational). A trip fires
    # only when the ticker had a GENUINE prior reading (``tk in pg``) — never when it was merely
    # absent from a degenerate/empty prev snapshot (e.g. a cycle whose conviction block produced
    # no baskets). Without this guard a persistently-gated name (a pre-revenue explorer) re-trips
    # every time one bad cycle wipes the baseline — the "nothing changed" JSF-note spam.
    pg, cg = prev.get("gates") or {}, curr.get("gates") or {}
    for tk, applied in cg.items():
        if tk not in pg:
            continue                                   # first genuine sight of this name -> no event
        was = bool(pg.get(tk))
        if applied and not was:
            events.append({"kind": "alert", "summary": f"JSF gate tripped on {tk}",
                           "ticker": tk, "level": "risk", "persist": True})
        elif was and not applied:
            events.append({"kind": "note", "summary": f"JSF gate cleared on {tk}",
                           "ticker": tk, "level": "good", "persist": False})

    # directive flips per name (e.g. ACCUMULATE → TRIM) — informational on the tape, not persisted
    pd, cd = prev.get("directives") or {}, curr.get("directives") or {}
    for tk, d in cd.items():
        old = pd.get(tk)
        if old and old != d:
            events.append({"kind": "note", "summary": f"{tk}: {_short(old)} → {_short(d)}",
                           "ticker": tk, "level": "info", "persist": False})
    return events


def _short(directive: Any) -> str:
    """The headline verb of a directive ('BELOW FLOOR — ACCUMULATE · watch' -> 'ACCUMULATE')."""
    d = str(directive or "")
    for key in ("ACCUMULATE", "CORE HOLD", "TRIM", "AVOID", "STAND ASIDE", "WATCH", "HOLD", "MONITOR"):
        if key in d.upper():
            return key
    return d[:18]
