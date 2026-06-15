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


def _finnhub_logo_url(ticker: str, key: str, timeout: float):
    if not key:
        return None
    try:
        import json
        import urllib.parse
        import urllib.request
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={urllib.parse.quote(ticker)}&token={key}"
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310
            return (json.loads(r.read().decode("utf-8")) or {}).get("logo") or None
    except Exception:
        return None


def _fmp_logo_url(ticker: str, fmp_client, timeout: float):
    try:
        if fmp_client is None:
            import fmp_client as _fc  # type: ignore
            client = _fc.FMPClient()
            if not client.key:                 # no FMP key -> skip (no network)
                return None
            fmp_client = client
        return ((fmp_client.profile(ticker) or {}).get("data") or {}).get("image") or None
    except Exception:
        return None


def fetch_logo(ticker: str, *, finnhub_key=None, fmp_client=None, timeout: float = 8.0) -> bool:
    """Best-effort: resolve the logo URL (Finnhub profile2 ``logo`` first, then FMP profile ``image``)
    and cache it. With no key for either source it returns False WITHOUT any network, so the renderer
    falls back to text. The orchestrator calls this out-of-band, never in the render path."""
    from .prices import env_key
    url = (_finnhub_logo_url(ticker, finnhub_key if finnhub_key is not None else env_key("FINNHUB_API_KEY"), timeout)
           or _fmp_logo_url(ticker, fmp_client, timeout))
    if not url:
        return False
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310
            return cache_logo(ticker, r.read()) is not None
    except Exception:
        return False
