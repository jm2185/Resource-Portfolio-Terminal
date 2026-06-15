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

_ROWS_Y = [16, 29, 42, 55]   # 128x64: band (scale-2) + 4 big rows


def render(ms: MatrixState):
    img = base.new_frame()
    base.draw_regime_band(img, ms)

    holds = [w for w in ms.watchlist if not w.eval_only]
    for w, y in zip(holds[:4], _ROWS_Y):
        font.draw_text(img, 2, y, (w.symbol or "")[:5], cfg.PALETTE["text"], scale=2)
        if w.change_pct is not None:                       # signed % (colour = direction)
            up = w.change_pct >= 0
            col = cfg.PALETTE["calm"] if up else cfg.PALETTE["stress"]
            font.draw_text(img, 44, y, f"{'+' if up else '-'}{abs(w.change_pct):.1f}%", col, scale=2)
        font.draw_text_right(img, base.W - 1, y, "$" + base.fmt_price(w.last), cfg.PALETTE["dim"], scale=2)

    if ms.stale:
        base.draw_stale(img)
    return img
