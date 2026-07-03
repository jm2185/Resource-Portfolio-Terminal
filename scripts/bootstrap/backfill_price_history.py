#!/usr/bin/env python3
"""
Backfill the replay harness's ground truth — data/price_history.json — with daily closes from
yfinance (free, one-time), so replay_grade can score the valuation ledger against ACTUAL closes
NOW instead of waiting months for the heartbeat to accumulate. This is the prerequisite for
*measuring* accuracy (vs hand-tuning constants): the graders (intrinsic→price convergence,
REP-floor reliability, P10–P90 PIT band coverage) read ONLY this reproducible store.

Run once on the engine host (needs yfinance + network):

    python backfill_price_history.py                 # the book + names in v5_config.portfolio_metadata
    python backfill_price_history.py AGA.V GROY      # explicit tickers
    python backfill_price_history.py --period 5y     # longer history (default 2y)

Idempotent: `record` refuses to overwrite an existing close (point-in-time discipline), so re-runs
only fill gaps. After the one-time backfill the engine's daily ingestion heartbeat keeps it current.
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))  # repo root (script lives in scripts/bootstrap/)

import json
import sys

import price_history as ph

BOOK = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]


def book_tickers() -> list:
    """The names the engine actually values (so the ledger has something to grade): the barbell
    book + anything carried in portfolio_metadata / an eval set. Falls back to the book alone."""
    tks = list(BOOK)
    try:
        cfg = json.load(open("v5_config.json", encoding="utf-8"))
        # Skip `_`-prefixed metadata keys (`_comment`, …): the same convention build_default_router
        # uses — a documentation key is not a ticker, so it must not be fetched (it 404s from Yahoo).
        for t in (cfg.get("portfolio_metadata") or {}):
            if t and not t.startswith("_") and t not in tks:
                tks.append(t)
        for key in ("eval_set", "eval_tickers", "eval_only"):
            for t in (cfg.get(key) or []):
                if t and not str(t).startswith("_") and t not in tks:
                    tks.append(t)
    except Exception:
        pass
    return tks


def main(argv: list) -> int:
    period, tickers, i = "2y", [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--period", "-p") and i + 1 < len(argv):
            period = argv[i + 1]; i += 2; continue
        if a in ("-h", "--help"):
            print(__doc__); return 0
        tickers.append(a); i += 1
    if not tickers:
        tickers = book_tickers()

    hist = ph.PriceHistory()
    print(f"backfilling {len(tickers)} tickers ({period}) -> {hist.path}")
    res = ph.backfill_from_yahoo(hist, tickers, period=period)
    if not res.get("ok"):
        print(f"  FAILED: {res.get('error')}")
        print("  (this needs yfinance + network on the engine host)")
        return 1
    for t, r in (res.get("results") or {}).items():
        if r.get("ok"):
            extra = f"  ⚠ {len(r['conflicts'])} conflicts" if r.get("conflicts") else ""
            print(f"  {t:10} +{r.get('added', 0)} closes ({r.get('duplicates', 0)} dup){extra}")
        else:
            print(f"  {t:10} ERROR {r.get('error')}")
    cov = hist.stats().get("tickers", {})
    print("\ncoverage now:", {t: n for t, n in sorted(cov.items())})
    print("next: run replay_grade (or /journal) to grade the valuation ledger against these closes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
