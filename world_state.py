"""
World-state snapshot — one situational-awareness object every agent inherits (Forge nervous system #3).

Today each agent stitches its own picture from three tools (get_conviction_ratings + memory_query +
get_ui_context). This assembles a single snapshot — regime + posture, what the operator is looking at,
the operator's last few actions (now visible thanks to the desk-tape hook), the book's verdicts, and
recent Living-Memory entries — so an agent prompt can be prepended with it and no agent starts blind.

Pure stdlib, fully testable. The engine/MCP wraps ``build`` with the live fetches; ``render_brief``
gives the compact text header to prepend to a prompt.
"""
from __future__ import annotations

import time
from typing import Any, Optional


def build(state: dict, *, recent_memory: Optional[list] = None,
          focus: Optional[str] = None) -> dict:
    """One situational-awareness snapshot from the engine ``state`` (+ optional recent Living-Memory
    entries and the operator's current focus). Everything optional — degrades gracefully to nulls."""
    state = state or {}
    conv = state.get("conviction_mode") or {}
    posture = state.get("posture") or {}
    tape = state.get("macro_tape") or {}
    acts = state.get("agent_activity") or []
    baskets = conv.get("baskets") or []
    pipe = state.get("pipeline") or {}

    op_kinds = {"ran", "edited", "git", "prompt"}
    recent_actions = []
    for a in acts[-8:]:
        who = "you" if (a.get("kind") in op_kinds and "claude" in str(a.get("agent", "")).lower()) \
            else a.get("agent", "agent")
        recent_actions.append({"who": who, "kind": a.get("kind"),
                               "what": str(a.get("summary", ""))[:60], "ticker": a.get("ticker")})

    active_agents = sorted({str(a.get("agent")) for a in acts[-8:]
                            if a.get("kind") in ("prompt", "tool", "response")})

    return {
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "regime": {"mri": state.get("mri"), "net_tilt": tape.get("net_tilt"),
                   "posture": posture.get("label") or posture.get("code"),
                   "posture_cap": posture.get("cap"), "headwind": posture.get("headwind")},
        "focus": focus or (conv.get("context") or {}).get("focus"),
        "book": [{"ticker": b.get("ticker"), "rating": b.get("rating"), "band": b.get("band"),
                  "directive": b.get("directive")} for b in baskets],
        "recent_actions": recent_actions,
        "recent_memory": [{"type": e.get("type"), "ticker": e.get("ticker"),
                           "text": str(e.get("text", ""))[:80], "ts": e.get("ts")}
                          for e in (recent_memory or [])[:5]],
        "pipeline": ({"status": pipe.get("status"), "theme": pipe.get("theme"),
                      "stage": pipe.get("stage")} if pipe.get("status") not in (None, "idle") else None),
        "active_agents": active_agents,
    }


def render_brief(ws: dict) -> str:
    """A compact text header to prepend to an agent prompt — the shared situational frame."""
    ws = ws or {}
    r = ws.get("regime") or {}
    lines = ["## DESK STATE (shared situational awareness — ground your reasoning in this)"]
    cap = r.get("posture_cap")
    lines.append(f"- Regime: MRI {r.get('mri')}, {r.get('net_tilt') or '—'}; "
                 f"posture {r.get('posture') or '—'}"
                 + (f" ({cap:g}x cap{', headwind' if r.get('headwind') else ''})" if cap is not None else ""))
    if ws.get("focus"):
        lines.append(f"- Operator is looking at: {ws['focus']}")
    book = ws.get("book") or []
    if book:
        lines.append("- Book: " + " · ".join(
            f"{b['ticker']} {b.get('rating')}/10 {str(b.get('directive') or '').split('—')[-1].strip()[:18]}"
            for b in book if b.get("ticker")))
    acts = ws.get("recent_actions") or []
    if acts:
        lines.append("- Recent actions: " + " · ".join(
            f"{a['who']} {a.get('kind')}: {a.get('what')}" for a in acts[-5:]))
    mem = ws.get("recent_memory") or []
    if mem:
        lines.append("- Recent memory: " + " · ".join(
            f"[{m.get('type')}] {m.get('ticker') or ''} {m.get('text')}".strip() for m in mem[:3]))
    if ws.get("pipeline"):
        p = ws["pipeline"]
        lines.append(f"- Pipeline: {p.get('status')} {p.get('theme') or ''} ({p.get('stage') or ''})")
    if ws.get("active_agents"):
        lines.append(f"- Also running: {', '.join(ws['active_agents'])}")
    return "\n".join(lines)
