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

_ROWS_Y = [14, 27, 40, 53]   # 128x64: small title + 4 big (scale-2) rows


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
    font.draw_text(img, 2, 1, "SAFETY", cfg.PALETTE["dim"])
    if ms.stale:
        base.draw_stale(img)
    holds = [w for w in ms.watchlist if not w.eval_only]
    for w, y in zip(holds[:4], _ROWS_Y):                   # SYM  PAY{ρ}  FLR{φ}, packed to fit 128px
        cx = font.draw_text(img, 0, y, (w.symbol or "")[:4], cfg.PALETTE["text"], scale=2)
        if w.rho is not None:
            cx = font.draw_text(img, cx, y, f"PAY{w.rho:.1f}", _rho_color(w.rho), scale=2)
        if w.floor_coverage is not None:
            font.draw_text(img, cx, y, f"FLR{w.floor_coverage:.1f}", _phi_color(w.floor_coverage), scale=2)
    return img
