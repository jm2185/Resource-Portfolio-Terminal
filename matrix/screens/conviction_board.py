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

_ROWS_Y = [1, 9, 17, 25]   # title row reclaimed: 4 names spread over the full height

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
    first = str(directive).split("—")[0].split("-")[0].strip().split()[0].upper() if str(directive).strip() else ""
    return _DIR_SHORT.get(first, first[:4])


def render(ms: MatrixState):
    img = base.new_frame()
    if ms.stale:
        base.draw_stale(img)
    for w, y in zip(ms.watchlist[:4], _ROWS_Y):
        font.draw_text(img, 1, y, (w.symbol or "")[:4], cfg.PALETTE["text"])
        if w.rating is not None:
            font.draw_text(img, 21, y, f"{w.rating:.1f}", cfg.PALETTE["text"])
        ds = _dir_short(w.directive)
        if ds:
            font.draw_text_right(img, base.W - 1, y, ds, cfg.state_color(_DIR_STATE.get(ds, "elevated")))
    return img
