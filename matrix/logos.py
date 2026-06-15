"""
Company-logo cache for the panel (Forge-Matrix). Logos are small bitmaps composited into a frame; the
original device showed them and they look good, so we keep them. Most TSX-V microcaps (AGA.V, GMX.TO…)
have NO logo in any feed, so the renderer always falls back to ticker text — never a blank.

Split so the RENDER path is pure + fast (cache-only, no network): ``load_logo`` reads a pre-cached PNG and
fits it to the requested size. The ORCHESTRATOR populates the cache out-of-band via ``fetch_logo``
(best-effort, budget-capped FMP profile ``image`` URL). Cache dir: data/matrix_logos/<TICKER>.png.
"""
from __future__ import annotations

import io
import os
from typing import Optional, Tuple

from PIL import Image

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "matrix_logos")


def _path(ticker: str) -> str:
    safe = str(ticker or "").upper().replace("/", "_").replace("\\", "_")
    return os.path.join(CACHE_DIR, f"{safe}.png")


def has_logo(ticker: str) -> bool:
    return bool(ticker) and os.path.exists(_path(ticker))


def cache_logo(ticker: str, src) -> Optional[str]:
    """Store a logo (a PIL Image or raw image bytes) for a ticker as an RGB PNG. Returns the path, or
    None on failure (an unreadable download must never crash the caller)."""
    try:
        img = Image.open(io.BytesIO(src)) if isinstance(src, (bytes, bytearray)) else src
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = _path(ticker)
        img.convert("RGB").save(path)
        return path
    except Exception:
        return None


def load_logo(ticker: str, size: Tuple[int, int]) -> Optional[Image.Image]:
    """The cached logo, fitted (contain + centre) onto a black ``size`` tile, or None if not cached.
    Pure/fast — this is the render path; it never hits the network."""
    if not has_logo(ticker):
        return None
    try:
        logo = Image.open(_path(ticker)).convert("RGB")
    except Exception:
        return None
    fitted = logo.copy()
    fitted.thumbnail(size, Image.LANCZOS)
    tile = Image.new("RGB", size, (0, 0, 0))
    tile.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    return tile


def fetch_logo(ticker: str, *, fmp_client=None, timeout: float = 8.0) -> bool:
    """Best-effort: resolve the logo URL from the FMP profile ``image`` field and cache it. Network- and
    key-dependent; returns False (caching nothing) on any failure, so the renderer falls back to text.
    The orchestrator calls this out-of-band, never in the render path."""
    try:
        import urllib.request
        if fmp_client is None:
            import fmp_client as _fc  # type: ignore
            fmp_client = _fc.FMPClient()
        data = (fmp_client.profile(ticker) or {}).get("data") or {}
        url = data.get("image")
        if not url:
            return False
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310
            return cache_logo(ticker, r.read()) is not None
    except Exception:
        return False
