"""
NO ENGINE card — what the panel shows when there is no engine reading at all.

The failure this exists for: ``MatrixState`` defaults ``net_tilt`` to "BALANCED", so an engine-down
state rendered through the ordinary screens draws a calm balanced regime band over empty rows — a
blank BALANCED screen, frozen (nothing changes, so change-detection skips every subsequent upload).
The only tell was ``draw_stale``'s 2x2 red dot: four pixels, and it means "feed late", not "no data".

On a desk panel that is a misreport, not a cosmetic gap: BALANCED is a regime CLAIM. This card makes
the absence explicit and unmistakable at a glance, and says how long the host has been blind so a
brief restart is distinguishable from a daemon that has been talking to nothing all day.
"""
from __future__ import annotations

import time

from .. import config as cfg
from .. import font
from ..contract import MatrixState
from . import base


def _blind_for(ms: MatrixState, now=None) -> str:
    """Compact 'how long without a reading' — the frame's own build time, so it stays honest even if
    the daemon has been looping on nothing. Empty when unknown (never fabricate an age)."""
    if not ms.generated_at:
        return ""
    secs = (time.time() if now is None else now) - ms.generated_at
    if secs < 0:
        return ""
    if secs < 90:
        return f"{int(secs)}s"
    if secs < 5400:
        return f"{int(secs // 60)}m"
    return f"{int(secs // 3600)}h"


def _endpoint(max_chars: int = 30) -> str:
    """``host:port/state`` for the configured engine, scheme stripped to save glyphs. Clipped from the
    LEFT if long, so the port — the half that is usually wrong — always survives."""
    url = str(cfg.ENGINE_URL or "").split("://")[-1].rstrip("/") + "/state"
    return url if len(url) <= max_chars else "\u2026" + url[-(max_chars - 1):]


def render(ms: MatrixState, now=None):
    img = base.new_frame()
    stress = cfg.PALETTE["stress"]

    # A full-width red rule top and bottom: unmistakable across a room, and nothing like any live
    # screen — no live state paints the panel's edges red.
    for y in (0, 1, base.H - 2, base.H - 1):
        for x in range(base.W):
            img.putpixel((x, y), stress)

    font.draw_text(img, 4, 12, "NO ENGINE", stress, scale=2)
    font.draw_text(img, 4, 30, "no /state reading", cfg.PALETTE["dim"], scale=1)

    blind = _blind_for(ms, now=now)
    if blind:
        font.draw_text(img, 4, 42, f"blind {blind}", cfg.PALETTE["elevated"], scale=1)

    # The URL THIS daemon polls — the single most diagnostic thing the glass can carry. A wrong host
    # or port is visible instantly, and it distinguishes "pointed somewhere wrong" from "pointed
    # right, nothing published yet" (the engine serves /state as an empty 200 until its first publish
    # completes, so 'engine is running' does NOT imply 'engine has published'). This is a fact about
    # the daemon's own configuration, not an engine reading, so it never fabricates a number.
    font.draw_text(img, 4, 52, _endpoint(), cfg.PALETTE["dim"], scale=1)
    return img
