"""
Conviction board — Forge-Matrix M3. The book's call per name at a glance: rating (1-10) + directive
(ACCUMULATE / HOLD / TRIM), the directive coloured green/amber/red. Quick monitoring, not a decision
tool — the engine owns the rating and the call; the glass just shows them.
"""
from __future__ import annotations

from .. import config as cfg
from .. import font
from ..contract import MatrixState
from . import base

_ROWS_Y = [14, 27, 40, 53]   # 128x64: small title + 4 big (scale-2) rows

_DIR_SHORT = {
    "ACCUMULATE": "ACC", "ADD": "ADD", "BUY": "BUY", "HOLD": "HOLD", "WAIT": "WAIT",
    "TRIM": "TRIM", "REDUCE": "RED", "SELL": "SELL", "AVOID": "AVD", "EXIT": "EXIT",
}
_DIR_STATE = {
    "ACC": "calm", "ADD": "calm", "BUY": "calm",
    "HOLD": "elevated", "WAIT": "elevated",
    "TRIM": "stress", "RED": "stress", "SELL": "stress", "AVD": "stress", "EXIT": "stress",
}


def _dir_short(directive) -> str:
    if not directive:
        return ""
    up = str(directive).upper()
    for key, short in _DIR_SHORT.items():          # find the ACTION anywhere ("BELOW FLOOR — ACCUMULATE" -> ACC)
        if key in up:
            return short
    head = up.replace("—", " ").replace("-", " ").split()
    return head[0][:4] if head else ""


def render(ms: MatrixState):
    img = base.new_frame()
    font.draw_text(img, 2, 1, "CONVICTION", cfg.PALETTE["dim"])
    if ms.stale:
        base.draw_stale(img)
    holds = [w for w in ms.watchlist if not w.eval_only]
    for w, y in zip(holds[:4], _ROWS_Y):
        font.draw_text(img, 2, y, (w.symbol or "")[:5], cfg.PALETTE["text"], scale=2)
        if w.rating is not None:
            font.draw_text(img, 58, y, f"{w.rating:.1f}", cfg.PALETTE["text"], scale=2)
        ds = _dir_short(w.directive)
        if ds:
            font.draw_text_right(img, base.W - 1, y, ds, cfg.state_color(_DIR_STATE.get(ds, "elevated")), scale=2)
    return img
