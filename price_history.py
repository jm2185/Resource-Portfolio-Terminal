"""
Price History — the replay harness's ground truth (Phase 2.1 of docs/archive/VALIDATION_FLYWHEEL_PLAN.md).

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

    # ------------------------------------------------------------------ migrate
    def force_set(self, ticker: str, day, close, *, save: bool = True) -> dict:
        """Overwrite a stored close, bypassing point-in-time discipline. NOT for ingestion — only
        for an explicit, audited data-quality migration (e.g. currency remediation). Callers must
        report what they changed; normal writes go through ``record`` / ``record_mark``."""
        d = _d(day)
        try:
            c = float(close)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"bad close {close!r}"}
        if d is None or c <= 0:
            return {"ok": False, "error": f"bad day/close ({day!r}, {close!r})"}
        key, ds = str(ticker).upper(), d.isoformat()
        prior = self._d_.get(key, {}).get(ds)
        self._d_.setdefault(key, {})[ds] = c
        if save:
            self._save()
        return {"ok": True, "ticker": key, "date": ds, "close": c, "prior": prior}


# The store is uniformly CAD — the engine marks the whole book in CAD (Wealthsimple / Canada), so the
# valuation ledger stamps CAD and the ground-truth store must match. A name's Yahoo close arrives in
# its LISTING currency, so a USD-listed name (GROY on NYSE-American) comes back ~1/1.4 of its CAD
# neighbours; storing it raw poisons every replay grade for that name (the GROY currency seam). The
# fix is general: resolve each ticker's currency the SAME way the engine does (research-cache tag,
# default CAD) and convert to CAD on the way in.
def to_store_ccy(close, native_ccy, usd_to_cad) -> float:
    """Convert a native-currency close into the store's CAD basis. USD → ×(USD/CAD); CAD/unknown
    pass through. Pure — unit-testable without yfinance or a network."""
    c = float(close)
    if str(native_ccy or "CAD").upper() == "USD" and usd_to_cad:
        return c * float(usd_to_cad)
    return c


def looks_wrong_currency(stored, native_close, converted, *, tol: float = 0.02) -> bool:
    """A stored close is mis-currencied when it matches the RAW native print (here, USD) far more
    closely than the CONVERTED (CAD) value — i.e. it was stored before conversion. Conservative:
    only True when it hugs the raw value (≤tol) and clearly departs from the converted one (>tol).
    Pure — the remediation detector, testable without a network. For a CAD name raw==converted so
    it can never trip."""
    try:
        s, n, cv = float(stored), float(native_close), float(converted)
    except (TypeError, ValueError):
        return False
    if cv <= 0 or n <= 0 or abs(n - cv) / cv <= tol:      # no meaningful gap → nothing to detect
        return False
    return abs(s - n) / n <= tol and abs(s - cv) / cv > tol


def _default_currency_of(_ticker: str) -> str:
    return "CAD"


def _fx_on(fx_series: dict, day: str, *, max_lag_days: int = 7):
    """Same-day USD/CAD (walk back over weekends/holidays), or None."""
    d = _d(day)
    if d is None or not fx_series:
        return None
    for lag in range(max_lag_days + 1):
        ds = (d - timedelta(days=lag)).isoformat()
        if ds in fx_series:
            return float(fx_series[ds])
    return None


def _yahoo_closes(period: str = "2y"):
    """(closes_fn, fx_series) from yfinance — ``closes_fn(ticker) -> {date: native_close}`` and the
    USD/CAD daily series. Lazy import so the module stays stdlib-pure; raises on unavailable so the
    caller reports it."""
    import yfinance as yf

    def closes_fn(t: str) -> dict:
        df = yf.Ticker(t).history(period=period)
        return {idx.date().isoformat(): float(row["Close"])
                for idx, row in df.iterrows() if float(row.get("Close") or 0) > 0}

    fx_series = closes_fn("USDCAD=X")
    return closes_fn, fx_series


def backfill_from_yahoo(history: PriceHistory, tickers: list, *, period: str = "2y",
                        currency_of=None, _sources=None) -> dict:
    """One-time (idempotent) backfill of daily closes from yfinance — free, build-time only.
    Currency-aware: each USD-listed name's native close is converted to the store's CAD basis by
    that day's USD/CAD before it lands (``currency_of`` resolves the listing currency the same way
    the engine does — default CAD). ``_sources`` injects (closes_fn, fx_series) for tests; live
    runs pull it from yfinance. Failures are reported, never raised."""
    currency_of = currency_of or _default_currency_of
    results = {}
    try:
        closes_fn, fx_series = _sources if _sources is not None else _yahoo_closes(period)
    except Exception as e:
        return {"ok": False, "error": f"yfinance unavailable: {e}"}
    for t in tickers:
        try:
            ccy = str(currency_of(t) or "CAD").upper()
            native = closes_fn(t)
            converted, skipped_fx = {}, 0
            for ds, px in native.items():
                if ccy == "USD":
                    fx = _fx_on(fx_series, ds)
                    if not fx:
                        skipped_fx += 1
                        continue                          # never store an unconvertible USD close
                    converted[ds] = to_store_ccy(px, ccy, fx)
                else:
                    converted[ds] = px
            r = history.record_many(t, converted)
            r["currency"] = ccy
            if ccy == "USD":
                r["converted_to_cad"] = len(converted)
                if skipped_fx:
                    r["skipped_no_fx"] = skipped_fx
            results[t] = r
        except Exception as e:
            results[t] = {"ok": False, "error": str(e)}
    return {"ok": True, "results": results}


def repair_currency(history: PriceHistory, tickers: list, *, currency_of=None,
                    apply: bool = False, _sources=None) -> dict:
    """Remediate rows stored in the WRONG currency (the GROY seam: a USD close that landed before
    conversion, so it sits ~1/1.4 of its CAD neighbours). For each USD-listed name, re-derive the
    correct CAD (Yahoo native × same-day USD/CAD) and, where the stored value hugs the RAW USD
    instead, correct it. Dry-run by default (returns the diff); ``apply=True`` force-writes the
    corrections and reports each one — an explicit, audited migration, not silent ingestion.
    CAD names are never touched (raw == converted → the detector can't trip)."""
    currency_of = currency_of or _default_currency_of
    try:
        closes_fn, fx_series = _sources if _sources is not None else _yahoo_closes("2y")
    except Exception as e:
        return {"ok": False, "error": f"yfinance unavailable: {e}"}
    fixes, scanned = [], 0
    for t in tickers:
        if str(currency_of(t) or "CAD").upper() != "USD":
            continue
        native = closes_fn(t)
        series = history._d_.get(str(t).upper(), {})
        for ds, stored in list(series.items()):
            raw = native.get(ds)
            fx = _fx_on(fx_series, ds)
            if raw is None or not fx:
                continue
            scanned += 1
            correct = to_store_ccy(raw, "USD", fx)
            if looks_wrong_currency(stored, raw, correct):
                fixes.append({"ticker": str(t).upper(), "date": ds,
                              "from": round(float(stored), 4), "to": round(correct, 4)})
                if apply:
                    history.force_set(t, ds, correct, save=False)
    if apply and fixes:
        history._save()
    return {"ok": True, "applied": bool(apply), "scanned": scanned,
            "fixed": len(fixes), "fixes": fixes}
