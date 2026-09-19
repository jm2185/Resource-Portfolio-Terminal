"""Shared low-level utilities for the compute engines — mechanically moved out of engine.py
(Arch 2 split); logic unchanged.

Holds the runtime SIGNAL SHIELD (installed as an import side effect — this module must be
imported before yfinance/OpenBB load, preserving engine.py's original order), the macro-state
and persistent disk caches (one on-disk instance shared by engine.py and every engines/*
module), the Phase-0 robust-statistic helpers, and the barbell-weight / book-membership
helpers. engine.py re-binds every name here into its own namespace, so `engine._save_to_disk_cache`,
`engine.eval_only_tickers` etc. keep working (and stay monkeypatchable for the orchestrator's
code paths, which resolve them through engine.py's module globals as before).
"""

import signal
import threading

# ====================== SIGNAL SHIELD ======================
_native_signal_setter = signal.signal

def _runtime_signal_shield(signum, handler):
    """Intercepts and silences signal registration errors from OpenBB worker threads."""
    try:
        if threading.current_thread() is threading.main_thread():
            return _native_signal_setter(signum, handler)
    except ValueError as e:
        if "main thread" in str(e).lower():
            return None
        raise e
    return None

signal.signal = _runtime_signal_shield
# ========================================================

import json
import logging
import os
import time

import numpy as np

# ====================== MACRO STATE CACHE UTILITY ======================
CACHE_FILE = ".cache/macro_state.json"

def _save_to_cache(category, key_values):
    try:
        os.makedirs(".cache", exist_ok=True)
        data = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    data = json.load(f)
            except Exception:
                pass
        if category not in data:
            data[category] = {}
        data[category].update(key_values)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] Failed to save macro state cache: {e}")

def _load_from_cache(category, default_dict):
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                if category in data:
                    res = default_dict.copy()
                    res.update(data[category])
                    return res
    except Exception:
        pass
    return default_dict

# ====================== PERSISTENT DISK CACHING UTILITY ======================
def _save_to_disk_cache(cache_key, data):
    try:
        os.makedirs(".cache", exist_ok=True)
        filename = f".cache/disk_cache_{cache_key}.json"
        cache_data = {
            "timestamp": time.time(),
            "data": data
        }
        with open(filename, "w") as f:
            json.dump(cache_data, f, indent=4)
    except Exception as e:
        print(f"[!] Failed to write disk cache for {cache_key}: {e}")

def _load_from_disk_cache(cache_key, max_age_hours):
    try:
        filename = f".cache/disk_cache_{cache_key}.json"
        if os.path.exists(filename):
            with open(filename, "r") as f:
                cache_data = json.load(f)
            t_diff = time.time() - cache_data.get("timestamp", 0)
            if t_diff < max_age_hours * 3600:
                return cache_data.get("data")
    except Exception as e:
        print(f"[!] Failed to read disk cache for {cache_key}: {e}")
    return None

# ====================== PHASE 0 ROBUST-STATISTIC HELPERS ======================
def _percentile_rank(series, x):
    """Percentile rank (0..100) of x within `series` — the fraction of observations <= x.
    Phase 0 patch: replaces static MRI min-max bounds, which permanently saturate at 0/100 once
    a price leaves its historic band, with a rank against a CURRENT rolling window so the signal
    never flat-lines. Returns None on an empty/invalid series so callers can fall back to static."""
    try:
        arr = [float(v) for v in series if v is not None and not (isinstance(v, float) and np.isnan(v))]
        n = len(arr)
        if n == 0:
            return None
        c = sum(1 for v in arr if v <= x)
        return 100.0 * c / n
    except Exception:
        return None

def _robust_adv_shares(hist, window_days=90, method="median", halflife=30):
    """Robust average daily VOLUME in shares, computed from a price/volume history frame.
    Phase 0 patch: a 10-day ADV spikes during panics and pro-cyclically inflates the dollar
    liquidity cap exactly when exit liquidity should be assumed scarcer. A 90-session median
    cannot be moved by a single spike; an EWMA(halflife) is offered as a smoother alternative.
    Returns None when there is insufficient history so callers can fall back to info-field ADV."""
    try:
        if hist is None or len(hist) == 0 or 'Volume' not in hist:
            return None
        vol = hist['Volume'].dropna()
        vol = vol[vol > 0].tail(int(window_days))
        if len(vol) < 10:
            return None
        if method == "ewma":
            return float(vol.ewm(halflife=max(1, int(halflife))).mean().iloc[-1])
        return float(vol.median())
    except Exception:
        return None

def _realized_vol(series, lookback=60):
    """Annualized realized volatility from a trailing price series (Phase 4a).
    Feeds the option-premium vol term with a LIVE silver vol instead of the old hardcoded 0.25.
    Returns None on insufficient history so callers can fall back to a config default."""
    try:
        s = [float(v) for v in series if v is not None and not (isinstance(v, float) and np.isnan(v))]
        s = s[-(int(lookback) + 1):]
        if len(s) < 20:
            return None
        rets = [(s[i] / s[i - 1] - 1.0) for i in range(1, len(s)) if s[i - 1] > 0]
        if len(rets) < 19:
            return None
        return float(np.std(rets, ddof=1) * np.sqrt(252.0))
    except Exception:
        return None


