"""
Price History — the replay harness's ground truth (Phase 2.1 of docs/VALIDATION_FLYWHEEL_PLAN.md).

A small cached store of daily closes (``data/price_history.json``) so valuation-ledger grading
reads ONLY a reproducible store — never a live quote — and a replay run yesterday and a replay run
today grade the same snapshot identically. Appended by the ingestion cadence (one batch a day);
backfilled once at build time via yfinance (free).

Discipline:
  * **Point-in-time honest.** ``record`` never silently overwrites an existing close with a
    different value — a restated print is returned as a conflict for the caller to surface.
  * **Weekend/holiday tolerant.** ``close_on`` walks back up to ``max_lag_days`` to the prior
    trading day, and reports the lag, so a 90-day horizon landing on a Sunday still grades.

Pure stdlib (yfinance imported lazily ONLY inside the optional backfill helper).
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Optional

DEFAULT_PATH = "data/price_history.json"


def _d(s) -> Optional[date]:
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class PriceHistory:
    """``{ticker: {"YYYY-MM-DD": close}}`` over one JSON file (atomic replace on save)."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._d_: dict = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._d_, f, indent=1, sort_keys=True)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ write
    def record(self, ticker: str, day, close, *, save: bool = True) -> dict:
        """Record one daily close. Idempotent for a repeated identical print; a DIFFERENT close for
        an already-recorded day is NOT overwritten (point-in-time discipline) — it comes back as
        ``{"conflict": True, ...}`` for the caller to surface, never a silent rewrite."""
        d = _d(day)
        try:
            c = float(close)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"bad close {close!r}"}
        if d is None or c <= 0:
            return {"ok": False, "error": f"bad day/close ({day!r}, {close!r})"}
        key, ds = str(ticker).upper(), d.isoformat()
        existing = self._d_.get(key, {}).get(ds)
        if existing is not None:
            if abs(float(existing) - c) <= 1e-9:
                return {"ok": True, "ticker": key, "date": ds, "close": c, "duplicate": True}
            return {"ok": False, "conflict": True, "ticker": key, "date": ds,
                    "existing": existing, "attempted": c,
                    "error": "close already recorded with a different value — not overwritten"}
        self._d_.setdefault(key, {})[ds] = c
        if save:
            self._save()
        return {"ok": True, "ticker": key, "date": ds, "close": c}

    def record_mark(self, ticker: str, day, price, *, today=None, save: bool = True) -> dict:
        """An intraday mark that CONVERGES to the close: today's value may be updated as the day
        progresses (the last mark before the date roll becomes the de-facto daily close — the
        engine eval loop calls this every cycle), but any PAST date is immutable (delegates to
        ``record``, which refuses a silent rewrite) and a future date is refused outright.
        This is what lets the engine — which never sees an official close — keep the ground-truth
        store current without violating point-in-time discipline."""
        d = _d(day)
        t = _d(today) or date.today()
        if d is None:
            return {"ok": False, "error": f"bad day {day!r}"}
        if d < t:
            return self.record(ticker, d, price, save=save)      # the past is immutable
        if d > t:
            return {"ok": False, "error": "refusing a future-dated mark"}
        try:
            c = float(price)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"bad price {price!r}"}
        if c <= 0:
            return {"ok": False, "error": f"bad price {price!r}"}
        key, ds = str(ticker).upper(), d.isoformat()
        existing = self._d_.get(key, {}).get(ds)
        if existing is not None and abs(float(existing) - c) <= 1e-9:
            return {"ok": True, "ticker": key, "date": ds, "close": c, "duplicate": True}
        self._d_.setdefault(key, {})[ds] = c
        if save:
            self._save()
        return {"ok": True, "ticker": key, "date": ds, "close": c,
                "updated": existing is not None}

    def record_many(self, ticker: str, closes: dict) -> dict:
        """Batch-record ``{date: close}`` (one save). Returns counts + any conflicts."""
        added, dups, conflicts = 0, 0, []
        for day, close in (closes or {}).items():
            r = self.record(ticker, day, close, save=False)
            if r.get("ok") and r.get("duplicate"):
                dups += 1
            elif r.get("ok"):
                added += 1
            elif r.get("conflict"):
                conflicts.append(r)
        self._save()
        return {"ok": True, "ticker": str(ticker).upper(), "added": added,
                "duplicates": dups, "conflicts": conflicts}

    # ------------------------------------------------------------------ read
    def close_on(self, ticker: str, day, *, max_lag_days: int = 5) -> Optional[dict]:
        """The close at-or-before ``day`` within ``max_lag_days`` (weekends/holidays), or None.
        Returns ``{date, close, lag_days}`` so the grade can show how stale its mark was."""
        d = _d(day)
        if d is None:
            return None
        series = self._d_.get(str(ticker).upper(), {})
        for lag in range(max_lag_days + 1):
            ds = (d - timedelta(days=lag)).isoformat()
            if ds in series:
                return {"date": ds, "close": float(series[ds]), "lag_days": lag}
        return None

    def window(self, ticker: str, start, end) -> list:
        """``[(date, close)]`` for start ≤ date ≤ end, oldest-first."""
        s, e = _d(start), _d(end)
        if s is None or e is None:
            return []
        series = self._d_.get(str(ticker).upper(), {})
        out = [(ds, float(c)) for ds, c in series.items() if s.isoformat() <= ds <= e.isoformat()]
        out.sort()
        return out

    def min_close(self, ticker: str, start, end) -> Optional[dict]:
        """The lowest close in the window — what the REP-floor reliability grade tests against."""
        w = self.window(ticker, start, end)
        if not w:
            return None
        ds, c = min(w, key=lambda x: x[1])
        return {"date": ds, "close": c, "n_days": len(w)}

    def last_date(self, ticker: str) -> Optional[str]:
        series = self._d_.get(str(ticker).upper(), {})
        return max(series) if series else None

    def tickers(self) -> list:
        return sorted(self._d_.keys())

    def stats(self) -> dict:
        return {"tickers": {t: len(s) for t, s in self._d_.items()}, "path": self.path}


def backfill_from_yahoo(history: PriceHistory, tickers: list, *, period: str = "2y") -> dict:
    """One-time (idempotent) backfill of daily closes from yfinance — free, build-time only.
    Lazy import so the module stays stdlib-pure for tests; failures are reported, never raised."""
    results = {}
    try:
        import yfinance as yf
    except Exception as e:
        return {"ok": False, "error": f"yfinance unavailable: {e}"}
    for t in tickers:
        try:
            df = yf.Ticker(t).history(period=period)
            closes = {idx.date().isoformat(): float(row["Close"])
                      for idx, row in df.iterrows() if float(row.get("Close") or 0) > 0}
            results[t] = history.record_many(t, closes)
        except Exception as e:
            results[t] = {"ok": False, "error": str(e)}
    return {"ok": True, "results": results}
