"""
Per-name detail card (Forge-Matrix) — a big single-name screen the rotation can land on, and where a
company logo shines. Logo + symbol + price/change + rating/directive + asymmetry (ρ/φ) + next catalyst,
all at 128x64. Logo is cache-only (text/space fallback when absent — most microcaps have none).
"""
from __future__ import annotations

from typing import Optional

from .. import config as cfg
from .. import font, logos
from ..contract import MatrixState, WatchItem
from . import base
from .asymmetry import _phi_color, _rho_color
from .conviction_board import _DIR_STATE, _dir_short

_LOGO = (30, 30)


def detail_card(ms: MatrixState, item: Optional[WatchItem]):
    img = base.new_frame()
    if ms.stale:
        base.draw_stale(img)
    if item is None:
        font.draw_text(img, 2, 4, "NO HOLDINGS", cfg.PALETTE["dim"], scale=2)
        return img

    logo = logos.load_logo(item.ticker or item.symbol, _LOGO)
    if logo is not None:
        img.paste(logo, (2, 2))

    x0 = 2 + _LOGO[0] + 4                                   # right of the logo
    font.draw_text(img, x0, 2, (item.symbol or "")[:6], cfg.PALETTE["text"], scale=2)
    if item.last is not None:
        font.draw_text(img, x0, 16, "$" + base.fmt_price(item.last), cfg.PALETTE["dim"], scale=2)
    if item.change_pct is not None:
        up = item.change_pct >= 0
        col = cfg.PALETTE["calm"] if up else cfg.PALETTE["stress"]
        font.draw_text_right(img, base.W - 1, 16, f"{'+' if up else '-'}{abs(item.change_pct):.1f}%", col, scale=2)

    y = 36                                                  # rating + directive (full width, below the logo)
    if item.rating is not None:
        font.draw_text(img, 2, y, f"R{item.rating:.1f}", cfg.PALETTE["text"], scale=2)
    ds = _dir_short(item.directive)
    if ds:
        font.draw_text_right(img, base.W - 1, y, ds, cfg.state_color(_DIR_STATE.get(ds, "elevated")), scale=2)

    y = 50                                                  # asymmetry + next catalyst
    if item.rho is not None:
        font.draw_text(img, 2, y, f"P{item.rho:.1f}", _rho_color(item.rho), scale=2)
    if item.floor_coverage is not None:
        font.draw_text(img, 52, y, f"F{item.floor_coverage:.1f}", _phi_color(item.floor_coverage), scale=2)
    if ms.next_catalyst is not None:
        font.draw_text_right(img, base.W - 1, y, f"{ms.next_catalyst.days}D", cfg.PALETTE["accent"], scale=2)
    return img


def render(ms: MatrixState):
    """SCREENS-compatible: the top holding's detail card (rotation through names is orchestrator-driven)."""
    holds = [w for w in ms.watchlist if not w.eval_only]
    return detail_card(ms, holds[0] if holds else None)
