"""
Mark guard — may THIS price mark be written into the desk's track record?

Pure, stdlib, unit-testable. The 2026-09-02 reassessment found the engine's cold-start seed
prices (badged LIVE) being stamped as the day's first ``daily`` valuation row and written into
the replay price store (``data/price_history.json``) with no staleness check, then protected by
the store's point-in-time immutability: 13/13 August AGA.V daily rows at the 0.72 seed, 7/7 GROY
daily rows at 4.444 (= the 3.22 seed × the 1.38 seed FX). Those constants then priced flywheel
decisions, outcomes, and the learned base rate.

The invariant this module enforces: **a mark the feed did not actually deliver is never
recorded** — not into the valuation ledger, not into the price store, not into the macro
snapshot history. Refusing to write is the honest outcome; a dark day in the store is a fact,
a constant in the store is a fabrication.

The engine's price worker already stamps per-ticker ``prices_stale`` (intraday / dated daily /
last-good / hardcoded-fallback, see ``market_data.resolve_freshness``) and a ``prices_ts`` on every
successful sync; the cold-start seed now stamps ``prices_status: INITIAL_BASELINE`` with every seed
ticker stale. This module just reads those honestly.
"""
from __future__ import annotations

import time
from typing import Iterable, Optional

SEED_STATUS = "INITIAL_BASELINE"
DEFAULT_MAX_AGE_S = 1800.0     # a worker sync older than this is a dead feed, not a live mark


def trustworthy(ticker: str, *, prices_stale: Optional[dict] = None,
                prices_status: Optional[str] = None, prices_ts=None, now=None,
                max_age_s: float = DEFAULT_MAX_AGE_S) -> tuple:
    """Return ``(ok, reason)`` — may ``ticker``'s current mark be written into a store?

    Fails closed in this order:
      * ``prices_status == INITIAL_BASELINE`` (nothing has been fetched yet) → ``seed``;
      * no ``prices_ts`` (the worker has never synced) → ``no-sync``;
      * ``prices_ts`` older than ``max_age_s`` → ``sync-stale``;
      * ``prices_stale[ticker]`` truthy (dated close / last-good / hardcoded fallback) → ``stale``;
      * otherwise ``ok``.
    An unknown ticker (absent from ``prices_stale``) is treated as stale — absence is not freshness.
    """
    key = str(ticker or "").upper()
    if not key:
        return False, "no-ticker"
    if str(prices_status or "").upper() == SEED_STATUS:
        return False, "seed"
    try:
        ts = float(prices_ts) if prices_ts is not None else None
    except (TypeError, ValueError):
        ts = None
    if ts is None:
        return False, "no-sync"
    t_now = float(now) if now is not None else time.time()
    if (t_now - ts) > float(max_age_s):
        return False, "sync-stale"
    stale = prices_stale or {}
    # tolerate either exact-case or upper-cased keys (the worker keys by vendor symbol)
    if key not in stale and ticker not in stale:
        return False, "unknown"
    if bool(stale.get(key, stale.get(ticker))):
        return False, "stale"
    return True, "ok"


def plan_stamps(tickers: Iterable[str], **kw) -> dict:
    """Split ``tickers`` into the names whose marks may be stamped this cycle and the names that
    must be skipped, with the reason per skipped name. Pure; the engine's ledger writer consumes it."""
    stamp, skipped = [], {}
    for t in tickers:
        ok, why = trustworthy(t, **kw)
        if ok:
            stamp.append(t)
        else:
            skipped[str(t)] = why
    return {"stamp": stamp, "skipped": skipped}


def seesaw_trusted(*, prices_stale: Optional[dict] = None, prices_status: Optional[str] = None,
                   ry_status: Optional[str] = None, prices_ts=None, now=None,
                   max_age_s: float = DEFAULT_MAX_AGE_S) -> tuple:
    """May today's macro snapshot (gold / silver / real yield / VIX) be recorded into
    ``seesaw_history``? Requires a live silver mark AND a live real-yield leg — the two legs the
    2026-08 rows fabricated (silver 74.8 / real 1.0 or 1.8 seeds on seven consecutive days)."""
    ok, why = trustworthy("SI=F", prices_stale=prices_stale, prices_status=prices_status,
                          prices_ts=prices_ts, now=now, max_age_s=max_age_s)
    if not ok:
        return False, f"silver:{why}"
    if str(ry_status or "").upper() != "LIVE":
        return False, f"real_yield:{ry_status or 'unknown'}"
    return True, "ok"


def regime_trusted(*, macro_status: Optional[str] = None, prices_status: Optional[str] = None) -> tuple:
    """May a POSTURE flip be persisted to Living Memory as a ``regime_snapshot``? The 16 rows of
    2026-06-23/24 flapped DEFENSIVE↔BALANCED↔SPEAR EXPLOIT within minutes on a regime read whose
    inputs were still seeds. A posture computed on baselines is a display state, not an event."""
    m = str(macro_status or "").upper()
    p = str(prices_status or "").upper()
    if m != "LIVE":
        return False, f"macro:{macro_status or 'unknown'}"
    if p == SEED_STATUS:
        return False, "prices:seed"
    return True, "ok"
