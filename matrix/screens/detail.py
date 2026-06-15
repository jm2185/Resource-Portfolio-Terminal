"""
Per-name detail card (Forge-Matrix) — a big single-name screen the rotation can land on, and where a
company logo shines. Logo + symbol + price/change + rating/directive + asymmetry (ρ/φ) + next catalyst,
all at 128x64. Logo is cache-only (text/space fallback when absent — most microcaps have none).
"""
from __future__ import annotations

from typing import List, Optional

from .. import config as cfg
from .. import font, logos
from ..contract import MatrixState, WatchItem
from . import base
from .asymmetry import _phi_color, _rho_color
from .conviction_board import _DIR_STATE, _dir_short

_LOGO = (26, 26)


def detail_card(ms: MatrixState, item: Optional[WatchItem], ohlc=None, spark: Optional[List[float]] = None):
    """Logo + symbol + $price/change (top) · candlestick chart (mid; sparkline fallback) · compact
    rating/directive/ρ/φ (bottom). ``ohlc`` = (o,h,l,c) bars (prices.yfinance_ohlc); ``spark`` = closes
    fallback; absent -> the chart area is blank."""
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

    if ohlc and len(ohlc) >= 2:                            # candlestick chart (the native-terminal look)
        base.draw_candles(img, 2, 30, base.W - 4, 21, ohlc)
    else:                                                  # fallback: line sparkline from closes
        vals = [v for v in (spark or []) if v is not None]
        if len(vals) >= 2:
            trend = cfg.PALETTE["calm"] if vals[-1] >= vals[0] else cfg.PALETTE["stress"]
            base.draw_sparkline(img, 2, 30, base.W - 4, 21, vals, trend, axis=cfg.PALETTE["dim"])

    y = 53                                                  # compact stats row (scale 1): RTG / call / PAY / FLR
    if item.rating is not None:
        font.draw_text(img, 2, y, f"RTG{item.rating:.1f}", cfg.PALETTE["text"])
    ds = _dir_short(item.directive)
    if ds:
        font.draw_text(img, 30, y, ds, cfg.state_color(_DIR_STATE.get(ds, "elevated")))
    if item.rho is not None:
        font.draw_text(img, 62, y, f"PAY{item.rho:.1f}", _rho_color(item.rho))
    if item.floor_coverage is not None:
        font.draw_text(img, 94, y, f"FLR{item.floor_coverage:.1f}", _phi_color(item.floor_coverage))
    return img


def render(ms: MatrixState):
    """SCREENS-compatible: the top holding's detail card (rotation through names is orchestrator-driven)."""
    holds = [w for w in ms.watchlist if not w.eval_only]
    return detail_card(ms, holds[0] if holds else None)
