"""
Screen-render helpers (Forge-Matrix M3) — shared primitives every screen composes from.

Each screen is a pure ``render(MatrixState) -> PIL.Image`` of size 64x32; the orchestrator (M5) picks
which to show and hands it to the encoder. Colours/thresholds come from ``matrix.config`` (engine-owned
defaults), never hardcoded here. Robust to missing data: None values are drawn as a dim dash or skipped,
never faked.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .. import config as cfg
from .. import font

W, H = 128, 64


def new_frame() -> Image.Image:
    return Image.new("RGB", (W, H), cfg.PALETTE["bg"])


def _set(px, x: int, y: int, color) -> None:
    if 0 <= x < W and 0 <= y < H:
        px[x, y] = color


def draw_up(img: Image.Image, x: int, y: int, color) -> None:
    """A 3x2 upward triangle (rising change)."""
    px = img.load()
    _set(px, x + 1, y, color)
    for dx in range(3):
        _set(px, x + dx, y + 1, color)


def draw_down(img: Image.Image, x: int, y: int, color) -> None:
    """A 3x2 downward triangle (falling change)."""
    px = img.load()
    for dx in range(3):
        _set(px, x + dx, y, color)
    _set(px, x + 1, y + 1, color)


def draw_bar(img: Image.Image, x: int, y: int, w: int, h: int, frac: float, color, bg=None) -> None:
    d = ImageDraw.Draw(img)
    if bg is not None:
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=bg)
    fw = max(0, min(w, int(round(w * (frac or 0.0)))))
    if fw > 0:
        d.rectangle([x, y, x + fw - 1, y + h - 1], fill=color)


def draw_sparkline(img: Image.Image, x: int, y: int, w: int, h: int, values, color, axis=None) -> None:
    """A line sparkline of ``values`` fitted into the (x,y,w,h) box (auto-scaled to min/max). Candlesticks
    are too dense for 64px tall; a trend line reads cleanly. Optional dim baseline at the first value."""
    vals = [float(v) for v in (values or []) if v is not None]
    if len(vals) < 2 or w < 2 or h < 2:
        return
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = [(x + int(i / (n - 1) * (w - 1)), y + int((1 - (v - lo) / rng) * (h - 1))) for i, v in enumerate(vals)]
    d = ImageDraw.Draw(img)
    if axis is not None:                                  # dim flat reference at the opening value
        ay = y + int((1 - (vals[0] - lo) / rng) * (h - 1))
        for xx in range(x, x + w, 3):
            img.load()[xx, ay] = axis
    d.line(pts, fill=color, width=1)


def draw_candles(img: Image.Image, x: int, y: int, w: int, h: int, ohlc,
                 up=None, down=None) -> None:
    """Candlestick chart of (open, high, low, close) bars fitted into (x,y,w,h), auto-scaled to the
    window's high/low. Green up / red down; high-low wick + open-close body. The native-terminal look."""
    bars = [(float(o), float(hi), float(lo), float(c)) for (o, hi, lo, c) in (ohlc or [])
            if None not in (o, hi, lo, c)]
    if len(bars) < 1 or w < 3 or h < 3:
        return
    up = up or cfg.PALETTE["calm"]
    down = down or cfg.PALETTE["stress"]
    lo_all = min(b[2] for b in bars)
    hi_all = max(b[1] for b in bars)
    rng = (hi_all - lo_all) or 1.0
    n = len(bars)
    slot = max(1, w // n)                                  # px per candle (body + 1px gap)
    body_w = max(1, slot - 1)
    d = ImageDraw.Draw(img)

    def yof(v):
        return y + int((1 - (v - lo_all) / rng) * (h - 1))

    for i, (o, hi, lo, c) in enumerate(bars):
        cx = x + i * slot
        col = up if c >= o else down
        wx = cx + body_w // 2
        d.line([(wx, yof(hi)), (wx, yof(lo))], fill=col, width=1)   # wick
        top, bot = sorted((yof(o), yof(c)))
        if bot == top:
            bot = top + 1                                  # doji -> 1px body
        d.rectangle([cx, top, cx + body_w - 1, bot], fill=col)      # body


def draw_stale(img: Image.Image) -> None:
    """A 2x2 red dot in the top-right corner — the feed-is-late marker (M8 stale degradation)."""
    px = img.load()
    for dx in range(2):
        for dy in range(2):
            _set(px, W - 1 - dx, dy, cfg.PALETTE["stress"])


def tilt_short(net_tilt: str) -> str:
    return {"RISK-ON": "ON", "RISK-OFF": "OFF", "BALANCED": "BAL"}.get(net_tilt, str(net_tilt)[:3])


def fmt_price(p) -> str:
    if p is None:
        return "--"
    return f"{p:.2f}" if abs(p) < 100 else f"{p:.0f}"


def draw_regime_band(img: Image.Image, ms) -> None:
    """The pinned top row: regime tilt as coloured TEXT (no filled banner) + MRI (stress-overlaid).
    Full word ('RISK-OFF', not 'OFF'). Shared by the static watchlist screen and the M4 crawl."""
    font.draw_text(img, 2, 2, str(ms.net_tilt or "")[:10], cfg.tilt_color(ms.net_tilt), scale=2)
    if ms.mri is not None:
        mc = cfg.PALETTE["stress"] if ms.mri >= cfg.MRI_STRESS_THRESHOLD else cfg.PALETTE["text"]
        font.draw_text_right(img, W - 1, 2, f"MRI {ms.mri:.0f}", mc, scale=2)
