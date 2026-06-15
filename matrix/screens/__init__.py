"""
Screen renderers (Forge-Matrix M3). Each is a pure ``render(MatrixState) -> PIL.Image`` (64x32). The
set is deliberately selective for a quick-monitoring panel: the ambient regime band + watchlist crawl,
and three rotating boards — conviction, margin-of-safety/asymmetry, stress. (Barbell and catalyst were
cut as not earning the limited space.)
"""
from __future__ import annotations

from . import base
from .asymmetry import render as asymmetry
from .conviction_board import render as conviction_board
from .crawl import build_ambient, build_crawl
from .regime_watchlist import render as regime_watchlist
from .stress import render as stress

# Rotation set for the orchestrator's cycle layer (M5). regime_watchlist is the ambient default.
SCREENS = {
    "regime_watchlist": regime_watchlist,
    "conviction_board": conviction_board,
    "asymmetry": asymmetry,
    "stress": stress,
}

__all__ = ["regime_watchlist", "conviction_board", "asymmetry", "stress", "build_crawl", "SCREENS", "base"]
