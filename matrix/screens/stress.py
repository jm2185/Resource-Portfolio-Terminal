"""
Stress complex — Forge-Matrix M3. One row per macro/stress index (engine importance order), the label
coloured by the engine-bucketed state (calm/elevated/stress -> green/amber/red) and the value
right-aligned. The renderer NEVER re-thresholds: the colour state is the engine's call.
"""
from __future__ import annotations

from .. import config as cfg
from .. import font
from ..contract import MatrixState
from . import base

_ROWS_Y = [7, 13, 19, 25]

# Hard 64px abbreviations for the engine's verbose macro labels (the contract's intent: abbreviate near
# the data; until the engine ships a matrix_label, map the known ones and truncate the rest).
_ABBR = {
    "VIX": "VIX", "Gold/Silver": "GSR", "Copper/Gold ×1k": "CU/AU", "DXY/Gold ×1k": "DXY",
    "Real Yield": "RY", "SOFR Spread": "SOFR", "HY Spread": "HY", "30Y–10Y": "CURVE",
    "CFTC Net %ile": "CFTC", "VIX Term (3M/1M)": "VXTM",
}


def _abbr(label: str) -> str:
    return _ABBR.get(label, str(label or "?")[:5].upper())


def _fmt_val(v) -> str:
    if v is None:
        return "--"
    return f"{v:.1f}" if abs(v) < 1000 else f"{v:.0f}"


def render(ms: MatrixState):
    img = base.new_frame()
    font.draw_text(img, 1, 1, "STRESS", cfg.PALETTE["dim"])
    if ms.stale:
        base.draw_stale(img)
    for s, y in zip(ms.stress[:4], _ROWS_Y):
        col = cfg.state_color(s.state)
        font.draw_text(img, 1, y, _abbr(s.label), col)
        font.draw_text_right(img, base.W - 1, y, _fmt_val(s.value), cfg.PALETTE["text"])
    return img
