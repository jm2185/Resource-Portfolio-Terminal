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

_ROWS_Y = [3, 15, 27, 39, 51]   # 128x64: 5 indices, scale-2

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


def _select(ms: MatrixState):
    """The operator-chosen indices (config.STRESS_SHOW), in that order; fall back to engine order so the
    screen is never blank when data exists."""
    by_label = {s.label: s for s in ms.stress}
    chosen = [by_label[lbl] for lbl in cfg.STRESS_SHOW if lbl in by_label]
    return chosen if chosen else list(ms.stress)


def render(ms: MatrixState):
    img = base.new_frame()
    if ms.stale:
        base.draw_stale(img)
    for s, y in zip(_select(ms)[:5], _ROWS_Y):
        col = cfg.state_color(s.state)
        font.draw_text(img, 2, y, _abbr(s.label), col, scale=2)
        font.draw_text_right(img, base.W - 1, y, _fmt_val(s.value), cfg.PALETTE["text"], scale=2)
    return img
