"""
M5 orchestrator — the daemon that makes the panel live.

The loop (house rule: animation on the MCU, data from the host):
  poll engine /state  +  prices (holdings day-change + the bench)
    -> build_matrix_state
    -> render the active view (rotates: ambient cockpit + conviction/safety/stress)
    -> encode anim.bin  ->  POST /upload
The device loops the uploaded anim.bin on its own; VALUES refresh each re-upload (debounced).

Device-free + testable: every side effect (state fetch, price fetch, bench load, upload, the device
button/focus state, the clock) is injected, so ``tick()`` unit-tests with mocks. The defaults use stdlib
urllib for /state and ``device.upload_anim`` for /upload (lazy-imported) — importing this module needs no
network. Discipline: change-detection (skip identical state), a min-upload interval (flash-wear guard),
timed rotation, an optional device-button hold, and graceful degradation (engine down -> a stale frame).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from . import config as cfg
from .adapter import build_matrix_state
from .bench import load_bench
from .contract import MatrixState
from .encoder import encode_anim
from .prices import yfinance_price_fetcher
from .screens import SCREENS
from .screens.crawl import build_ambient


def _http_get_json(url: str, timeout: float = 2.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:   # noqa: S310 (localhost engine)
        return json.loads(resp.read().decode("utf-8"))


def fmp_profile_fetcher(tickers: List[str], client=None) -> Dict[str, dict]:
    """Best-effort {ticker: {last, change_pct}} via the engine's budget-capped FMP client (free-tier
    ``profile``; ``quote`` is paid). Cached + quota-guarded, so cadence is slow (hourly-ish), not
    real-time — fine for an ambient panel. Degrades to {} on any failure. NOTE: verify the profile
    field names ('price' / 'changesPercentage' / 'changes') against a live call; absent -> change None."""
    out: Dict[str, dict] = {}
    try:
        if client is None:
            import fmp_client  # type: ignore
            client = fmp_client.FMPClient()
    except Exception:
        return out
    for tk in tickers:
        try:
            d = (client.profile(tk) or {}).get("data") or {}
            last = d.get("price")
            chg = d.get("changesPercentage")
            if chg is None and d.get("changes") is not None and last:
                base = float(last) - float(d["changes"])
                chg = (float(d["changes"]) / base * 100.0) if base else None
            out[tk] = {"last": last, "change_pct": chg}
        except Exception:
            continue
    return out


class MatrixOrchestrator:
    """One ``tick()`` = one cycle; ``run()`` wraps it in a poll loop. Inject fetchers/uploader/clock."""

    def __init__(self, *, engine_url: Optional[str] = None, host: Optional[str] = None,
                 views: Optional[List[str]] = None,
                 state_fetcher: Optional[Callable[[], Optional[dict]]] = None,
                 price_fetcher: Optional[Callable[[List[str]], Dict[str, dict]]] = None,
                 bench_loader: Optional[Callable[[], List[str]]] = None,
                 uploader: Optional[Callable[[bytes], None]] = None,
                 focus_fetcher: Optional[Callable[[], bool]] = None,
                 cycle_interval: Optional[float] = None,
                 min_upload_interval: Optional[float] = None,
                 clock: Callable[[], float] = time.time):
        self.engine_url = (engine_url or cfg.ENGINE_URL).rstrip("/")
        self.host = host or cfg.DEVICE_HOST
        self.views = list(views or cfg.ROTATION)
        self.state_fetcher = state_fetcher or self._default_state_fetcher
        self.price_fetcher = price_fetcher or yfinance_price_fetcher   # default: yfinance (handles .V/.TO)
        self.bench_loader = bench_loader or load_bench
        self.uploader = uploader or self._default_uploader
        self.focus_fetcher = focus_fetcher                          # device button -> hold the current view
        self.cycle_interval = cycle_interval if cycle_interval is not None else cfg.CYCLE_INTERVAL_S
        self.min_upload_interval = (min_upload_interval if min_upload_interval is not None
                                    else cfg.MIN_UPLOAD_INTERVAL_S)
        self.clock = clock
        self._view_idx = 0
        self._last_rotate = self.clock()
        self._last_upload = -1e9
        self._last_sig: Optional[tuple] = None

    # ---- default I/O (lazy; tests inject mocks) ----
    def _default_state_fetcher(self) -> Optional[dict]:
        try:
            return _http_get_json(f"{self.engine_url}/state")
        except Exception:
            return None

    def _default_uploader(self, payload: bytes) -> None:
        from . import device
        device.upload_anim(self.host, payload)

    def _focus_active(self) -> bool:
        """Device button repurpose: when the toggle is on, freeze rotation on the current view."""
        if not self.focus_fetcher:
            return False
        try:
            return bool(self.focus_fetcher())
        except Exception:
            return False

    # ---- build the live MatrixState (engine /state + injected prices + the bench) ----
    def build_state(self) -> MatrixState:
        try:
            state = self.state_fetcher()
        except Exception:
            state = None
        if not state:
            return build_matrix_state(None, now=self.clock())
        baskets = (state.get("conviction_mode") or {}).get("baskets") or []
        holdings = [b.get("ticker") for b in baskets if isinstance(b, dict) and b.get("ticker")]
        bench = list(self.bench_loader() or [])
        try:
            prices = self.price_fetcher(holdings + bench) or {}
        except Exception:
            prices = {}
        changes = {t: p["change_pct"] for t, p in prices.items()
                   if isinstance(p, dict) and p.get("change_pct") is not None}
        monitored = [{"symbol": t, "last": (prices.get(t) or {}).get("last"),
                      "change_pct": (prices.get(t) or {}).get("change_pct")} for t in bench]
        return build_matrix_state(state, changes=changes, monitored=monitored, now=self.clock())

    # ---- render the active view -> frames ----
    def frames_for(self, view: str, ms: MatrixState) -> Tuple[List[Image.Image], List[int]]:
        if view == "ambient":
            return build_ambient(ms)
        render = SCREENS.get(view)
        if render is None:
            return build_ambient(ms)
        return [render(ms)], [cfg.STATIC_FRAME_MS]

    # ---- one cycle (the unit-tested core) ----
    def tick(self, *, force: bool = False) -> dict:
        now = self.clock()
        if self.views and not self._focus_active() and (now - self._last_rotate) >= self.cycle_interval:
            self._view_idx = (self._view_idx + 1) % len(self.views)
            self._last_rotate = now
        view = self.views[self._view_idx] if self.views else "ambient"
        ms = self.build_state()
        sig = (view, hash(replace(ms, generated_at=0.0)))      # content signature (ignore the timestamp)
        if sig == self._last_sig and not force:
            return {"action": "skip", "view": view, "stale": ms.stale}
        if (now - self._last_upload) < self.min_upload_interval and not force:
            return {"action": "defer", "view": view}
        frames, delays = self.frames_for(view, ms)
        payload = encode_anim(frames, delays)
        try:
            self.uploader(payload)
        except Exception as e:
            logging.warning("matrix upload failed: %s", e)
            return {"action": "error", "view": view, "error": str(e)}
        self._last_sig = sig
        self._last_upload = now
        return {"action": "upload", "view": view, "frames": len(frames),
                "bytes": len(payload), "stale": ms.stale}

    # ---- the daemon loop (wraps tick with sleep; not unit-tested) ----
    def run(self, poll_interval: Optional[float] = None,
            stop: Optional[Callable[[], bool]] = None) -> None:
        poll = poll_interval if poll_interval is not None else cfg.POLL_INTERVAL_S
        logging.info("matrix orchestrator: engine=%s device=%s views=%s",
                     self.engine_url, self.host, self.views)
        while not (stop and stop()):
            try:
                self.tick()
            except Exception:
                logging.exception("matrix orchestrator tick failed")
            time.sleep(poll)
