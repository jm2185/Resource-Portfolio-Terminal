"""
M4 scrolling composite — Forge-Matrix M4. The ambient 'real layout': regime band pinned on top, the
watchlist crawling smoothly below. Pre-rendered as a LOOPING multi-frame anim.bin the device loops on its
own (motion on the MCU, values from the host) — never stream frames at scroll framerate.

Seamless loop: the tape is padded to an exact multiple of the per-frame step, so the frame after the last
wraps cleanly back to frame 0. The step is auto-fit to a frame budget so the payload stays inside the
device limits (<= ~90 frames, < 400 KB). Re-render + re-upload on data change, debounced (M5).
"""
from __future__ import annotations

from typing import List, Tuple

from PIL import Image

from .. import config as cfg
from .. import font
from ..contract import MatrixState
from ..encoder import MAX_FRAMES
from . import base

BAND_H = 6
LOWER_H = base.H - BAND_H
GAP_PX = 12                 # spacing (1x) between the tape's end and its wrap-around repeat
FRAME_BUDGET = 88          # <= 90 (spec); 88 * 4098 B ≈ 360 KB < 400 KB
PAYLOAD_BUDGET = 400 * 1024


def _build_tape(ms: MatrixState) -> Tuple[Image.Image, int]:
    """Render the watchlist as one wide multi-colour strip (height font.GLYPH_H): per name SYMBOL,
    ▲▼change magnitude (colour = sign), price. Returns (strip, content_width)."""
    items = ms.watchlist
    canvas = Image.new("RGB", (max(1, len(items)) * 80 + base.W, font.GLYPH_H), cfg.PALETTE["bg"])
    cx = 0
    for w in items:
        cx = font.draw_text(canvas, cx, 0, (w.symbol or "")[:4], cfg.PALETTE["text"]) + 1
        if w.change_pct is not None:
            up = w.change_pct >= 0
            col = cfg.PALETTE["calm"] if up else cfg.PALETTE["stress"]
            (base.draw_up if up else base.draw_down)(canvas, cx, 1, col)
            cx = font.draw_text(canvas, cx + 4, 0, f"{abs(w.change_pct):.1f}", col)
        cx = font.draw_text(canvas, cx + 2, 0, base.fmt_price(w.last), cfg.PALETTE["dim"])
        cx += GAP_PX
    width = max(cx, 1)
    return canvas.crop((0, 0, width, font.GLYPH_H)), width


def build_crawl(ms: MatrixState, *, budget: int = FRAME_BUDGET, delay_ms: int = 70,
                scale: int = 2) -> Tuple[List[Image.Image], List[int]]:
    """Build (frames, delays_ms) for the looping ambient crawl. ``scale`` enlarges the tape glyphs
    (2x = a bold, readable ticker). ``budget`` caps frames so the encoded payload stays within limits."""
    tape, w = _build_tape(ms)
    if scale > 1:
        tape = tape.resize((max(1, w * scale), font.GLYPH_H * scale), Image.NEAREST)
        w *= scale
    if w < base.W:                                   # ensure a full 64px window + wrap is possible
        pad = Image.new("RGB", (base.W + GAP_PX * max(1, scale), tape.height), cfg.PALETTE["bg"])
        pad.paste(tape, (0, 0))
        tape, w = pad, pad.width

    budget = max(1, min(budget, MAX_FRAMES))
    step = max(1, -(-w // budget))                   # ceil(w / budget) -> px scrolled per frame
    n = max(1, -(-w // step))                         # ceil(w / step)  -> frame count
    padded_w = n * step                              # pad to an exact multiple of step => seamless loop
    if padded_w > w:
        pad = Image.new("RGB", (padded_w, tape.height), cfg.PALETTE["bg"])
        pad.paste(tape, (0, 0))
        tape, w = pad, padded_w

    doubled = Image.new("RGB", (w * 2, tape.height), cfg.PALETTE["bg"])
    doubled.paste(tape, (0, 0))
    doubled.paste(tape, (w, 0))

    th = tape.height
    ty = BAND_H + max(0, (LOWER_H - th) // 2)         # vertically centre the tape in the lower region
    frames: List[Image.Image] = []
    for i in range(n):
        off = i * step
        frame = base.new_frame()
        base.draw_regime_band(frame, ms)
        frame.paste(doubled.crop((off, 0, off + base.W, th)), (0, ty))
        if ms.stale:
            base.draw_stale(frame)
        frames.append(frame)
    return frames, [delay_ms] * len(frames)
