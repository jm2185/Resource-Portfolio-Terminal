"""
Regime band + watchlist (static) — Forge-Matrix M3. The ambient default's still frame; M4 adds the
MCU-looped crawl. Top band = regime tilt (coloured) + MRI (stress-overlaid); rows = the watchlist in the
engine's conviction order, price right-aligned, ▲▼ from change sign when present (a dim gap otherwise).
"""
from __future__ import annotations

from .. import config as cfg
from .. import font
from ..contract import MatrixState
from . import base

_ROWS_Y = [7, 13, 19, 25]


def render(ms: MatrixState):
    img = base.new_frame()
    base.draw_regime_band(img, ms)

    for w, y in zip(ms.watchlist[:4], _ROWS_Y):
        font.draw_text(img, 1, y, (w.symbol or "")[:4], cfg.PALETTE["text"])
        if w.change_pct is not None:                       # ▲▼ direction + magnitude (colour = sign)
            up = w.change_pct >= 0
            col = cfg.PALETTE["calm"] if up else cfg.PALETTE["stress"]
            (base.draw_up if up else base.draw_down)(img, 18, y + 1, col)
            font.draw_text(img, 23, y, f"{abs(w.change_pct):.1f}", col)
        font.draw_text_right(img, base.W - 1, y, base.fmt_price(w.last), cfg.PALETTE["dim"])

    if ms.stale:
        base.draw_stale(img)
    return img
