"""
Reactive triggers — the cockpit acts (a little) without being asked (Forge nervous system #5).

A tiny rules layer over the semantic event stream: when posture flips to DEFENSIVE, pin a book-level
caution; when a name's JSF gate trips, flag it risk. This is the difference between a dashboard you
query and a desk that talks back.

Three guardrails, hard-wired (they are the whole reason this is safe):
  1. **Decision-support ONLY.** Triggers may pin / highlight / surface — they NEVER size, press, cut,
     or otherwise act on the book. The output is annotations, not orders.
  2. **Loop-guarded.** Triggers consume *state* events (posture/gate/directive) and emit *annotations*.
     Annotations are not state events, so a trigger's output can never re-trigger itself. No storms.
  3. **Rate-limited.** Each rule de-dupes on a key with a cooldown, so a flapping posture can't spam.

Pure stdlib, fully testable. The engine feeds it the per-cycle events + the fired-keys ledger and
applies the returned actions through the existing pin/highlight path.
"""
from __future__ import annotations

import time
from typing import Optional

COOLDOWN_SECONDS = 1800.0        # don't re-fire the same trigger within 30 min (anti-flap)


def evaluate(events: list, *, fired: Optional[dict] = None, now: Optional[float] = None) -> list:
    """Map semantic events (from cockpit_events.detect_events) to decision-support actions.

    Each action: ``{action: 'pin'|'highlight', ticker, level, text, key}``. ``fired`` is a
    {key: last_ts} ledger the caller persists across cycles; a key within COOLDOWN is suppressed.
    Returns only the actions to apply this cycle (already rate-limited). NEVER returns a book action.
    """
    fired = fired or {}
    now = now if now is not None else time.time()
    out = []
    for e in events:
        kind, summ = e.get("kind"), str(e.get("summary", ""))
        action = None
        if kind == "posture" and "DEFENSIVE" in summ.upper():
            action = {"action": "pin", "ticker": None, "level": "warn", "key": "posture:defensive",
                      "text": "Regime turned DEFENSIVE — accumulate smaller / slower, raise dry powder."}
        elif kind == "alert" and "JSF gate tripped" in summ:
            tk = e.get("ticker")
            action = {"action": "highlight", "ticker": tk, "level": "risk", "key": f"jsf:{tk}",
                      "text": "JSF gate tripped — forensic review before sizing."}
        if not action:
            continue
        last = fired.get(action["key"])
        if last is not None and (now - last) < COOLDOWN_SECONDS:
            continue                                   # rate-limited — already surfaced recently
        out.append(action)
    return out
