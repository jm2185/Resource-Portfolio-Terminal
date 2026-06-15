"""
Margin-of-safety / asymmetry — Forge-Matrix M3. Per name: P = ρ payoff ratio, F = φ REP-floor coverage
(how far above the stressed floor it trades). The book's core lens — downside protection + asymmetric
upside — as two colour-coded numbers. Colour cutoffs are config defaults (engine/config-owned), not
re-decided here.
"""
from __future__ import annotations

from .. import config as cfg
from .. import font
from ..contract import MatrixState
from . import base

_ROWS_Y = [7, 13, 19, 25]


def _rho_color(r):
    if r is None:
        return cfg.PALETTE["dim"]
    return cfg.PALETTE["calm"] if r >= cfg.RHO_GOOD else (cfg.PALETTE["elevated"] if r >= 1.0
                                                          else cfg.PALETTE["stress"])


def _phi_color(p):
    if p is None:
        return cfg.PALETTE["dim"]
    return cfg.PALETTE["calm"] if p >= cfg.PHI_GOOD else (cfg.PALETTE["elevated"] if p >= 1.0
                                                          else cfg.PALETTE["stress"])


def render(ms: MatrixState):
    img = base.new_frame()
    font.draw_text(img, 1, 1, "SAFETY", cfg.PALETTE["dim"])
    if ms.stale:
        base.draw_stale(img)
    for w, y in zip(ms.watchlist[:4], _ROWS_Y):
        font.draw_text(img, 1, y, (w.symbol or "")[:4], cfg.PALETTE["text"])
        if w.rho is not None:
            font.draw_text(img, 21, y, f"P{w.rho:.1f}", _rho_color(w.rho))      # ρ payoff
        if w.floor_coverage is not None:
            font.draw_text_right(img, base.W - 1, y, f"F{w.floor_coverage:.1f}", _phi_color(w.floor_coverage))  # φ
    return img