def _is_pos(x):
    """True iff x is a finite, strictly-positive number (Phase 7 helper)."""
    try:
        f = float(x)
        return f == f and f not in (float("inf"), float("-inf")) and f > 0.0
    except (TypeError, ValueError):
        return False


def _age_days_iso(ts):
    """Whole days since an ISO-8601 ('…Z' UTC) timestamp, or None if unparseable — the clock the
    calibration flywheel injects into its pure planner (matches mcp_server/core._age_days)."""
    if not ts:
        return None
    import datetime as _dt
    try:
        t = _dt.datetime.strptime(str(ts).replace("Z", "").split("+")[0], "%Y-%m-%dT%H:%M:%S")
        return max(0, (_dt.datetime.utcnow() - t).days)
    except (ValueError, TypeError):
        return None


# Structural barbell sleeve weights (the Druckenmiller 60/40 spear+ballast split). SINGLE source —
# the same 60/15/15/10 was previously duplicated as literals in the sizer, the comps worker (as a
# mis-orderable np.array against a differently-ordered ticker list), and the PPI / EV blend, one edit
# from a silent mis-weighting. Note: this does NOT loosen the structural 60% spear ceiling in
# calculate_sizing (that min() clamp is a separate, deliberately non-configurable invariant).
DEFAULT_BARBELL_WEIGHTS = {"AGA.V": 0.60, "GROY": 0.15, "URC.TO": 0.15, "GMX.TO": 0.10}


def _resolve_barbell_weights(cfg):
    """Barbell sleeve weights from config (`barbell_weights`), validated to sum to ~1; otherwise the
    safe default. One validated source for every consumer so the weights can never silently diverge."""
    raw = cfg.get("barbell_weights") if isinstance(cfg, dict) else None
    if not isinstance(raw, dict):
        return dict(DEFAULT_BARBELL_WEIGHTS)
    bw = {k: v for k, v in raw.items() if not str(k).startswith("_")}   # drop _comment etc.
    if not bw:
        return dict(DEFAULT_BARBELL_WEIGHTS)
    try:
        weights = {k: float(v) for k, v in bw.items()}
    except (TypeError, ValueError):
        return dict(DEFAULT_BARBELL_WEIGHTS)
    if abs(sum(weights.values()) - 1.0) > 1e-6:
        logging.warning("barbell_weights sum %.4f != 1.0; falling back to defaults",
                        sum(weights.values()))
        return dict(DEFAULT_BARBELL_WEIGHTS)
    return weights


def book_tickers(cfg):
    """The HELD book = the keys of the validated barbell weights — the single source of MEMBERSHIP
    (who is in the book), companion to `_resolve_barbell_weights` (their weights). Eval-only names
    (rated, not held) are NOT here — they come from `eval_only_tickers`. Routing every consumer
    through this makes cutting/adding a holding a pure data change (`barbell_weights`), never a code
    edit, and stops any site from KeyError-ing on a name that was removed."""
    return list(_resolve_barbell_weights(cfg).keys())


def held_positions(cfg):
    """The HELD book OUTSIDE the silver barbell sleeve (``held_positions`` in v5_config.json):
    actually-held names that are rated + priced + dashboard-carded like the book but enter NO
    barbell sizing math (the barbell remains the silver sleeve). A dict of
    ``ticker -> {weight_pct, asof, basis}``; weights are approximate book weights, not sizing
    inputs. Cutting/adding a holding is a pure data change here, never a code edit."""
    hp = cfg.get("held_positions") if isinstance(cfg, dict) else None
    if not isinstance(hp, dict):
        return {}
    return {str(t): m for t, m in hp.items()
            if not str(t).startswith("_") and isinstance(m, dict)}


def held_book_tickers(cfg):
    """The FULL held book for pricing/rating/dashboard membership: barbell members first,
    then held_positions keys (deduped, order-stable). Eval-only names are NOT here — they
    come from `eval_only_tickers`."""
    return list(dict.fromkeys(book_tickers(cfg) + list(held_positions(cfg).keys())))


def native_ladder(ladder, fx):
    """The CAD price ladder converted back to a name's NATIVE display currency: each absolute leg
    (price/floor/base/bull/bear) ÷ ``fx`` (the rate that normalized it to CAD). φ and upside are
    RATIOS and so are currency-invariant — this only realigns the absolute points so they reconcile
    with the native-currency fundamentals the cockpit shows alongside them. ``fx``≈1 -> unchanged."""
    if not isinstance(ladder, dict) or not fx or abs(float(fx) - 1.0) < 1e-9:
        return None
    f = float(fx)
    return {k: (round(v / f, 3) if isinstance(v, (int, float)) else v) for k, v in ladder.items()}


def eval_only_tickers(cfg, cap=6):
    """Names promoted to the EVAL set — ``portfolio_metadata[t].eval_only`` is true. The engine
    rates them alongside the book (price fetched, archetype-valued, conviction-scored) but they
    hold NO barbell weight and enter NO sizing math: rated, not held. Promotion is gated at the
    MCP layer (graduation receipts); this helper is the single definition of the set. Capped so
    the bulk yfinance download stays bounded."""
    meta = cfg.get("portfolio_metadata") if isinstance(cfg, dict) else None
    if not isinstance(meta, dict):
        return []
    out = [str(t) for t, m in meta.items()
           if isinstance(m, dict) and m.get("eval_only") and not str(t).startswith("_")]
    return sorted(out)[:max(0, int(cap))]
