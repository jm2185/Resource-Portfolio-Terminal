"""
Scrolling composites — Forge-Matrix M4 / ambient cockpit.

Both are pre-rendered as a LOOPING anim.bin the device loops on its own (motion on the MCU, values from
the host):
  * build_crawl   — regime band pinned + a single watchlist crawl (the simple ambient).
  * build_ambient — the cockpit-at-a-glance: a STATIC macro dashboard (regime + MRI + VIX/USD/yields/…)
                    over a BOTTOM crawl of the names (holdings bright, monitored/EVAL dim after a WATCH tag).

Seamless loop: the tape is padded to a whole number of per-frame steps; the step is auto-fit to a frame
budget so the payload stays inside the device limits (<= ~90 frames, < 400 KB). Re-render on data change.
"""
from __future__ import annotations

from typing import Callable, List, Sequence, Tuple

from PIL import Image

from .. import config as cfg
from .. import font
from ..contract import MatrixState, WatchItem
from ..encoder import MAX_FRAMES, frame_bytes
from . import base

GAP_PX = 12
FRAME_BUDGET = 88
PAYLOAD_BUDGET = 400 * 1024

# macro_tape label -> 64px tag for the dashboard cells
_MACRO_ABBR = {"VIX": "VIX", "Real Yield": "RY", "DXY": "DXY", "DXY/Gold ×1k": "USD", "HY Spread": "HY",
               "30Y–10Y": "CURV", "Gold/Silver": "GSR", "Copper/Gold ×1k": "CU",
               "SOFR Spread": "SOFR", "CFTC Net %ile": "CFTC", "VIX Term (3M/1M)": "VXTM"}


def _fmt_val(v) -> str:
    if v is None:
        return "--"
    return f"{v:.0f}" if abs(v) >= 10 else f"{v:.1f}"


