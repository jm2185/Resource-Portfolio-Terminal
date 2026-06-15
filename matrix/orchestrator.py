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
from . import logos
from .encoder import encode_anim
from .prices import yfinance_ohlc, yfinance_price_fetcher
from .screens import SCREENS
from .screens.crawl import build_ambient
from .screens.detail import detail_card


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
                 ohlc_fetcher: Optional[Callable[[str], list]] = None,
                 logo_fetcher: Optional[Callable[[str], bool]] = None,
                 uploader: Optional[Callable[[bytes], None]] = None,
                 focus_fetcher: Optional[Callable[[], bool]] = None,
                 cycle_interval: Optional[float] = None,
                 ambient_dwell: Optional[float] = None,
                 min_upload_interval: Optional[float] = None,
                 loop_max_frames: Optional[int] = None,
                 clock: Callable[[], float] = time.time):
        self.engine_url = (engine_url or cfg.ENGINE_URL).rstrip("/")
        self.host = host or cfg.DEVICE_HOST
        self.views = list(views or cfg.ROTATION)
        self.state_fetcher = state_fetcher or self._default_state_fetcher
        self.price_fetcher = price_fetcher or yfinance_price_fetcher   # default: yfinance (handles .V/.TO)
        self.bench_loader = bench_loader or load_bench
        self.ohlc_fetcher = ohlc_fetcher or yfinance_ohlc           # detail-mode candlestick data
        self.logo_fetcher = logo_fetcher or logos.fetch_logo        # detail-mode logo (out-of-band)
        self.uploader = uploader or self._default_uploader
        self.focus_fetcher = focus_fetcher                          # device button -> hold the current view
        self.cycle_interval = cycle_interval if cycle_interval is not None else cfg.CYCLE_INTERVAL_S
        self.ambient_dwell = ambient_dwell if ambient_dwell is not None else cfg.AMBIENT_DWELL_S
        self.min_upload_interval = (min_upload_interval if min_upload_interval is not None
                                    else cfg.MIN_UPLOAD_INTERVAL_S)
        self.loop_max_frames = loop_max_frames or cfg.LOOP_MAX_FRAMES
        self.clock = clock
        self._panel_idx = 0
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
    def _detail_names(self, ms: MatrixState):
        return [w for w in ms.watchlist if not w.eval_only]   # detail cards: holdings only (bench rides the crawl)

    def _panels(self, ms: MatrixState):
        """Expand the configured views into concrete panels. 'detail' becomes one panel per HOLDING,
        so the rotation walks each company's full-screen card (the detail mode)."""
        names = self._detail_names(ms)
        out = []
        for v in self.views:
            if v == "detail":
                out += [("detail", i) for i in range(len(names))] or [("detail", -1)]
            else:
                out.append((v, None))
        return out or [("ambient", None)]

    def _frames_for_panel(self, panel, ms: MatrixState):
        view, idx = panel
        if view == "detail":
            names = self._detail_names(ms)
            item = names[idx] if (idx is not None and 0 <= idx < len(names)) else None
            ohlc = []
            if item is not None:
                tk = item.ticker or item.symbol
                try:
                    ohlc = self.ohlc_fetcher(tk) or []
                except Exception:
                    ohlc = []
                try:
                    if item.ticker and not logos.has_logo(item.ticker):
                        self.logo_fetcher(item.ticker)          # populate the logo cache out-of-band
                except Exception:
                    pass
            return [detail_card(ms, item, ohlc=ohlc)], [cfg.STATIC_FRAME_MS]
        return self.frames_for(view, ms)

    def tick(self, *, force: bool = False) -> dict:
        now = self.clock()
        ms = self.build_state()
        panels = self._panels(ms)
        current = panels[self._panel_idx % len(panels)]
        dwell = self.ambient_dwell if current[0] == "ambient" else self.cycle_interval
        if not self._focus_active() and (now - self._last_rotate) >= dwell:
            self._panel_idx = (self._panel_idx + 1) % len(panels)
            self._last_rotate = now
        panel = panels[self._panel_idx % len(panels)]
        sig = (panel, hash(replace(ms, generated_at=0.0)))     # content signature (ignore the timestamp)
        if sig == self._last_sig and not force:
            return {"action": "skip", "view": panel[0], "panel": panel, "stale": ms.stale}
        if (now - self._last_upload) < self.min_upload_interval and not force:
            return {"action": "defer", "view": panel[0], "panel": panel}
        frames, delays = self._frames_for_panel(panel, ms)
        payload = encode_anim(frames, delays)
        try:
            self.uploader(payload)
        except Exception as e:
            logging.warning("matrix upload failed: %s", e)
            return {"action": "error", "view": panel[0], "panel": panel, "error": str(e)}
        self._last_sig = sig
        self._last_upload = now
        return {"action": "upload", "view": panel[0], "panel": panel,
                "frames": len(frames), "bytes": len(payload), "stale": ms.stale}

    # ---- the daemon loop (wraps tick with sleep; not unit-tested) ----
    # ---- self-loop mode: one anim the device rotates on its own ----
    def build_loop_frames(self, ms: MatrixState):
        """One representative frame per rotation screen (detail expands per name), each held for the
        dwell, packed so the DEVICE cycles them autonomously from a single upload — no host needed until
        the data changes. Capped at ``loop_max_frames`` (upload-size guard). The scrolling crawl collapses
        to its static first frame here (smooth scroll is host-driven / Tier-C only)."""
        frames, delays = [], []
        for panel in self._panels(ms):
            f, _ = self._frames_for_panel(panel, ms)
            frames.append(f[0])
            d = self.ambient_dwell if panel[0] == "ambient" else self.cycle_interval
            delays.append(int(min(d * 1000, 60000)))           # ms/screen, clamped under uint16 + firmware
            if len(frames) >= self.loop_max_frames:
                break
        return frames, delays

    def push_loop(self, *, force: bool = False) -> dict:
        """Build + upload the whole rotation as ONE looping anim.bin; re-upload only on data change
        (debounced). The device handles the cycling, so this can run on a slow poll."""
        now = self.clock()
        ms = self.build_state()
        sig = ("loop", hash(replace(ms, generated_at=0.0)))
        if sig == self._last_sig and not force:
            return {"action": "skip", "mode": "loop", "stale": ms.stale}
        if (now - self._last_upload) < self.min_upload_interval and not force:
            return {"action": "defer", "mode": "loop"}
        frames, delays = self.build_loop_frames(ms)
        payload = encode_anim(frames, delays)
        try:
            self.uploader(payload)
        except Exception as e:
            logging.warning("matrix loop upload failed: %s", e)
            return {"action": "error", "mode": "loop", "error": str(e)}
        self._last_sig = sig
        self._last_upload = now
        return {"action": "upload", "mode": "loop", "frames": len(frames),
                "bytes": len(payload), "stale": ms.stale}

    # ---- the daemon loop ----
    def run(self, poll_interval: Optional[float] = None,
            stop: Optional[Callable[[], bool]] = None, self_loop: bool = False) -> None:
        """Poll loop. ``self_loop=False`` (default): host-driven rotation (one screen per tick).
        ``self_loop=True``: push one self-cycling anim the device rotates itself (resilient when the
        host is off); only re-uploads on data change."""
        poll = poll_interval if poll_interval is not None else cfg.POLL_INTERVAL_S
        logging.info("matrix orchestrator: engine=%s device=%s views=%s self_loop=%s",
                     self.engine_url, self.host, self.views, self_loop)
        while not (stop and stop()):
            try:
                self.push_loop() if self_loop else self.tick()
            except Exception:
                logging.exception("matrix orchestrator %s failed", "loop" if self_loop else "tick")
            time.sleep(poll)