# ---- generic seamless scroller ------------------------------------------------------------------
def _scroll_loop(static_draw: Callable[[Image.Image], None], tape: Image.Image, tape_w: int, ty: int,
                 *, budget: int, delay_ms: int) -> Tuple[List[Image.Image], List[int]]:
    """A static layer (redrawn each frame) + ``tape`` windowed and scrolled at vertical offset ``ty``.
    ``tape`` is already at final scale. Padded to a whole number of steps so the loop is seamless."""
    if tape_w < base.W:
        pad = Image.new("RGB", (base.W + GAP_PX, tape.height), cfg.PALETTE["bg"])
        pad.paste(tape, (0, 0))
        tape, tape_w = pad, pad.width
    budget = max(1, min(budget, MAX_FRAMES, PAYLOAD_BUDGET // frame_bytes()))   # payload-capped (16KB/frame @128x64)
    step = max(1, -(-tape_w // budget))               # ceil(w / budget) px scrolled per frame
    n = max(1, -(-tape_w // step))                      # frame count
    padded = n * step
    if padded > tape_w:
        pad = Image.new("RGB", (padded, tape.height), cfg.PALETTE["bg"])
        pad.paste(tape, (0, 0))
        tape, tape_w = pad, padded
    doubled = Image.new("RGB", (tape_w * 2, tape.height), cfg.PALETTE["bg"])
    doubled.paste(tape, (0, 0))
    doubled.paste(tape, (tape_w, 0))
    frames: List[Image.Image] = []
    for i in range(n):
        off = i * step
        f = base.new_frame()
        static_draw(f)
        f.paste(doubled.crop((off, 0, off + base.W, tape.height)), (0, ty))
        frames.append(f)
    return frames, [delay_ms] * n


# ---- the watchlist tape -------------------------------------------------------------------------
def _tape_item(canvas: Image.Image, cx: int, w: WatchItem, *, dim: bool = False) -> int:
    """Draw one item: SYMBOL (white, or dim for monitored), $price (dim), signed change% (green/red)."""
    cx = font.draw_text(canvas, cx, 0, (w.symbol or "")[:4], cfg.PALETTE["dim"] if dim else cfg.PALETTE["text"]) + 2
    cx = font.draw_text(canvas, cx, 0, "$" + base.fmt_price(w.last), cfg.PALETTE["dim"]) + 3
    if w.change_pct is not None:
        up = w.change_pct >= 0
        ccol = cfg.PALETTE["calm"] if up else cfg.PALETTE["stress"]
        cx = font.draw_text(canvas, cx, 0, f"{'+' if up else '-'}{abs(w.change_pct):.1f}%", ccol)
    return cx + GAP_PX


def _build_tape(items: Sequence[WatchItem], *, monitored: Sequence[WatchItem] = (), scale: int = 2):
    n = len(items) + len(monitored) + 1
    canvas = Image.new("RGB", (n * 100 + base.W, font.GLYPH_H), cfg.PALETTE["bg"])
    cx = 0
    for w in items:
        cx = _tape_item(canvas, cx, w)
    for w in monitored:                              # bench rides the crawl dim (no WATCH separator label)
        cx = _tape_item(canvas, cx, w, dim=True)
    width = max(cx, 1)
    tape = canvas.crop((0, 0, width, font.GLYPH_H))
    if scale > 1:
        tape = tape.resize((width * scale, font.GLYPH_H * scale), Image.NEAREST)
        width *= scale
    return tape, width


# ---- composite 1: simple band + crawl -----------------------------------------------------------
def build_crawl(ms: MatrixState, *, budget: int = FRAME_BUDGET, delay_ms: int = None, scale: int = None):
    """Regime band pinned + the holdings crawl, vertically centred below the band."""
    delay_ms = cfg.CRAWL_DELAY_MS if delay_ms is None else delay_ms
    scale = cfg.CRAWL_SCALE if scale is None else scale
    holdings = [w for w in ms.watchlist if not w.eval_only] or list(ms.watchlist)
    tape, w = _build_tape(holdings, scale=scale)
    ty = 6 + max(0, ((base.H - 6) - tape.height) // 2)

    def static(f):
        base.draw_regime_band(f, ms)
        if ms.stale:
            base.draw_stale(f)
    return _scroll_loop(static, tape, w, ty, budget=budget, delay_ms=delay_ms)


# ---- composite 2: macro dashboard + bottom crawl (the cockpit) ----------------------------------
def _draw_dashboard(img: Image.Image, ms: MatrixState) -> None:
    base.draw_regime_band(img, ms)                       # band y2-11 (scale 2)
    by = {s.label: s for s in ms.stress}
    cells = [by[lbl] for lbl in cfg.AMBIENT_MACRO if lbl in by][:6]
    rows_y = (14, 25, 36)                                 # three macro rows (scale 2), 2 columns = 6 cells
    for i, s in enumerate(cells):                         # 2x3 macro grid, label coloured by state
        x = 2 + (i % 2) * 64
        y = rows_y[min(i // 2, len(rows_y) - 1)]
        font.draw_text(img, x, y, _MACRO_ABBR.get(s.label, str(s.label)[:4].upper()),
                       cfg.state_color(s.state), scale=2)
        font.draw_text_right(img, x + 62, y, _fmt_val(s.value), cfg.PALETTE["text"], scale=2)
    px = img.load()                                      # dim dashed divider above the crawl
    for xx in range(0, base.W, 3):
        px[xx, 47] = cfg.PALETTE["dim"]
    if ms.stale:
        base.draw_stale(img)


def build_ambient(ms: MatrixState, *, budget: int = FRAME_BUDGET, delay_ms: int = None, scale: int = None):
    """Cockpit-at-a-glance: static macro dashboard (top) + bottom crawl (holdings bright, monitored dim)."""
    delay_ms = cfg.CRAWL_DELAY_MS if delay_ms is None else delay_ms
    scale = cfg.AMBIENT_CRAWL_SCALE if scale is None else scale
    holdings = [w for w in ms.watchlist if not w.eval_only]
    monitored = [w for w in ms.watchlist if w.eval_only]
    tape, w = _build_tape(holdings, monitored=monitored, scale=scale)
    ty = 49 + max(0, ((base.H - 49) - tape.height) // 2)   # bottom crawl band (below the 3-row macro grid)
    return _scroll_loop(lambda f: _draw_dashboard(f, ms), tape, w, ty, budget=budget, delay_ms=delay_ms)
