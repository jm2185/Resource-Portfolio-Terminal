"""
Layout Changes Summary:
Condensation approach for the v5.1 Professional Educational Terminal:
- Introduced `metric_metadata` dictionary into the terminal state within the orchestrator (`CommodityExMonitor.__init__`).
- This dictionary populates the new "Metric Compass" panel and inline educational tooltips across the frontends (Streamlit and Flutter) to explain first-principles definitions, calculation contexts, actionability, relationships, and indicator signals for all core terminal metrics.
- No calculations were modified; all structural logic remains identical to v5.0.
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

import asyncio
import copy
import yfinance as yf
import os
import json
import logging
import time
import pandas as pd
import numpy as np
from fastapi import FastAPI, WebSocket
import uvicorn
from contextlib import asynccontextmanager

# Phase 5b: the Polymorphic Archetype Factory (pure-Python, no heavy deps). Imported here
# so the orchestrator can emit supplementary, CAD-normalized triangulated valuations
# alongside — never instead of — the legacy valuation path. archetypes.py never imports
# engine.py, so there is no circular dependency.
from archetypes import build_default_router, load_config, TickerNotRegisteredError, REGIME_ORDER
from ui_state import UIStateManager
from dynamic_config import DynamicConfigManager, ConfigError
try:
    from fmp_client import FMPClient            # free-tier FMP: fundamentals + treasury, hard-cached
except Exception:                               # pragma: no cover - optional dependency-light helper
    FMPClient = None

# Research dossiers / decision memos written by the /dossier skill (agents) and rendered
# read-only by the cockpit Dossier tab. Absolute so it resolves regardless of launch cwd.
DECISIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "decisions")

# Phase 7: the dependency-free T-Q-V Asymmetry Rating that powers the primary Conviction Mode
# view. Pure supplement — guarded so the engine still runs if the module is absent.
try:
    from asymmetry_rating import build_conviction_state
except Exception:  # pragma: no cover - conviction overlay is strictly additive
    build_conviction_state = None

# Phase 8: live catalyst reactivity. Events (drill/financing/permitting/catalyst) become
# bounded signal overlays on the TQV inputs + a recent-catalyst list. Guarded import.
try:
    from catalyst_engine import load_catalyst_feed, build_catalyst_overlays
except Exception:  # pragma: no cover - catalyst layer is strictly additive
    load_catalyst_feed = None
    build_catalyst_overlays = None

# Phase 6: optional open-source ingestion overlay. The engine reads the cache that
# ingestion_pipeline.py compiles; the import is guarded so the engine still runs if
# the module (or one of its deps) is absent. ingestion_pipeline never imports engine.py.
try:
    from ingestion_pipeline import load_ingestion_cache
except Exception:  # pragma: no cover - ingestion layer is strictly optional
    load_ingestion_cache = None

# Phase 8 (debug fix): the LIVE catalyst refresher. Without this, the engine only ever
# served the static checked-in feed file (catalysts looked "hardcoded"). Guarded + optional.
try:
    from ingestion_pipeline import refresh_catalyst_feed
except Exception:  # pragma: no cover - live refresh is strictly optional / offline-safe
    refresh_catalyst_feed = None

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

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

# ========================================================
# v5 MODULAR ENGINE ARCHITECTURE
# ========================================================

class MacroRegimeEngine:
    def __init__(self, config_path):
        self.config_path = config_path
        
    def get_config(self):
        # When the orchestrator wires a config provider (CommodityExMonitor), serve the per-cycle
        # EFFECTIVE config (v5_config.json defaults + confirmed SQLite overrides) instead of a raw
        # file read. This is what makes a /confirm'd override actually reach live valuation, the JSF
        # gate, and the directives (previously every engine re-read the raw file and silently bypassed
        # the overlay), and it collapses ~dozens of redundant disk reads per cycle into one. Engines
        # constructed standalone (e.g. unit tests) have no provider -> identical legacy file read.
        provider = getattr(self, "_config_provider", None)
        if provider is not None:
            return provider()
        with open(self.config_path, "r") as f:
            return json.load(f)

    async def fetch_macro_data(self):
        # 1. Check 12-hour local disk cache
        cached_data = _load_from_disk_cache("macro_data", 12.0)
        if cached_data is not None:
            print("[*] [Macro Engine] Cache HIT for macro_data. Loaded from disk instantly.")
            return cached_data["result"], cached_data["status"]

        status = "LIVE"
        try:
            def openbb_fetch():
                from openbb import obb
                import os
                if os.path.exists("FRED_API_KEY"):
                    with open("FRED_API_KEY", "r") as f:
                        obb.user.credentials.fred_api_key = f.read().strip()
                def fetch_raw_fred(series_id, fallback_val):
                    try:
                        res = obb.economy.fred_series(series_id)
                        df = res.to_dataframe()
                        if not df.empty:
                            df_clean = df.replace('.', None).dropna()
                            if not df_clean.empty: return float(df_clean.iloc[-1].iloc[0])
                    except: pass
                    
                    # Level 2: Direct anonymous CSV download from FRED ( extrêmement reliable )
                    try:
                        import requests
                        import pandas as pd
                        import io
                        import numpy as np
                        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        if res.status_code == 200:
                            df = pd.read_csv(io.StringIO(res.text))
                            if not df.empty and series_id in df.columns:
                                df_clean = df.replace('.', np.nan).dropna()
                                if not df_clean.empty:
                                    return float(df_clean[series_id].iloc[-1])
                    except Exception as e:
                        print(f"[!] Direct FRED CSV fetch fallback failed for {series_id}: {e}")

                    # Level 3: yfinance treasury rates indices proxies
                    try:
                        import yfinance as yf
                        if series_id == "DGS3MO":
                            t = yf.Ticker("^IRX")
                            h = t.history(period="5d")
                            if not h.empty: return float(h['Close'].iloc[-1])
                        elif series_id == "DGS10":
                            t = yf.Ticker("^TNX")
                            h = t.history(period="5d")
                            if not h.empty: return float(h['Close'].iloc[-1])
                        elif series_id == "DGS30":
                            t = yf.Ticker("^TYX")
                            h = t.history(period="5d")
                            if not h.empty: return float(h['Close'].iloc[-1])
                    except Exception as e:
                        print(f"[!] yfinance rate fallback failed for {series_id}: {e}")

                    return fallback_val
                
                # Fetch SOFR and DGS3MO with paired validation to prevent cross-cycle contamination
                _SOFR_SENTINEL = -999.0
                _DGS3MO_SENTINEL = -999.0
                sofr_val = fetch_raw_fred("SOFR", _SOFR_SENTINEL)
                dgs3mo_val = fetch_raw_fred("DGS3MO", _DGS3MO_SENTINEL)
                
                if sofr_val != _SOFR_SENTINEL and dgs3mo_val != _DGS3MO_SENTINEL:
                    # Both fetched successfully — compute live spread
                    sofr_spread = sofr_val - dgs3mo_val
                elif sofr_val != _SOFR_SENTINEL and dgs3mo_val == _DGS3MO_SENTINEL:
                    # SOFR live but DGS3MO failed — estimate DGS3MO from SOFR (typically within ±15bps)
                    dgs3mo_val = sofr_val - 0.05  # Conservative 5bps assumption
                    sofr_spread = sofr_val - dgs3mo_val
                    print(f"[!] SOFR Spread: DGS3MO fetch failed. Using SOFR-derived estimate ({dgs3mo_val:.2f}%)")
                elif sofr_val == _SOFR_SENTINEL and dgs3mo_val != _DGS3MO_SENTINEL:
                    # DGS3MO live but SOFR failed — estimate from Fed Funds
                    fed_funds = fetch_raw_fred("FEDFUNDS", 4.33)
                    sofr_val = fed_funds  # SOFR tracks EFFR closely
                    sofr_spread = sofr_val - dgs3mo_val
                    print(f"[!] SOFR Spread: SOFR fetch failed. Using Fed Funds proxy ({fed_funds:.2f}%)")
                else:
                    # Both failed — use safe neutral spread
                    sofr_spread = 0.05
                    print(f"[!] SOFR Spread: Both SOFR and DGS3MO fetches failed. Using neutral fallback.")
                
                # Sanity clamp: A money-market spread outside ±50bps would indicate catastrophic
                # systemic stress that would be corroborated by VIX > 40 and HY spreads > 6%.
                if sofr_spread < -0.50 or sofr_spread > 1.00:
                    print(f"[!] SOFR Spread ({sofr_spread:+.4f}%) out of expected bounds [-0.50, +1.00]. Clamping.")
                    sofr_spread = max(-0.50, min(1.00, sofr_spread))
                
                return [
                    fetch_raw_fred("DGS10", 4.45), fetch_raw_fred("DGS30", 4.98),
                    fetch_raw_fred("BAMLH0A0HYM2", 2.72), sofr_spread,
                    fetch_raw_fred("FEDFUNDS", 4.33), fetch_raw_fred("VIXCLS", 15.74)
                ]
            result = await asyncio.to_thread(openbb_fetch)
            # Save to disk cache
            _save_to_disk_cache("macro_data", {"result": result, "status": status})
            _save_to_cache("macro_data", {
                "DGS10": result[0], "DGS30": result[1], "BAMLH0A0HYM2": result[2],
                "TEDRATE": result[3], "FEDFUNDS": result[4], "VIXCLS": result[5]
            })
        except Exception as e:
            print(f"[!] fetch_macro_data error: {e}")
            status = "DEGRADED_STALE"
            cached = _load_from_cache("macro_data", {
                "DGS10": 4.45, "DGS30": 4.98, "BAMLH0A0HYM2": 2.72,
                "TEDRATE": 0.05,
                "FEDFUNDS": 4.33, "VIXCLS": 15.74
            })
            result = [
                cached["DGS10"], cached["DGS30"], cached["BAMLH0A0HYM2"],
                cached["TEDRATE"], cached["FEDFUNDS"], cached["VIXCLS"]
            ]
            # Supplement with real-time Yahoo rates if available
            yf_live = _load_from_cache("yf_live_macro", {})
            if yf_live:
                result[0] = yf_live.get("y10", result[0])
                result[1] = yf_live.get("y30", result[1])
                result[5] = yf_live.get("vix", result[5])
                print("[*] [Macro Engine] Dynamic yfinance rates merged successfully.")
        return result, status

    async def fetch_real_yield(self):
        # 1. Check 12-hour local disk cache
        cached_data = _load_from_disk_cache("real_yield", 12.0)
        if cached_data is not None:
            print("[*] [Macro Engine] Cache HIT for real_yield. Loaded from disk instantly.")
            return cached_data["result"], cached_data["status"]

        status = "LIVE"
        try:
            def _fetch():
                try:
                    from openbb import obb
                    import os
                    if os.path.exists("FRED_API_KEY"):
                        with open("FRED_API_KEY", "r") as f:
                            obb.user.credentials.fred_api_key = f.read().strip()
                    res = obb.economy.fred_series("DFII10")
                    df = res.to_dataframe()
                    if not df.empty:
                        df_clean = df.replace('.', None).dropna()
                        return float(df_clean.iloc[-1].iloc[0])
                except:
                    # Level 2: Direct anonymous CSV download fallback
                    try:
                        import requests
                        import pandas as pd
                        import io
                        import numpy as np
                        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
                        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        if res.status_code == 200:
                            df = pd.read_csv(io.StringIO(res.text))
                            if not df.empty and "DFII10" in df.columns:
                                df_clean = df.replace('.', np.nan).dropna()
                                if not df_clean.empty:
                                    return float(df_clean["DFII10"].iloc[-1])
                    except Exception as e:
                        print(f"[!] Direct FRED CSV real yield fallback failed: {e}")

                    # Level 3: yfinance 10-year Treasury minus 2% proxy
                    try:
                        import yfinance as yf
                        tnx = yf.Ticker("^TNX").history(period="1d")
                        if not tnx.empty:
                            return max(0.0, float(tnx['Close'].iloc[-1]) - 2.0)
                    except: pass
                raise Exception("Real yield fetch failed")
            result = await asyncio.to_thread(_fetch)
            _save_to_disk_cache("real_yield", {"result": result, "status": status})
            _save_to_cache("real_yield", {"value": result})
        except Exception as e:
            print(f"[!] fetch_real_yield error: {e}")
            status = "DEGRADED_STALE"
            
            # Supplement with real-time derived real yield proxy if available
            yf_live = _load_from_cache("yf_live_macro", {})
            if yf_live and "y10" in yf_live:
                result = max(0.0, yf_live["y10"] - 2.0)
                print(f"[*] [Macro Engine] Derived degraded real yield from live yfinance proxy: {result:.2f}%")
            else:
                cached = _load_from_cache("real_yield", {"value": 1.8})
                result = cached["value"]
        return result, status

    async def fetch_dxy_momentum(self):
        status = "LIVE"
        try:
            def _fetch():
                t = yf.Ticker("DX-Y.NYB")
                hist = t.history(period="15d")
                if not hist.empty and len(hist) >= 10:
                    current_dxy = float(hist['Close'].iloc[-1])
                    prior_dxy = float(hist['Close'].iloc[-10])
                    mom = (current_dxy - prior_dxy) / prior_dxy * 100.0
                    return mom, current_dxy
                raise Exception("DXY fetch failed")
            mom, current_dxy = await asyncio.to_thread(_fetch)
            _save_to_cache("dxy_momentum", {"mom": mom, "current_dxy": current_dxy})
        except Exception as e:
            print(f"[!] fetch_dxy_momentum error: {e}")
            status = "DEGRADED_STALE"
            cached = _load_from_cache("dxy_momentum", {"mom": 0.0, "current_dxy": 99.0})
            mom, current_dxy = cached["mom"], cached["current_dxy"]
        return mom, current_dxy, status

    async def fetch_mri_history(self):
        """Phase 0 patch: seed/refresh a trailing multi-year history per MRI driver so calculate_mri
        can score each live value by its rolling percentile rank instead of a static, saturating
        min-max band. Sourced once from yfinance (silver/copper/gold/dxy/vix) and FRED (real yield,
        HY spread), cached to disk with a refresh_hours TTL, and reused across cycles. Any driver that
        fails to fetch is simply omitted -> calculate_mri falls back to the static norm for it."""
        cfg = self.get_config().get("mri_dynamic_bounds", {})
        if not cfg.get("enabled", False):
            return {}
        refresh_hours = float(cfg.get("refresh_hours", 24))
        lookback_years = int(cfg.get("lookback_years", 5))

        cached = _load_from_disk_cache("mri_history", refresh_hours)
        if cached is not None:
            print(f"[*] [Macro Engine] Cache HIT for mri_history ({len(cached)} drivers).")
            return cached

        def _fetch():
            period = f"{lookback_years}y"
            out = {}

            def _yf_closes(symbol):
                try:
                    h = yf.Ticker(symbol).history(period=period)
                    s = h['Close'].dropna() if (h is not None and 'Close' in h) else None
                    return s if (s is not None and len(s)) else None
                except Exception as e:
                    print(f"[!] mri_history yfinance fetch failed for {symbol}: {e}")
                    return None

            def _fred_series(series_id):
                try:
                    import requests, io
                    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                    if res.status_code == 200:
                        df = pd.read_csv(io.StringIO(res.text))
                        if not df.empty and series_id in df.columns:
                            df = df.replace('.', np.nan)
                            df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
                            df = df.dropna()
                            if len(df):
                                return df[series_id].astype(float).tail(lookback_years * 252)
                except Exception as e:
                    print(f"[!] mri_history FRED fetch failed for {series_id}: {e}")
                return None

            silver = _yf_closes("SI=F")
            copper = _yf_closes("HG=F")
            gold = _yf_closes("GC=F")
            dxy = _yf_closes("DX-Y.NYB")
            vix = _yf_closes("^VIX")

            if silver is not None: out["silver"] = [float(v) for v in silver.values]
            if dxy is not None: out["dxy"] = [float(v) for v in dxy.values]
            if vix is not None: out["vix"] = [float(v) for v in vix.values]

            # copper/gold ratio aligned on common trading dates
            if copper is not None and gold is not None:
                try:
                    joined = pd.concat([copper.rename('cu'), gold.rename('au')], axis=1).dropna()
                    ratio = (joined['cu'] / joined['au']).replace([np.inf, -np.inf], np.nan).dropna()
                    if len(ratio): out["copper_gold"] = [float(v) for v in ratio.values]
                except Exception as e:
                    print(f"[!] mri_history copper/gold ratio build failed: {e}")

            ry = _fred_series("DFII10")
            if ry is not None: out["real_yield"] = [float(v) for v in ry.values]
            hy = _fred_series("BAMLH0A0HYM2")
            if hy is not None: out["hy_spread"] = [float(v) for v in hy.values]

            return out

        try:
            out = await asyncio.to_thread(_fetch)
            if out:
                _save_to_disk_cache("mri_history", out)
                print(f"[*] [Macro Engine] mri_history seeded: { {k: len(v) for k, v in out.items()} }")
            return out
        except Exception as e:
            print(f"[!] fetch_mri_history error: {e}")
            stale = _load_from_disk_cache("mri_history", 24 * 365)  # reuse any prior history past TTL
            return stale or {}

    def calculate_mri(self, metrics, spot_ag, real_yield, copper, gold, dxy_mom=0.0, return_detail=False, history=None):
        try:
            dxy = float(metrics.get('DXY', {}).get('value', 100))
            ted = float(metrics.get('TED', {}).get('value', 0.3))
            vix = float(metrics.get('VIX', {}).get('value', 18))
            spreads = float(metrics.get('Spreads', {}).get('value', 3.5))
            y10 = float(metrics.get('10Y', {}).get('value', 4.2))
            y30 = float(metrics.get('30Y', {}).get('value', 4.4))
            cftc_net = float(metrics.get('CFTC_Silver_Net_Longs', {}).get('value', 35000.0))

            def norm(val, low, high):
                return max(0, min(100, (val - low) / (high - low) * 100))

            # Dynamic rolling-percentile bounds (Phase 0 patch): for the configured components, score
            # the live value by its percentile rank within a trailing window (default 5y) instead of a
            # static min-max. Static bounds permanently saturate at 0/100 once a price leaves the
            # historic band (silver pinned at 100 in the $70+ regime); a percentile against a CURRENT
            # window keeps the signal live. Each f_* preserves the same direction as its old norm
            # (low<high => ascending rank). Any component lacking >= min_obs cached observations, or
            # not listed, transparently falls back to the static norm so a cold cache never blocks.
            dyn_cfg = self.get_config().get("mri_dynamic_bounds", {})
            dyn_on = bool(dyn_cfg.get("enabled", False))
            dyn_components = set(dyn_cfg.get("components", []))
            min_obs = int(dyn_cfg.get("min_obs", 252))
            hist = history or {}
            basis = {}

            def score(component, raw_value, static_fn):
                if dyn_on and component in dyn_components:
                    series = hist.get(component)
                    if series and len(series) >= min_obs:
                        pr = _percentile_rank(series, raw_value)
                        if pr is not None:
                            basis[component] = {"mode": "dynamic", "percentile": round(pr, 1), "n": len(series)}
                            return pr
                basis[component] = {"mode": "static"}
                return static_fn()

            # 1. Liquidity & FX Score
            f_dxy = score("dxy", dxy, lambda: norm(dxy - 100, -5, 8))
            f_ted = norm(ted, 0.1, 0.9)
            f_ry = score("real_yield", real_yield, lambda: norm(real_yield, 0.5, 3.5))
            f_dxymom = norm(dxy_mom, -2.0, 2.0)
            liq_score = f_dxy * 0.30 + f_ted * 0.20 + f_ry * 0.30 + f_dxymom * 0.20

            # 2. Yield & Rate Curve Score
            f_curve, f_y10 = norm(y30 - y10, -0.5, 1.5), norm(y10, 3.0, 5.5)
            yield_score = f_curve * 0.50 + f_y10 * 0.50

            # 3. Volatility & Systemic Stress Score
            f_vix = score("vix", vix, lambda: norm(vix, 12, 35))
            f_hy = score("hy_spread", spreads, lambda: norm(spreads, 2, 7))
            vol_score = f_vix * 0.50 + f_hy * 0.50

            # 4. Physical Commodity Regimes (rolling percentile bounds; static fallback pre-seed)
            cu_au_ratio = copper / gold if gold > 0 else 0.00136
            f_cuau = score("copper_gold", cu_au_ratio, lambda: norm(cu_au_ratio, 0.0010, 0.0018))
            f_ag = score("silver", spot_ag, lambda: norm(spot_ag, 50.0, 100.0))
            comm_score = f_cuau * 0.60 + f_ag * 0.40

            # 5. Speculative Capitulation Score (Config-driven Normalization)
            # CFTC is INTENTIONALLY static: it is deliberately absent from mri_dynamic_bounds.components
            # because there is no free rolling COT history to seed into `history` (fetch_mri_history
            # sources yfinance/FRED only). score() therefore short-circuits to the static norm and
            # labels it "static" in bounds_basis — correct, not an oversight. NOTE: adding "cftc" to the
            # components list would NOT make it dynamic until a >= min_obs COT series is seeded into
            # mri_history["cftc"]; it would just keep falling back to static (handled gracefully).
            cftc_cfg = self.get_config().get("cftc_params", {"norm_low": -15000, "norm_high": 85000})
            sentiment_score = score("cftc", cftc_net, lambda: norm(cftc_net, cftc_cfg["norm_low"], cftc_cfg["norm_high"]))

            # Blended MRI Index (each block contributes score*weight; contributions sum to the MRI)
            block_w = {"liquidity_fx": 0.30, "yield_curve": 0.20, "volatility": 0.20, "commodity": 0.15, "sentiment": 0.15}
            block_s = {"liquidity_fx": liq_score, "yield_curve": yield_score, "volatility": vol_score, "commodity": comm_score, "sentiment": sentiment_score}
            mri = round(max(0, min(100, sum(block_s[k] * block_w[k] for k in block_w))), 1)

            if not return_detail:
                return mri

            labels = {"liquidity_fx": "Liquidity & FX", "yield_curve": "Yield & Curve", "volatility": "Volatility & Credit",
                      "commodity": "Commodity Regime", "sentiment": "Spec Positioning"}
            blocks = [
                {"key": k, "name": labels[k], "score": round(block_s[k], 1), "weight": block_w[k],
                 "contribution": round(block_s[k] * block_w[k], 1)}
                for k in block_w
            ]
            blocks_sorted = sorted(blocks, key=lambda b: b["contribution"], reverse=True)
            detail = {
                "mri": mri,
                "blocks": blocks_sorted,
                "top_driver": blocks_sorted[0]["name"],
                "drivers": {
                    "dxy_level": round(f_dxy, 0), "sofr_spread": round(f_ted, 0), "real_yield": round(f_ry, 0),
                    "dxy_momentum": round(f_dxymom, 0), "curve_2s30s": round(f_curve, 0), "y10": round(f_y10, 0),
                    "vix": round(f_vix, 0), "hy_spread": round(f_hy, 0), "copper_gold": round(f_cuau, 0),
                    "silver": round(f_ag, 0), "cftc_positioning": round(sentiment_score, 0)
                },
                # Phase 0: per-component bound mode (static vs dynamic rolling-percentile) + the live
                # percentile, so the cockpit can render e.g. "silver @ 92nd pct of 5y range".
                "bounds_basis": basis,
                "dynamic_active": [k for k, v in basis.items() if v.get("mode") == "dynamic"]
            }
            return mri, detail
        except Exception as e:
            print(f"[!] MRI calculation error: {e}")
            return (45.0, {"mri": 45.0, "blocks": [], "top_driver": "n/a", "drivers": {}}) if return_detail else 45.0


class PeerEngine:
    def __init__(self, config_path):
        self.config_path = config_path
        self.cached_mean_peer_ev_oz = 2.50
        self.peer_data_cache = {}

    def get_config(self):
        # When the orchestrator wires a config provider (CommodityExMonitor), serve the per-cycle
        # EFFECTIVE config (v5_config.json defaults + confirmed SQLite overrides) instead of a raw
        # file read. This is what makes a /confirm'd override actually reach live valuation, the JSF
        # gate, and the directives (previously every engine re-read the raw file and silently bypassed
        # the overlay), and it collapses ~dozens of redundant disk reads per cycle into one. Engines
        # constructed standalone (e.g. unit tests) have no provider -> identical legacy file read.
        provider = getattr(self, "_config_provider", None)
        if provider is not None:
            return provider()
        with open(self.config_path, "r") as f:
            return json.load(f)

    async def fetch_and_calculate_weighted_comps(self, usd_to_cad=1.38):
        cfg = self.get_config()
        v5_data = cfg.get("dynamic_discovery_v5", {})
        tickers = v5_data.get("peer_comp_tickers", [])
        peer_registry = v5_data.get("peer_registry", {})
        stage_multipliers = v5_data.get("stage_multipliers", {})
        mi_weight = v5_data.get("measured_indicated_weight", 1.00)
        inf_weight = v5_data.get("inferred_weight", 0.50)
        # Stage-normalization of peer EV/oz (bring every peer into AGA's stage frame before
        # blending) + relevance weighting (BRC.V full weight). Defensive: if the module or its
        # toggle is absent, fall through to the legacy per-peer stage_multiplier behavior.
        stage_norm_on = bool(v5_data.get("stage_normalization_enabled", False))
        target_stage = (cfg.get("portfolio_metadata", {}).get("AGA.V", {}) or {}).get("stage") \
            or v5_data.get("target_stage", "pre_pea")
        relevance = v5_data.get("peer_relevance_weights", {}) or {}
        stage_curve = v5_data.get("stage_curve")          # optional override; module default if None
        try:
            import peer_normalization as _pn
        except Exception:
            _pn = None
            stage_norm_on = False
        _rc = None
        try:
            import research_cache as _rcmod
            _rc = _rcmod.ResearchCache()
        except Exception:
            _rc = None

        def _sourced_eff_oz(tkr):
            """Confidence-weighted ounces from the SOURCED research cache (filings), tolerating the
            key spellings in the cache (ageq_oz_indicated/inferred, ageq_oz_mi for M&I). Returns None
            when unsourced so the caller falls back to the registry."""
            if _rc is None:
                return None
            ind = _rc.value(tkr, "ageq_oz_indicated") or _rc.value(tkr, "ageq_oz_mi") \
                or _rc.value(tkr, "in_ground_ageq_oz_indicated")
            inf = _rc.value(tkr, "ageq_oz_inferred") or _rc.value(tkr, "in_ground_ageq_oz_inferred")
            if ind is None and inf is None:
                return None
            if _pn is not None:
                return _pn.effective_oz(ind or 0.0, inf or 0.0, mi_weight=mi_weight, inf_weight=inf_weight)
            return max(0.0, (ind or 0.0) * mi_weight + (inf or 0.0) * inf_weight)
        guard = cfg.get("v5_guardrails", {})
        adv_window = int(guard.get("adv_window_days", 90))
        adv_method = guard.get("adv_method", "median")
        adv_halflife = int(guard.get("adv_ewma_halflife_days", 30))

        def _fetch():
            results = {}
            total_adv = 0.0
            peer_advs = {}

            for t in tickers:
                try:
                    ticker_obj = yf.Ticker(t)
                    info = ticker_obj.info

                    raw_val = info.get('enterpriseValue')
                    if not raw_val:
                        raw_val = info.get('marketCap', 0)

                    price = info.get('regularMarketPrice') or info.get('previousClose') or 1.0

                    # Average Daily Volume for the liquidity weight (Phase 0 patch): a 90-session MEDIAN
                    # of daily volume rather than a 10-day ADV, so a single panic-driven peer volume
                    # spike cannot distort the liquidity-weighted comp. Falls back to the info fields.
                    robust_vol = _robust_adv_shares(ticker_obj.history(period=f"{adv_window + 40}d"),
                                                    adv_window, adv_method, adv_halflife)
                    avg_vol = robust_vol if (robust_vol and robust_vol > 0) else (
                        info.get('averageVolume') or info.get('averageVolume10Day') or 50000)
                    currency = str(info.get('currency', 'CAD')).upper()
                    
                    adv_local = avg_vol * price
                    adv_cad = adv_local * usd_to_cad if currency == 'USD' else adv_local
                    peer_advs[t] = adv_cad
                    total_adv += adv_cad

                    # Convert EV to target CAD
                    normalized_ev = float(raw_val)
                    if currency == 'USD':
                        normalized_ev = normalized_ev * usd_to_cad
                    
                    # Fetch database attributes from Peer Registry
                    reg = peer_registry.get(t, {})
                    mi_pct = reg.get("measured_indicated_pct", 0.50)
                    j_risk = reg.get("jurisdiction_risk", 0.20)
                    stage = reg.get("development_stage", "PEA")
                    disc_cost = reg.get("historical_discovery_cost_oz", 0.50)

                    # Effective confidence-weighted ounces: prefer the SOURCED research cache
                    # (filings), fall back to the registry's single-figure resource. No-hardcode.
                    effective_oz = _sourced_eff_oz(t)
                    oz_source = "research_cache"
                    if effective_oz is None or effective_oz <= 0:
                        # NO FABRICATION: a peer listed in peer_comp_tickers but absent from BOTH the
                        # registry AND the research cache has no resource basis. Skip it rather than
                        # inject a fictional 100M-oz comp (one typo in peer_comp_tickers used to do
                        # exactly that, silently polluting the EV/oz blend).
                        reg_oz = reg.get("resources_oz_AgEq")
                        if not isinstance(reg_oz, (int, float)) or reg_oz <= 0:
                            print(f"[!] Skipping peer {t}: no sourced ounces and no registry resource "
                                  f"basis (won't fabricate a comp).")
                            continue
                        effective_oz = reg_oz * (mi_pct * mi_weight + (1.0 - mi_pct) * inf_weight)
                        oz_source = "registry(fallback)"

                    if effective_oz > 0 and normalized_ev > 0:
                        raw_ev_oz = normalized_ev / effective_oz
                        risk_discount = 1.0 - j_risk

                        if stage_norm_on and _pn is not None:
                            # Normalize the peer's EV/oz INTO AGA's stage frame, THEN apply the
                            # jurisdiction discount. A more-advanced peer (BRC.V) is de-rated down
                            # to AGA's pre-PEA frame instead of lending its richer multiple raw.
                            norm_ev_oz, stage_factor = _pn.normalize_ev_oz(
                                raw_ev_oz, peer_stage=stage, target_stage=target_stage, curve=stage_curve)
                            adjusted_ev_oz = norm_ev_oz * risk_discount
                        else:                                  # legacy path (toggle off / module absent)
                            stage_factor = stage_multipliers.get(stage, 1.0)
                            adjusted_ev_oz = raw_ev_oz * risk_discount * stage_factor

                        # Relevance weight (BRC.V full as the adjacent prime comp); liquidity ADV is
                        # kept for the legacy weighting path and for transparency.
                        rel_w = float(relevance.get(t, relevance.get("_default", 1.0)))

                        results[t] = {
                            "raw_ev_oz": raw_ev_oz,
                            "adjusted_ev_oz": adjusted_ev_oz,
                            "adv_cad": adv_cad,
                            "discovery_cost": disc_cost,
                            "effective_oz": effective_oz,
                            "oz_source": oz_source,
                            "price": price,
                            "jurisdiction_risk": j_risk,
                            "stage": stage,
                            "target_stage": target_stage,
                            "stage_factor": round(float(stage_factor), 4),
                            "relevance_weight": rel_w,
                        }
                except Exception as e:
                    print(f"[!] Failed to fetch/parse peer {t}: {e}")

            if not results:
                return 2.50, {}, 0.48

            # Blend the (stage-normalized) peer multiples. Relevance weighting (BRC.V full) when
            # stage-normalization is on; liquidity ADV weighting on the legacy path. Either way the
            # weight actually used is recorded per peer so the comp is auditable.
            weighted_ev_oz = 0.0
            sum_weights = 0.0
            sum_disc_cost = 0.0

            for t, data in results.items():
                liq_weight = data["adv_cad"] / total_adv if total_adv > 0 else 1.0 / len(results)
                w = data.get("relevance_weight", liq_weight) if stage_norm_on else liq_weight
                data["weight_used"] = round(float(w), 4)
                weighted_ev_oz += data["adjusted_ev_oz"] * w
                sum_weights += w
                sum_disc_cost += data["discovery_cost"]

            avg_disc_cost = sum_disc_cost / len(results) if results else 0.48
            final_mean_ev = weighted_ev_oz / sum_weights if sum_weights > 0 else 2.50
            return final_mean_ev, results, avg_disc_cost

        try:
            mean_ev, details, avg_disc = await asyncio.to_thread(_fetch)
            _save_to_cache("peer_comps", {
                "mean_ev": mean_ev,
                "details": details,
                "avg_disc": avg_disc
            })
        except Exception as e:
            print(f"[!] Peer comps fetch failed, loading from cache: {e}")
            cached = _load_from_cache("peer_comps", {
                "mean_ev": 2.50,
                "details": {},
                "avg_disc": 0.48
            })
            mean_ev = cached["mean_ev"]
            details = cached["details"]
            avg_disc = cached["avg_disc"]
            
        self.cached_mean_peer_ev_oz = mean_ev
        self.peer_data_cache = details
        return mean_ev, details, avg_disc


class ForensicEngine:
    def __init__(self, config_path, cache_path=".cache/forensic_cache.json", cache_ttl_seconds=86400):
        self.config_path = config_path
        self.cache_path = cache_path
        self.cache_ttl = cache_ttl_seconds
        self._lock = threading.Lock()
        
        # Ensure cache directory exists
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

    def get_config(self):
        # When the orchestrator wires a config provider (CommodityExMonitor), serve the per-cycle
        # EFFECTIVE config (v5_config.json defaults + confirmed SQLite overrides) instead of a raw
        # file read. This is what makes a /confirm'd override actually reach live valuation, the JSF
        # gate, and the directives (previously every engine re-read the raw file and silently bypassed
        # the overlay), and it collapses ~dozens of redundant disk reads per cycle into one. Engines
        # constructed standalone (e.g. unit tests) have no provider -> identical legacy file read.
        provider = getattr(self, "_config_provider", None)
        if provider is not None:
            return provider()
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _read_cache(self) -> dict:
        """Thread-safe read of the local JSON cache."""
        with self._lock:
            if not os.path.exists(self.cache_path):
                return {}
            try:
                with open(self.cache_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[!] Forensic Cache read error: {e}")
                return {}

    def _write_cache(self, ticker: str, data: dict):
        """Thread-safe write to the local JSON cache."""
        with self._lock:
            cache = {}
            if os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path, "r") as f:
                        cache = json.load(f)
                except Exception:
                    pass
            cache[ticker] = {
                "timestamp": time.time(),
                "data": data
            }
            try:
                with open(self.cache_path, "w") as f:
                    json.dump(cache, f, indent=4)
            except Exception as e:
                print(f"[!] Forensic Cache write error for {ticker}: {e}")

    async def fetch_forensic_metrics(self, ticker, usd_to_cad=1.38):
        # 1. Query thread-safe cache first
        cache = self._read_cache()
        cached_entry = cache.get(ticker)
        
        if cached_entry:
            timestamp = cached_entry.get("timestamp", 0)
            cached_data = cached_entry.get("data")
            
            # If cache is valid (within 24 hours), return immediately
            if time.time() - timestamp < self.cache_ttl:
                print(f"[*] Forensic Cache HIT (Fresh) for {ticker}")
                return cached_data

        # 2. Cache is missing or expired -> Fetch fresh data in a non-blocking thread
        def _fetch():
            try:
                print(f"[*] Fetching fresh quarterly statements from yfinance for {ticker}...")
                t = yf.Ticker(ticker)
                
                # Heavy synchronous fetches
                bs = t.quarterly_balance_sheet
                cf = t.quarterly_cashflow
                inc = t.quarterly_financials
                
                if bs.empty or cf.empty or inc.empty:
                    raise ValueError("Quarterly financial statements are empty or unavailable.")

                # INTEGRITY: every iloc[0]/iloc[1] below assumes columns are NEWEST-FIRST. That is
                # a yfinance convention, not a contract — if the provider ever returns oldest-first,
                # dilution velocity silently reads ~0 (clamped) and the Sloan accrual deltas flip
                # sign. Sort the period columns explicitly so the assumption is enforced, not hoped.
                def _newest_first(df):
                    try:
                        return df[sorted(df.columns, reverse=True)]
                    except Exception:
                        return df                              # unsortable columns: leave as-is
                bs, cf, inc = _newest_first(bs), _newest_first(cf), _newest_first(inc)

                def find_row(df, labels):
                    for label in labels:
                        match = [idx for idx in df.index if label.lower() in str(idx).lower()]
                        if match:
                            return df.loc[match[0]]
                    return None

                total_assets_series = find_row(bs, ['Total Assets'])
                net_income_series = find_row(inc, ['Net Income', 'Net Income Common Stockholders'])
                cfo_series = find_row(cf, ['Operating Cash Flow', 'Cash Flow From Operating Activities'])
                share_count_series = find_row(bs, ['Share Cap', 'Ordinary Shares Number', 'Common Stock Shares Outstanding'])
                
                _info = t.info
                # Ticker-keyed share count: feed -> SOURCED filing share count -> (AGA.V's filed
                # 208.6M ONLY for the spear). NEVER apply the spear's hardcoded share count to a
                # ballast name (cross-ticker contamination); an unsourced non-spear name gets 0.
                _src_sh = None
                try:
                    import research_cache as _rcmod
                    _src_sh = _rcmod.ResearchCache().value(ticker, "shares_out")
                except Exception:
                    _src_sh = None
                current_shares = (_info.get('sharesOutstanding') or _src_sh
                                  or (208600000 if ticker == "AGA.V" else 0))
                # Phase 0 patch: capture a size proxy (Enterprise Value, falling back to market cap)
                # so CBA can be normalized against EV instead of cash — i.e. not punish a lean treasury.
                enterprise_value = _info.get('enterpriseValue') or _info.get('marketCap')
                market_cap = _info.get('marketCap')
                # INTEGRITY: the feed's market cap / EV goes stale for post-merger micro-caps — it
                # missed AGA.V's merger issuance (shows ~$112M on ~173M implied shares vs the filed
                # 208.6M). Prefer a size computed from the SOURCED filing share count × live price
                # (less treasury cash for EV), so the JSF/CBA gate is never normalized against a stale
                # size. The cash netted is THIS ticker's own treasury: config cash_treasury_m is the
                # SPEAR's, so it is subtracted ONLY for AGA.V — never a ballast name's EV against the
                # spear's cash (which also mixed CAD into a possibly-USD mcap). Falls back to the feed
                # for any name we haven't sourced. Never raises.
                try:
                    _px = (_info.get('regularMarketPrice') or _info.get('currentPrice')
                           or _info.get('previousClose'))
                    if _src_sh and _px and float(_src_sh) > 0 and float(_px) > 0:
                        _src_mcap = float(_src_sh) * float(_px)
                        _cash = (float(self.get_config().get("rep_floor_params", {})
                                       .get("cash_treasury_m", 0.0) or 0.0) * 1e6) if ticker == "AGA.V" else 0.0
                        if market_cap and abs(_src_mcap / float(market_cap) - 1.0) > 0.10:
                            logging.info("Forensic EV: feed mcap %.0f stale vs sourced %.0f for %s "
                                         "— using sourced", float(market_cap), _src_mcap, ticker)
                        market_cap = _src_mcap
                        enterprise_value = max(0.0, _src_mcap - _cash)
                except Exception:
                    pass

                if total_assets_series is None or cfo_series is None or net_income_series is None:
                    raise ValueError("Critical financial statement rows missing.")

                tot_assets_t0 = float(total_assets_series.iloc[0])
                net_inc_t0 = float(net_income_series.iloc[0])
                cfo_t0 = float(cfo_series.iloc[0])
                
                shares_t0 = float(share_count_series.iloc[0]) if (share_count_series is not None and len(share_count_series) > 0) else current_shares
                shares_t1 = float(share_count_series.iloc[1]) if (share_count_series is not None and len(share_count_series) > 1) else shares_t0
                
                sga_series = find_row(inc, ['Selling General and Administrative', 'General and Administrative', 'SG&A'])
                sga_t0 = float(sga_series.iloc[0]) if (sga_series is not None and len(sga_series) > 0) else 0.0

                sloan_cfo = (net_inc_t0 - cfo_t0) / tot_assets_t0 if tot_assets_t0 > 0 else 0.0
                cfo_t1 = float(cfo_series.iloc[1]) if len(cfo_series) > 1 else cfo_t0
                
                sloan_bs = sloan_cfo
                cash_t0 = None
                
                cash_series = find_row(bs, ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'])
                da_series = find_row(cf, ['Depreciation And Amortization', 'Depreciation & Amortization'])
                ca_series = find_row(bs, ['Total Current Assets', 'Current Assets'])
                cl_series = find_row(bs, ['Total Current Liabilities', 'Current Liabilities'])

                if cash_series is not None and len(cash_series) > 0:
                    try:
                        cash_t0 = float(cash_series.iloc[0])
                    except:
                        pass

                if ca_series is not None and cl_series is not None and cash_series is not None:
                    try:
                        ca_t0, ca_t1 = float(ca_series.iloc[0]), float(ca_series.iloc[1]) if len(ca_series) > 1 else float(ca_series.iloc[0])
                        cl_t0, cl_t1 = float(cl_series.iloc[0]), float(cl_series.iloc[1]) if len(cl_series) > 1 else float(cl_series.iloc[0])
                        cash_t0_val, cash_t1 = float(cash_series.iloc[0]), float(cash_series.iloc[1]) if len(cash_series) > 1 else float(cash_series.iloc[0])
                        cash_t0 = cash_t0_val
                        da_t0 = float(da_series.iloc[0]) if (da_series is not None and len(da_series) > 0) else 0.0
                        
                        d_ca = ca_t0 - ca_t1
                        d_cash = cash_t0_val - cash_t1
                        d_cl = cl_t0 - cl_t1
                        
                        bs_accruals = (d_ca - d_cash) - d_cl - da_t0
                        sloan_bs = bs_accruals / tot_assets_t0 if tot_assets_t0 > 0 else 0.0
                    except Exception as e:
                        print(f"[DEBUG] Sloan BS accrual calculation exception: {e}")

                return {
                    "sloan_cfo": sloan_cfo,
                    "sloan_bs": sloan_bs,
                    "shares_t0": shares_t0,
                    "shares_t1": shares_t1,
                    "sga_t0": sga_t0,
                    "tot_assets_t0": tot_assets_t0,
                    "cfo_t0": cfo_t0,
                    "cfo_t1": cfo_t1,
                    "cash_t0": cash_t0,
                    "enterprise_value": enterprise_value,
                    "market_cap": market_cap
                }
            except Exception as e:
                print(f"[!] yfinance fetch failed for {ticker}: {e}")
                return None

        fresh_data = await asyncio.to_thread(_fetch)
        
        if fresh_data:
            # Succesfully fetched; store to thread-safe cache
            self._write_cache(ticker, fresh_data)
            return fresh_data
        
        # 3. High-Reliability Stale Fallback: If fetch failed but we have expired cached data, use it!
        if cached_entry:
            age = time.time() - cached_entry["timestamp"]
            print(f"[WARNING] Using EXPIRED/STALE cache for {ticker} (Age: {age/3600:.1f} hours) to prevent degradation.")
            return cached_entry["data"]

        # 4. Critical Failure: No cache exists at all
        print(f"[CRITICAL] No cache and no live data for {ticker}. Returning None.")
        return None

    @staticmethod
    def _override_active(overrides, key, today=None, max_validity_days=45):
        """A manual forensic override is honored ONLY when explicitly enabled AND carrying a
        governance trail: a non-empty `justification` and an `expiry` (YYYY-MM-DD) that is in the
        future but no further than `max_validity_days` away. Silent, unjustified, expired, OR
        long-dated overrides are ignored so the real forensic test re-engages. Bounding the window
        forces short, frequently re-confirmed waivers and prevents the riskiest holding from having
        its safety gates disabled indefinitely (v5.2)."""
        if not isinstance(overrides, dict) or not overrides.get(key, False):
            return False
        justification = str(overrides.get("justification", "")).strip()
        expiry = str(overrides.get("expiry", "")).strip()
        if not justification or not expiry:
            return False
        try:
            import datetime as _dt
            today_d = _dt.date.fromisoformat(today) if today else _dt.date.today()
            days_left = (_dt.date.fromisoformat(expiry) - today_d).days
            return 0 <= days_left <= max(1, int(max_validity_days))
        except Exception:
            return False

    @staticmethod
    def _override_days_left(overrides, today=None):
        """Days until an override's expiry (None if unparseable); for the confirm-on-use audit trail."""
        try:
            import datetime as _dt
            today_d = _dt.date.fromisoformat(today) if today else _dt.date.today()
            return (_dt.date.fromisoformat(str(overrides.get("expiry", "")).strip()) - today_d).days
        except Exception:
            return None

    def calculate_jsf_score(self, ticker, cash, monthly_burn, sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense, cfo_t0=None, cfo_t1=None, cash_t0=None, today=None, enterprise_value=None):
        cfg = self.get_config()
        metadata = cfg.get("portfolio_metadata", {}).get(ticker, {})
        asset_type = metadata.get("type", "explorer")
        forensic_thresholds = cfg.get("forensic_thresholds", {})

        score = 0.0
        details = {}
        overrides_applied = []
        max_validity_days = cfg.get("forensic_override_policy", {}).get("max_validity_days", 45)
        
        # 1. Cash Runway Test
        runway = cash / monthly_burn if monthly_burn > 0 else 99.0
        runway_pass = runway >= forensic_thresholds.get("runway_min_months", 18.0)
        if runway_pass:
            score += 1.0
            details["runway"] = {"pass": True, "value": runway, "desc": f"Runway >= 18 mo ({runway:.1f} mo)"}
        else:
            details["runway"] = {"pass": False, "value": runway, "desc": f"Short Runway ({runway:.1f} mo)"}
            
        # 2. Accrual / Burn Test
        cba = 0.0
        if asset_type == "explorer":
            # Cash Burn Acceleration (CBA). Phase 0 patch: normalize the quarter-over-quarter change in
            # burn against ENTERPRISE VALUE (a size proxy) rather than Total Cash. Dividing by cash
            # disproportionately penalizes micro-cap explorers that deliberately hold a lean treasury —
            # a smaller denominator inflates the ratio and trips the gate on otherwise-healthy names.
            # EV >> cash, so the threshold drops from 0.15 (fraction of cash) to ~0.03 (fraction of EV).
            # When EV is unavailable (degraded feed) we fall back to the original cash-based test so
            # behavior and existing tests are preserved.
            total_cash = cash_t0 if cash_t0 is not None else cash
            curr_burn = -cfo_t0 if cfo_t0 is not None else (monthly_burn * 3.0)
            prev_burn = -cfo_t1 if cfo_t1 is not None else curr_burn
            burn_accel = curr_burn - prev_burn
            cba_cash = burn_accel / total_cash if total_cash > 0 else 0.0  # retained for audit/continuity

            denom_mode = forensic_thresholds.get("cba_denominator", "enterprise_value")
            ev_floor = forensic_thresholds.get("cba_ev_floor", 5_000_000)
            use_ev = (denom_mode == "enterprise_value") and (enterprise_value is not None) and (enterprise_value > 0)
            if use_ev:
                cba = burn_accel / max(ev_floor, float(enterprise_value))
                cba_threshold = forensic_thresholds.get("max_burn_acceleration_ev_pct", 0.03)
                cba_basis = "EV"
            else:
                cba = cba_cash
                cba_threshold = forensic_thresholds.get("max_burn_acceleration_pct", 0.15)
                cba_basis = "cash"

            real_cba_pass = cba <= cba_threshold
            overrides = cfg.get("forensic_overrides", {}).get(ticker, {})
            cba_override = self._override_active(overrides, "cba_insulated", today, max_validity_days)
            cba_pass = real_cba_pass or cba_override

            if cba_pass:
                score += 1.0
                insulated = cba_override and not real_cba_pass
                desc = "CBA Insulated" if insulated else f"CBA <= {cba_threshold*100:.0f}% ({cba_basis})"
                details["accrual"] = {"pass": True, "value": cba, "desc": f"{desc} ({cba*100:.1f}%)", "overridden": insulated,
                                      "basis": cba_basis, "cba_cash": cba_cash, "threshold": cba_threshold}
                if insulated:
                    overrides_applied.append({"test": "cba", "justification": overrides.get("justification", ""),
                                              "expiry": overrides.get("expiry", ""),
                                              "days_until_expiry": self._override_days_left(overrides, today),
                                              "requires_confirmation": True})
            else:
                details["accrual"] = {"pass": False, "value": cba, "desc": f"Burn accelerating ({cba*100:.1f}% of {cba_basis})", "overridden": False,
                                      "basis": cba_basis, "cba_cash": cba_cash, "threshold": cba_threshold}
        else:
            # Standard Sloan Ratio Check (Integrates both CFO and BS Accruals for high safety)
            sloan_thresh = forensic_thresholds.get("sloan_accrual_threshold", 0.05)
            sloan_pass = (sloan_cfo < sloan_thresh) and (sloan_bs < sloan_thresh)
            if sloan_pass:
                score += 1.0
                details["accrual"] = {
                    "pass": True,
                    "value": sloan_cfo,
                    "desc": f"Sloan CFO < 5% ({sloan_cfo*100:.1f}%) & BS < 5% ({sloan_bs*100:.1f}%)"
                }
            else:
                # Select the violating or higher value to preserve float type compatibility in test asserts
                violating_val = sloan_cfo if sloan_cfo >= 0.05 else sloan_bs
                details["accrual"] = {
                    "pass": False,
                    "value": violating_val,
                    "desc": f"Accrual overload (CFO: {sloan_cfo*100:.1f}%, BS: {sloan_bs*100:.1f}%)"
                }

        # 3. Share Dilution Test
        dilution = 0.0
        if shares_t1 > 0:
            dilution = (shares_t0 - shares_t1) / shares_t1
            if dilution < 0: dilution = 0.0
        
        real_dilution_pass = dilution < (forensic_thresholds.get("max_qoq_dilution_pct", 2.0) / 100.0)
        overrides = cfg.get("forensic_overrides", {}).get(ticker, {})
        dilution_override = self._override_active(overrides, "dilution_insulated", today, max_validity_days)
        dilution_pass = real_dilution_pass or dilution_override

        if dilution_pass:
            score += 1.0
            insulated = dilution_override and not real_dilution_pass
            desc = "Dilution Insulated" if insulated else "Dilution < 2% QoQ"
            details["dilution"] = {"pass": True, "value": dilution, "desc": f"{desc} ({dilution*100:.1f}%)", "overridden": insulated}
            if insulated:
                overrides_applied.append({"test": "dilution", "justification": overrides.get("justification", ""),
                                          "expiry": overrides.get("expiry", ""),
                                          "days_until_expiry": self._override_days_left(overrides, today),
                                          "requires_confirmation": True})
        else:
            details["dilution"] = {"pass": False, "value": dilution, "desc": f"Share count expanded ({dilution*100:.1f}%)", "overridden": False}

        # 4. SG&A Drag Test
        quarterly_burn = monthly_burn * 3.0
        sga_ratio = sga_expense / quarterly_burn if quarterly_burn > 0 else 0.0
        sga_pass = sga_ratio < forensic_thresholds.get("max_sga_ratio", 0.30)
        if sga_pass:
            score += 1.0
            details["sga_drag"] = {"pass": True, "value": sga_ratio, "desc": f"SG&A drag < 30% ({sga_ratio*100:.1f}%)"}
        else:
            details["sga_drag"] = {"pass": False, "value": sga_ratio, "desc": f"Bloated corporate drag ({sga_ratio*100:.1f}%)"}

        # Penalty Factor calculation
        if asset_type == "explorer":
            # 35% Dilution, 21.67% Runway, CBA, SG&A
            dilution_penalty = 0.0 if dilution_pass else 1.0
            runway_penalty = 0.0 if runway_pass else 1.0
            cba_penalty = 0.0 if cba_pass else 1.0
            sga_penalty = 0.0 if sga_pass else 1.0
            
            weighted_penalty = 0.35 * dilution_penalty + 0.21666666666666667 * (runway_penalty + cba_penalty + sga_penalty)
            penalty_factor = 1.0 - 0.30 * weighted_penalty
        else:
            penalty_factor = 0.70 + 0.30 * (score / 4.0)

        details["overrides_applied"] = overrides_applied
        return score, penalty_factor, details


class ValuationEngine:
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
        # When the orchestrator wires a config provider (CommodityExMonitor), serve the per-cycle
        # EFFECTIVE config (v5_config.json defaults + confirmed SQLite overrides) instead of a raw
        # file read. This is what makes a /confirm'd override actually reach live valuation, the JSF
        # gate, and the directives (previously every engine re-read the raw file and silently bypassed
        # the overlay), and it collapses ~dozens of redundant disk reads per cycle into one. Engines
        # constructed standalone (e.g. unit tests) have no provider -> identical legacy file read.
        provider = getattr(self, "_config_provider", None)
        if provider is not None:
            return provider()
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _sourced_spear_resource(self, ticker="AGA.V"):
        """Sourced in-ground AgEq ounces (indicated, inferred) for the spear, from the research
        cache (filings). Returns ``(indicated, inferred)`` or None when unsourced — so the spear
        market leg can reconcile its config project buckets to filings (magnitude + the REAL M&I /
        inferred confidence split) instead of trusting hardcoded per-project confidence guesses.
        Defensive: any problem -> None -> the legacy config behavior is untouched."""
        try:
            import research_cache
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            ind = self._rc.value(ticker, "in_ground_ageq_oz_indicated")
            if ind is None:
                ind = self._rc.value(ticker, "ageq_oz_indicated")
            if ind is None:
                ind = self._rc.value(ticker, "ageq_oz_mi")
            inf = self._rc.value(ticker, "in_ground_ageq_oz_inferred")
            if inf is None:
                inf = self._rc.value(ticker, "ageq_oz_inferred")
            if ind is None and inf is None:
                return None
            return float(ind or 0.0), float(inf or 0.0)
        except Exception:
            return None

    def calculate_rep_floor(self, shares_outstanding=None, effective_oz=None):
        """Stressed liquidation floor ($/share): cash + heavily-discounted effective ounces +
        permitting/infra, conservatism-scaled, per share.

        ``effective_oz`` lets the caller pass the ALREADY-RECONCILED effective ounce count (filings
        magnitude + the sourced sitewide M&I/inferred split) so the COST leg and the MARKET leg of
        the triangulation value the SAME resource base. Previously the floor always used the config
        project buckets x target_mi (a far more optimistic ~60% M&I) while the market leg reconciled
        to ~96%-inferred filings, biasing the floor HIGH exactly where the blend leans on it. Omitted
        (the standalone/legacy call) it falls back to config buckets — byte-identical to before."""
        cfg = self.get_config()
        shares = shares_outstanding if shares_outstanding is not None else cfg["aga_shares_out"]
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        infra_component = rf["permitting_infra_premium_m"] * 1_000_000

        if effective_oz is None:
            buckets = cfg.get("project_buckets_oz_AgEq", {})
            target_mi_pct = cfg.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
            # Enforce symmetric inferred ounces haircut (50% discount to Inferred)
            total_effective_oz = 0.0
            for proj, oz in buckets.items():
                mi_pct = target_mi_pct.get(proj, 0.50)
                measured_indicated_oz = oz * mi_pct
                inferred_oz = oz * (1.0 - mi_pct)
                total_effective_oz += (measured_indicated_oz * 1.0) + (inferred_oz * 0.50)
        else:
            total_effective_oz = max(0.0, float(effective_oz))

        resource_component = total_effective_oz * rf["stressed_resource_per_oz"]
        total_rep_value = cash_component + resource_component + infra_component
        rep_floor = (total_rep_value * rf["conservatism_scalar"]) / shares
        return rep_floor

    @staticmethod
    def _softplus(x, beta):
        # Numerically-stable softplus (1/beta)*ln(1 + exp(beta*x)); a smooth (C-infinity)
        # approximation of max(0, x). Used to round off slope-kinks without value jumps.
        return float(np.logaddexp(0.0, beta * x) / beta)

    def calculate_jurisdiction_uplift(self, spot_ag):
        # Smooth logistic ramp replacing the discontinuous (spot_ag > 50 -> 1.35 else 1.15) cliff.
        # Asymptotes to `low` for weak silver and `high` for strong silver, with no step at the center.
        p = self.get_config().get("jurisdiction_uplift_params", {
            "low": 1.15, "high": 1.35, "center_spot_ag": 50.0, "steepness": 0.30
        })
        low, high = p["low"], p["high"]
        center, k = p["center_spot_ag"], p["steepness"]
        return low + (high - low) / (1.0 + np.exp(-k * (spot_ag - center)))

    def calculate_capital_discount_factor(self, y30):
        # Smooth cost-of-capital discount replacing max(0.40, 1.0 - (y30 - 4.0)*0.12) gated at y30 > 4.0.
        # The softplus hinges remove the slope-kinks at the onset and the floor while preserving the
        # value away from those kinks (e.g. the live y30 ~ 5.0 operating point is unchanged to 4 dp).
        p = self.get_config().get("capital_discount_params", {
            "onset_y30": 4.0, "slope": 0.12, "floor": 0.40, "onset_beta": 8.0, "floor_beta": 25.0
        })
        excess = self._softplus(y30 - p["onset_y30"], p["onset_beta"])
        raw = 1.0 - p["slope"] * excess
        # Smooth lower bound: floor + softplus(raw - floor) -> max(floor, raw) as beta grows.
        return p["floor"] + self._softplus(raw - p["floor"], p["floor_beta"])

    def calculate_continuous_rov(self, real_yield, spot_ag, rov_default=1.18, silver_vol=0.25):
        # Continuous Options Convexity
        negative_yield_premium = min(0.50, max(0.0, 1.0 - real_yield) * 0.25)
        vol_premium = max(0.0, (silver_vol - 0.20) * 0.50)
        rov = rov_default * (1.0 + negative_yield_premium) * (1.0 + vol_premium)
        return rov

    def calculate_is_iai(self, peer_ev_oz, discovery_premium_factor, spot_ag, capital_discount_factor, shares_outstanding=None):
        cfg = self.get_config()
        shares = shares_outstanding if shares_outstanding is not None else cfg["aga_shares_out"]
        buckets = cfg.get("project_buckets_oz_AgEq", {})
        recovery = cfg.get("metallurgical_recovery", {})
        target_mi_pct = cfg.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
        
        jurisdiction_uplift = self.calculate_jurisdiction_uplift(spot_ag)

        is_iai_total = 0.0
        for proj, oz in buckets.items():
            rec_silver = recovery.get(proj, {}).get("silver", 0.85)
            # Enforce symmetric inferred ounces haircut (50% discount to Inferred)
            mi_pct = target_mi_pct.get(proj, 0.50)
            measured_indicated_oz = oz * mi_pct
            inferred_oz = oz * (1.0 - mi_pct)
            effective_oz = (measured_indicated_oz * 1.0) + (inferred_oz * 0.50)
            
            # Market Value = Effective Ounces * Peer EV/oz * Premium Guardrail * Jurisdiction Uplift * Recovery * Cost of Capital
            is_iai_total += effective_oz * peer_ev_oz * discovery_premium_factor * jurisdiction_uplift * rec_silver * capital_discount_factor

        is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / shares
        return is_iai_per_share, jurisdiction_uplift

    def calculate_ballast_fair_value(self, ref_price, base_mult, spot_now, spot_ref, spot_beta, forensic_pen=1.0):
        """Spot-linked ballast fair value, DECOUPLED from the name's own market price.

        A royalty/producer's intrinsic value is driven by the underlying COMMODITY, not by its
        own share-price action. Pre-v5.2 the ballast sleeve was valued as `live_price * multiple`,
        which made fair value track the very price it was being compared against: a rally lifted
        the "fair value" by the same proportion, so Implied Upside never compressed (a self-
        referential mirage). Here fair value is anchored to a fundamental reference
        (`ref_price * base_mult`, defined at the commodity level `spot_ref`) and re-scaled by the
        LIVE commodity spot only:

            spot_factor = max(0, 1 + spot_beta * (spot_now / spot_ref - 1))
            fair_value  = ref_price * base_mult * spot_factor * forensic_pen

        The live share price never enters this expression — it only enters the cost-basis PPI —
        so a price pump can no longer manufacture phantom implied upside. spot_beta encodes
        commodity leverage (~1.0 for a pure royalty; >1 for an operating producer)."""
        if ref_price <= 0 or spot_ref <= 0:
            return 0.0
        spot_factor = max(0.0, 1.0 + spot_beta * ((spot_now / spot_ref) - 1.0))
        return max(0.0, ref_price * base_mult * spot_factor * forensic_pen)

    # ====================== PHASE 4a — TRIANGULATED VALUATION ======================
    def calculate_technical_quality(self, project):
        """Transparent, bounded Technical-Quality multiplier so in-situ ounces are NOT fungible.
        TQ = clamp( product of per-factor bands, tq_min, tq_max ). Each factor maps a documented
        geological/operational driver onto a band. The M&I<->Inferred confidence haircut is
        deliberately NOT a TQ factor (it lives in effective_oz) to avoid double-counting confidence.
        f_jurisdiction reads the REAL Fraser index (fixing the old silver-price misnomer);
        f_metallurgy blends Ag+Au recovery on the AgEq split (fixing the dropped-gold bug)."""
        cfg = self.get_config()
        tqc = cfg.get("technical_quality", {})
        if not tqc.get("enabled", True):
            return {"tq": 1.0, "factors": {}}
        fcfg = tqc.get("factors", {})
        proj = tqc.get("projects", {}).get(project, {})

        def band(name, s):
            fc = fcfg.get(name, {})
            lo, hi = fc.get("lo", 1.0), fc.get("hi", 1.0)
            return lo + (hi - lo) * max(0.0, min(1.0, s))

        g = fcfg.get("grade", {})
        bench = g.get("benchmark_gpt_ageq", 250) or 250
        grade = proj.get("grade_gpt_ageq", bench)
        f_grade = band("grade", grade / (2.0 * bench))               # grade == benchmark -> mid-band

        m = fcfg.get("metallurgy", {})
        a_ag = proj.get("ageq_share_ag", 0.7); a_au = proj.get("ageq_share_au", 0.3)
        rec_blend = a_ag * proj.get("rec_ag", 0.85) + a_au * proj.get("rec_au", 0.92)
        f_met = band("metallurgy", (rec_blend - m.get("rec_lo", 0.70)) / max(1e-9, m.get("rec_hi", 0.95) - m.get("rec_lo", 0.70)))

        j = fcfg.get("jurisdiction", {})
        fraser = proj.get("fraser", 75.0)
        f_jur = band("jurisdiction", (fraser - j.get("fraser_lo", 50)) / max(1e-9, j.get("fraser_hi", 95) - j.get("fraser_lo", 50)))

        f_inf = band("infrastructure", proj.get("infrastructure", 0.5))
        f_dep = band("depth", proj.get("depth", 0.5))

        # Surface which inputs fell back to mid-band defaults: an unconfigured project silently scores
        # TQ ~ 1.0 (mid-band) with no flag, which over-credits ounces that have no sourced geology.
        _expected = ("grade_gpt_ageq", "ageq_share_ag", "ageq_share_au", "rec_ag", "rec_au",
                     "fraser", "infrastructure", "depth")
        defaults_used = [k for k in _expected if k not in proj]

        tq_raw = f_grade * f_met * f_jur * f_inf * f_dep
        tq = max(tqc.get("tq_min", 0.55), min(tqc.get("tq_max", 1.70), tq_raw))
        return {"tq": round(tq, 4), "project_configured": bool(proj), "defaults_used": defaults_used,
                "factors": {
            "grade": round(f_grade, 3), "metallurgy": round(f_met, 3), "jurisdiction": round(f_jur, 3),
            "infrastructure": round(f_inf, 3), "depth": round(f_dep, 3),
            "rec_blend": round(rec_blend, 3), "raw": round(tq_raw, 3)}}

    def calculate_option_premium(self, spot_ag, aisc, silver_vol, real_yield, stage="explorer", peer_aisc=None):
        """Dimensionally-coherent option/convexity premium pi_opt (a FRACTION >= 0) applied
        MULTIPLICATIVELY to the market leg. Replaces the dead additive ROV term and the mislabeled
        discovery_premium_factor. Captures convexity NOT already in the comps: peer EV/oz already
        prices the live silver LEVEL, so the absolute moneyness is excluded to avoid double-counting;
        only realized vol, monetary carry, and any RELATIVE operating-leverage edge (target vs peer
        AISC) contribute. Decays by stage (explorer IS an option; producer is cash).

        The relative-moneyness term needs a genuine PROJECT AISC for the target. A pre-PEA explorer
        has none (only an INDUSTRY aisc is available), so `peer_aisc` is None and the term is
        structurally inactive. Rather than let its configured weight (the largest) silently shrink
        the premium, when the term is inactive its weight is DROPPED and vol+carry are RENORMALIZED
        to the active basis — so the convexity the model genuinely has (vol + carry) is expressed at
        full weight. When a real peer_aisc edge is supplied (developer/producer stages) all three
        terms apply at their configured weights."""
        cfg = self.get_config()
        oc = cfg.get("option_premium", {})
        if not oc.get("enabled", True):
            return {"pi_opt": 0.0, "vol_term": 0.0, "carry_term": 0.0, "moneyness_excess": 0.0,
                    "stage_cap": 0.0, "moneyness_active": False,
                    "weights_used": {"moneyness": 0.0, "vol": 0.0, "carry": 0.0}}
        w = oc.get("weights", {"moneyness": 0.40, "vol": 0.35, "carry": 0.25})
        w_money, w_vol, w_carry = w.get("moneyness", 0.40), w.get("vol", 0.35), w.get("carry", 0.25)
        sv = silver_vol if (silver_vol and silver_vol > 0) else 0.30
        # comps_overlap_keep: peer EV/oz is a MARKET multiple, so the peers' own caps already re-rate
        # partially on silver vol / falling real yields — i.e. the comps embed SOME of this convexity.
        # Keep only the fraction NOT already priced in (default 0.70 -> a 30% haircut) so (1+pi_opt) on
        # top of the comps does not double-count vol/carry. (The relative-moneyness edge below is a
        # target-vs-peer differential genuinely absent from the comps, so it is NOT haircut.)
        overlap_keep = oc.get("comps_overlap_keep", 1.0)
        vol_term = min(oc.get("vol_cap", 0.40), max(0.0, sv - oc.get("vol_floor", 0.20)) * oc.get("vol_k", 1.0)) * overlap_keep
        carry_term = min(oc.get("carry_cap", 0.50), max(0.0, oc.get("carry_breakeven", 1.0) - real_yield) * oc.get("carry_k", 0.25)) * overlap_keep

        moneyness_active = bool(peer_aisc and peer_aisc > 0 and aisc > 0 and abs(peer_aisc - aisc) > 1e-9)
        if moneyness_active:
            moneyness = max(0.0, (spot_ag - aisc) / aisc) if aisc > 0 else 0.0
            peer_moneyness = max(0.0, (spot_ag - peer_aisc) / peer_aisc) if peer_aisc > 0 else 0.0
            moneyness_excess = min(oc.get("moneyness_cap", 1.50), max(0.0, moneyness - peer_moneyness))
        else:
            # no relative-AISC edge available -> drop the term and renormalize vol+carry to sum to 1
            moneyness_excess = 0.0
            active = w_vol + w_carry
            if active > 0:
                w_vol, w_carry = w_vol / active, w_carry / active
            w_money = 0.0

        stage_cap = oc.get("stage_optionality_cap", {}).get(stage, 0.5)
        pi_opt = stage_cap * (w_money * moneyness_excess + w_vol * vol_term + w_carry * carry_term)
        return {"pi_opt": round(pi_opt, 4), "vol_term": round(vol_term, 4), "carry_term": round(carry_term, 4),
                "moneyness_excess": round(moneyness_excess, 4), "stage_cap": stage_cap,
                "moneyness_active": moneyness_active,
                "weights_used": {"moneyness": round(w_money, 4), "vol": round(w_vol, 4), "carry": round(w_carry, 4)}}

    def calculate_spear_intrinsic(self, peer_ev_oz, spot_ag, capital_discount_factor, real_yield,
                                  silver_vol, forensic_penalty, dynamic_aisc, shares_outstanding=None,
                                  p_discovery=None):
        """Triangulated explorer intrinsic ($/share): confidence-tilted blend of a Cost leg (REP
        floor) and a quality-graded, de-overlapped Market leg lifted by the option-convexity premium.
        Income leg is 0 for a pure explorer. Returns the full auditable breakdown."""
        cfg = self.get_config()
        shares = shares_outstanding if shares_outstanding is not None else cfg["aga_shares_out"]
        buckets = cfg.get("project_buckets_oz_AgEq", {})
        target_mi = cfg.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
        conservatism = cfg.get("conservatism_scalar", 0.88)
        tri = cfg.get("triangulation", {})
        sw = tri.get("stage_weights", {}).get("explorer", {"cost": 0.30, "market": 0.70, "income": 0.0})
        cc = tri.get("confidence", {})

        # --- MARKET LEG: comps x technical quality, de-overlapped (NO discovery multiplier) ---
        # NO-HARDCODE reconciliation: the config project buckets carry per-project ounces + an
        # assumed M&I% (target_mi). When the SOURCED resource is available (filings), reconcile the
        # buckets to it — scale total ounces to the sourced magnitude AND replace the per-project
        # confidence guesses with the REAL sitewide M&I/inferred split (AGA.V is ~96% inferred, far
        # less confident than the config assumed). Per-project TQ is preserved. Toggle + transparent.
        use_sourced = cfg.get("dynamic_discovery_v5", {}).get("use_sourced_spear_oz", True)
        sum_buckets = sum(v for v in buckets.values() if isinstance(v, (int, float)))
        sourced = self._sourced_spear_resource("AGA.V") if use_sourced else None
        reconcile = None
        if sourced and (sourced[0] + sourced[1]) > 0 and sum_buckets > 0:
            s_ind, s_inf = sourced
            s_total = s_ind + s_inf
            s_mi = s_ind / s_total
            recon_factor = s_total / sum_buckets               # match filings magnitude
            reconcile = {"sourced_indicated": round(s_ind), "sourced_inferred": round(s_inf),
                         "sourced_total": round(s_total), "config_bucket_total": round(sum_buckets),
                         "reconcile_factor": round(recon_factor, 4), "sourced_mi_pct": round(s_mi, 4),
                         "source": "research_cache (filings)"}

        v_mkt_total = 0.0
        tq_by_project = {}
        sum_raw_oz = sum_eff_oz = sum_quality_oz = mi_oz = 0.0
        for proj, oz in buckets.items():
            if reconcile is not None:
                oz = oz * reconcile["reconcile_factor"]        # sourced magnitude
                mi = reconcile["sourced_mi_pct"]               # sourced sitewide confidence (no per-proj guess)
            else:
                mi = target_mi.get(proj, 0.50)
            eff_oz = oz * (mi * 1.0 + (1.0 - mi) * 0.5)        # symmetric inferred haircut (confidence)
            tqd = self.calculate_technical_quality(proj)
            quality_oz = eff_oz * tqd["tq"]
            tq_by_project[proj] = tqd
            v_mkt_total += quality_oz * peer_ev_oz * capital_discount_factor
            sum_raw_oz += oz; sum_eff_oz += eff_oz; sum_quality_oz += quality_oz; mi_oz += oz * mi
        v_mkt_defined = (v_mkt_total * conservatism) / shares if shares > 0 else 0.0

        # --- EXPLORATION SUB-LEG: future undiscovered ounces. Deliberately discounted HARDER than
        # defined ounces because pure-exploration upside is far more speculative: it is risked by
        # P(discovery) AND a margin-of-safety recognition fraction (`weight`, shared with the legacy /
        # archetype paths). The capital discount is now applied here too, UNIFORM with the defined-
        # ounce leg (it was previously omitted). No re-rating multiplier is applied. (Earlier comments
        # claimed "risked ONCE" — corrected: this is an explicit conservative multi-factor haircut.)
        exp = cfg.get("exploration_upside", {})
        p_disc = p_discovery if p_discovery is not None else exp.get("probability_of_discovery", 0.25)
        avg_tq = (sum_quality_oz / sum_eff_oz) if sum_eff_oz > 0 else 1.0
        tq_expl = min(1.0, avg_tq)                              # undiscovered ounces earn no quality premium
        v_expl = (exp.get("expected_future_oz", 0) * p_disc * peer_ev_oz * tq_expl
                  * exp.get("weight", 0.12) * capital_discount_factor * conservatism) / shares if shares > 0 else 0.0

        # --- OPTION LEG: convexity NOT in comps, multiplies the market base ---
        opt = self.calculate_option_premium(spot_ag, dynamic_aisc, silver_vol, real_yield, stage="explorer")
        l_market = (v_mkt_defined + v_expl) * (1.0 + opt["pi_opt"]) * forensic_penalty

        # --- COST LEG (REP floor) and INCOME LEG (none for a pure explorer) ---
        # Pass the reconciled effective ounces so the floor values the SAME resource base as the
        # market leg (filings magnitude + sourced M&I split) instead of the optimistic config buckets.
        l_cost = self.calculate_rep_floor(shares, effective_oz=sum_eff_oz)
        l_income = 0.0

        # --- CONFIDENCE-TILTED TRIANGULATION ---
        avg_mi = (mi_oz / sum_raw_oz) if sum_raw_oz > 0 else 0.5
        c_cost = cc.get("cost", 0.90)
        c_market = cc.get("market_base", 0.85) * (0.6 + 0.4 * avg_mi)   # Inferred-heavy -> less confident
        c_income = cc.get("income_explorer", 0.20)
        legs = {"cost": l_cost, "market": l_market, "income": l_income}
        confs = {"cost": c_cost, "market": c_market, "income": c_income}
        raw_w = {k: sw.get(k, 0.0) * confs[k] for k in legs}
        wsum = sum(raw_w.values())
        weights = {k: (raw_w[k] / wsum if wsum > 0 else 0.0) for k in legs}
        v_intrinsic = sum(weights[k] * legs[k] for k in legs)

        # --- MARGIN-OF-SAFETY LEDGER (multiplicative factors on the market leg, gross -> net) ---
        # Now includes the option premium (a >1 LIFT) so the chain actually reproduces the market leg
        # gross->net; the ADDITIVE exploration sub-leg is reported separately (v_exploration), not as a
        # multiplicative row. forensic_penalty stays last (the final net haircut). The cumulative is
        # compounded on the UNROUNDED factors (rounded only for display) so it never drifts from the
        # true value the way compounding pre-rounded factors did.
        ledger_factors = [
            ("inferred_haircut", (sum_eff_oz / sum_raw_oz) if sum_raw_oz > 0 else 1.0),
            ("technical_quality", (sum_quality_oz / sum_eff_oz) if sum_eff_oz > 0 else 1.0),
            ("capital_discount", capital_discount_factor),
            ("conservatism", conservatism),
            ("option_premium", 1.0 + opt["pi_opt"]),
            ("forensic_penalty", forensic_penalty),
        ]
        mos_ledger = []
        cum = 1.0
        for name, factor in ledger_factors:
            cum *= factor
            mos_ledger.append({"name": name, "factor": round(factor, 3), "cumulative": round(cum, 3)})

        return {
            "v_intrinsic": v_intrinsic,
            "stage": "explorer",
            "legs": {"cost": round(l_cost, 4), "market": round(l_market, 4), "income": round(l_income, 4)},
            "weights": {k: round(v, 3) for k, v in weights.items()},
            "confidence": {k: round(v, 3) for k, v in confs.items()},
            "v_mkt_defined": round(v_mkt_defined, 4),
            "v_exploration": round(v_expl, 4),
            "tq_by_project": tq_by_project,
            "avg_tq": round(avg_tq, 3),
            "option_premium": opt,
            "mos_ledger": mos_ledger,
            "effective_oz_total": round(sum_eff_oz, 0),
            "quality_oz_total": round(sum_quality_oz, 0),
            "resource_source": "research_cache (filings, reconciled)" if reconcile else "config buckets",
            "rep_floor_basis": "research_cache (filings, reconciled)" if reconcile else "config buckets",
            "resource_reconciliation": reconcile,            # None when unsourced/disabled
        }

    @staticmethod
    def peer_ev_margin_scaled(peer0, spot0, spot1, aisc):
        """Convex propagation of peer EV/oz under a silver move: peers re-rate with the operating
        MARGIN (spot − AISC), not 1:1 with spot. SINGLE source shared by the scenario tornado and the
        What-If, so the dashboard band and the cockpit What-If agree for an identical move (they used
        to disagree — linear beta=1 vs this convex ratio). Floored so the margin can't collapse to ~0
        or go negative on a deep drawdown."""
        try:
            a = float(aisc or 0.0)
        except (TypeError, ValueError):
            a = 0.0
        flo = max(1.0, 0.10 * a)
        m0 = max(flo, float(spot0) - a)
        m1 = max(flo, float(spot1) - a)
        return peer0 * (m1 / m0) if m0 > 0 else peer0

    def run_intrinsic_scenarios(self, base_kwargs, silver_vol):
        """Base/bull/bear triangulation range + one-at-a-time tornado over the dominant swing inputs.
        Silver moves are propagated into peer EV/oz via the CONVEX operating-margin model (the same
        peer_ev_margin_scaled the What-If uses, so the two surfaces agree); the peer-multiple lever is
        an INDEPENDENT sector re-rating on top, so the tornado separates 'silver moved' from 'the
        sector multiple moved'."""
        cfg = self.get_config()
        sc = cfg.get("scenarios", {})
        sv = silver_vol if (silver_vol and silver_vol > 0) else 0.30
        spot_move = sc.get("spot_sigma_mult", 1.0) * sv
        ry_shift = sc.get("real_yield_shift_bps", 50) / 100.0     # bps -> percentage points (yields in %)
        pd_shift = sc.get("p_discovery_shift", 0.10)
        peer_pct = sc.get("peer_ev_pct", 0.35)

        base_peer = base_kwargs["peer_ev_oz"]; base_spot = base_kwargs["spot_ag"]
        base_ry = base_kwargs["real_yield"]
        aisc = base_kwargs.get("dynamic_aisc", 0.0)
        base_pd = base_kwargs.get("p_discovery")
        if base_pd is None:
            base_pd = cfg.get("exploration_upside", {}).get("probability_of_discovery", 0.25)

        spot_up = base_spot * (1 + spot_move)
        spot_dn = base_spot * max(0.0, 1 - spot_move)
        # Convex peer EV/oz at the up/down silver spots (peers re-rate with the operating margin).
        peer_up = self.peer_ev_margin_scaled(base_peer, base_spot, spot_up, aisc)
        peer_dn = self.peer_ev_margin_scaled(base_peer, base_spot, spot_dn, aisc)

        def run(peer_ev, spot, ry, pdisc):
            kw = dict(base_kwargs)
            kw.update(peer_ev_oz=max(0.0, peer_ev), spot_ag=max(0.0, spot), real_yield=ry, p_discovery=pdisc)
            return self.calculate_spear_intrinsic(**kw)["v_intrinsic"]

        base_v = run(base_peer, base_spot, base_ry, base_pd)
        bull = run(peer_up * (1 + peer_pct), spot_up,
                   base_ry - ry_shift, min(0.95, base_pd + pd_shift))
        bear = run(peer_dn * (1 - peer_pct), spot_dn,
                   base_ry + ry_shift, max(0.0, base_pd - pd_shift))

        def lever(label, lo, hi):
            return {"input": label, "low": round(min(lo, hi), 3), "high": round(max(lo, hi), 3)}
        tornado = [
            lever("Silver spot",
                  run(peer_dn, spot_dn, base_ry, base_pd),
                  run(peer_up, spot_up, base_ry, base_pd)),
            lever("Peer EV/oz multiple",
                  run(base_peer * (1 - peer_pct), base_spot, base_ry, base_pd),
                  run(base_peer * (1 + peer_pct), base_spot, base_ry, base_pd)),
            lever("Real yield",
                  run(base_peer, base_spot, base_ry + ry_shift, base_pd),
                  run(base_peer, base_spot, base_ry - ry_shift, base_pd)),
            lever("Discovery prob",
                  run(base_peer, base_spot, base_ry, max(0.0, base_pd - pd_shift)),
                  run(base_peer, base_spot, base_ry, min(0.95, base_pd + pd_shift))),
        ]
        rng = {"bear": round(bear, 3), "base": round(base_v, 3), "bull": round(bull, 3), "tornado": tornado}
        rng["implied_upside_pct"] = None    # filled by the orchestrator once price is known
        return rng


class HealthRadarEngine:
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
        # When the orchestrator wires a config provider (CommodityExMonitor), serve the per-cycle
        # EFFECTIVE config (v5_config.json defaults + confirmed SQLite overrides) instead of a raw
        # file read. This is what makes a /confirm'd override actually reach live valuation, the JSF
        # gate, and the directives (previously every engine re-read the raw file and silently bypassed
        # the overlay), and it collapses ~dozens of redundant disk reads per cycle into one. Engines
        # constructed standalone (e.g. unit tests) have no provider -> identical legacy file read.
        provider = getattr(self, "_config_provider", None)
        if provider is not None:
            return provider()
        with open(self.config_path, "r") as f:
            return json.load(f)

    def calculate_health_rating(self, jsf_score, mri_score, expected_shortfall_95, is_stale):
        cfg = self.get_config()
        radar_cfg = cfg.get("health_radar", {})
        
        forensics_mult = radar_cfg.get("forensics_multiplier", 1.25)
        macro_mult = radar_cfg.get("macro_multiplier", 1.5)
        stale_penalty = radar_cfg.get("stale_penalty", 2.0)
        es_cfg = radar_cfg.get("es_penalty", {
            "free_pct": -5.0, "ref_pct": -10.0, "ref_penalty": 1.0, "exponent": 1.5
        })

        score = 10.0
        
        # 1. Forensics penalty
        score -= (4.0 - jsf_score) * forensics_mult
        
        # 2. Macro penalty
        score -= (mri_score / 100.0) * macro_mult
        
        # 3. Pipeline cache penalty
        if is_stale:
            score -= stale_penalty
            
        # 4. Tail Risk expected shortfall penalty (continuous, convex, uncapped)
        # Penalty grows as a power of how far the daily 95% ES falls below the no-penalty band,
        # anchored so the documented reference point (ES = ref_pct -> ref_penalty) is preserved.
        # gamma > 1 makes deep tails hurt disproportionately more (no flat -1.0 saturation cap).
        free_mag = -es_cfg.get("free_pct", -5.0)
        ref_mag = -es_cfg.get("ref_pct", -10.0)
        gamma = es_cfg.get("exponent", 1.5)
        excess = max(0.0, (-expected_shortfall_95) - free_mag)
        ref_excess = max(1e-9, ref_mag - free_mag)
        k = es_cfg.get("ref_penalty", 1.0) / (ref_excess ** gamma)
        es_penalty = k * (excess ** gamma)

        score -= es_penalty
        
        score = round(max(1.0, min(10.0, score)), 1)
        
        if score >= 8.5:
            rating_desc = "HIGH INTEGRITY - STRONGLY ACTIONABLE"
            rating_color = "green"
            health_summary = "Data pipelines are fresh, macro stress is low, and forensic shields are active. Signals are highly reliable for portfolio sizing."
        elif score >= 6.0:
            rating_desc = "MODERATE QUALITY - EXERCISE GUARDRAILS"
            rating_color = "orange"
            health_summary = "Mild accounting or dilution drags present, or rising macro stress. Maintain strict adherence to Kelly allocation caps."
        else:
            rating_desc = "HIGH NOISE - EXTREME CAUTION"
            rating_color = "red"
            health_summary = "Severe forensic failures, extreme macro regime volatility, or stale network fallback active. Treat model values as high-uncertainty limits."
            
        return {
            "health_rating": score,
            "rating_desc": rating_desc,
            "rating_color": rating_color,
            "health_summary": health_summary
        }

    def generate_priorities(self, val_data, jsf_score, mri_score, expected_shortfall_95, p_aga):
        implied_edge = val_data.get("Implied_Upside", 0.0)
        rep_floor = val_data.get("REP_Floor", 0.0)
        kelly = val_data.get("Kelly_Multiple", 1.0)          # risk-adjusted target leverage f* (<= L_max)
        # Over/under-allocation vs the Kelly-optimal target (bounded, correctly-oriented). Falls back to
        # 1.0 (at-target) when absent so legacy/partial state payloads do not false-trigger a trim.
        alloc_ratio = val_data.get("allocation_ratio", 1.0)
        caution_ratio = self.get_config().get("v5_guardrails", {}).get("allocation_directive", {}).get("caution_ratio", 1.5)
        adv_cap = val_data.get("ADV_Cap_CAD", 0.0)
        adv_cap_pct = val_data.get("ADV_Cap_Percentage", 15.0)
        # Fail CONSERVATIVE if the intrinsic is missing: a stale non-zero default (was 4.18) would
        # scream "EXPLOIT SPEAR ARBITRAGE" at phantom upside. 0.0 -> negative spear upside -> no signal.
        aga_intrinsic = val_data.get("AGA_Intrinsic", 0.0)
        
        priorities = []

        # Priority 1: Valuation / Spear Arbitrage — gate on the spear's OWN intrinsic-vs-price upside
        # (recalibrated for the de-inflated valuation), not the structurally-lower blended portfolio edge.
        spear_upside = (aga_intrinsic / p_aga - 1.0) * 100 if p_aga > 0 else 0.0
        spear_arb_thresh = self.get_config().get("directive_thresholds", {}).get("spear_arbitrage_pct", 50.0)
        if spear_upside > spear_arb_thresh:
            priorities.append({
                "icon": "shopping_cart_outlined",
                "color": "green",
                "title": "EXPLOIT SPEAR ARBITRAGE",
                "desc": f"AGA.V market price (${p_aga:.2f}) is trading at a discount to triangulated Intrinsic (${aga_intrinsic:.2f}) with {spear_upside:.0f}% upside (blended portfolio edge {implied_edge:.0f}%)."
            })
        else:
            priorities.append({
                "icon": "info_outline",
                "color": "white",
                "title": "MONITOR VALUATION ALIGNMENT",
                "desc": "Barbell components are trading closer to model fair values. No aggressive accumulation signaled. Maintain baseline holdings."
            })
            
        # Priority 2: Forensics / Accruals / Dilution
        # Aligned with directive threshold: JSF < 3.5 triggers warning (not 3.0)
        if jsf_score < 3.5:
            priorities.append({
                "icon": "warning_amber_rounded",
                "color": "red" if jsf_score < 3.0 else "orange",
                "title": "MITIGATE JUNIOR ACCOUNTING STRESS",
                "desc": f"JSF Score is degraded at {jsf_score:.1f}/4.0 due to CBA burn acceleration or share dilution expansion. Enforce strict allocation caps to avoid structural traps."
            })
        else:
            priorities.append({
                "icon": "verified_user_outlined",
                "color": "green",
                "title": "RISK SHIELD IS SECURE",
                "desc": f"Forensic risk checks are clean (JSF: {jsf_score:.1f}/4.0). Dilution drag and cash burn are well-contained. High safety factor for capital deployment."
            })
            
        # Priority 3: Sizing / Macro Sizing Caps
        if mri_score > 65:
            priorities.append({
                "icon": "lock_clock",
                "color": "red",
                "title": "ENFORCE SEVERE EXIT SIZING CAPS",
                "desc": f"Sovereign stress (MRI: {mri_score:.1f}) is highly elevated. Sizing cap restricted to {adv_cap_pct:.1f}% ADV (${adv_cap:.0f}). Restrict trading block execution to avoid market impact."
            })
        else:
            priorities.append({
                "icon": "swap_horizontal_circle_outlined",
                "color": "green",
                "title": "EXECUTE BLOCK TRADES CONFIDENTLY",
                "desc": f"Macro regime is calm (MRI: {mri_score:.1f}). Exit liquidity cap expanded to {adv_cap_pct:.1f}% ADV (${adv_cap:.0f}). Large additions can be run safely without blocking frames or moving the tape."
            })
            
        # Priority 4: Portfolio Capital Rebalancing
        if alloc_ratio > caution_ratio:
            priorities.append({
                "icon": "balance_outlined",
                "color": "orange",
                "title": "TRIM OVERALLOCATION DRAG",
                "desc": f"Book is holding {alloc_ratio:.2f}x the risk-adjusted Kelly target (f*={kelly:.2f}x of capital). Trim barbell assets back toward the target to reclaim risk budget."
            })
        else:
            priorities.append({
                "icon": "check_circle_outline",
                "color": "green",
                "title": "ALLOCATIONS WITHIN RISK BOUNDS",
                "desc": f"Deployment is within the Kelly band ({alloc_ratio:.2f}x target, f*={kelly:.2f}x of capital). No urgent trim directives active."
            })
            
        return priorities


class PortfolioSizer:
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
        # When the orchestrator wires a config provider (CommodityExMonitor), serve the per-cycle
        # EFFECTIVE config (v5_config.json defaults + confirmed SQLite overrides) instead of a raw
        # file read. This is what makes a /confirm'd override actually reach live valuation, the JSF
        # gate, and the directives (previously every engine re-read the raw file and silently bypassed
        # the overlay), and it collapses ~dozens of redundant disk reads per cycle into one. Engines
        # constructed standalone (e.g. unit tests) have no provider -> identical legacy file read.
        provider = getattr(self, "_config_provider", None)
        if provider is not None:
            return provider()
        with open(self.config_path, "r") as f:
            return json.load(f)

    async def fetch_historical_returns(self, tickers, lookback_days=60):
        def _fetch():
            data = {}
            for t in tickers:
                try:
                    hist = yf.Ticker(t).history(period=f"{lookback_days + 10}d")
                    if not hist.empty:
                        data[t] = hist['Close'].pct_change().dropna().tail(lookback_days)
                except Exception as e:
                    print(f"[!] Return fetch error for {t}: {e}")
            
            if not data:
                return None, {}, {}

            df = pd.DataFrame(data)
            corr_matrix = self.shrink_correlation(df)  # shrunk toward constant-correlation target
            volatilities = df.std().to_dict()
            
            annualized_vols = {k: float(v * np.sqrt(252)) for k, v in volatilities.items()}
            return df, corr_matrix, annualized_vols

        res = await asyncio.to_thread(_fetch)
        return res

    def calculate_expected_shortfall(self, df_returns, weights, confidence_level=0.95):
        try:
            df_aligned = df_returns.dropna()
            if df_aligned.empty:
                return 0.0
            
            portfolio_returns = df_aligned.dot(weights)
            cutoff = np.percentile(portfolio_returns, (1 - confidence_level) * 100)
            tail_losses = portfolio_returns[portfolio_returns <= cutoff]
            
            if len(tail_losses) == 0:
                return 0.0
                
            es = tail_losses.mean()
            return float(es)
        except Exception as e:
            print(f"[!] Expected Shortfall error: {e}")
            return 0.0

    def shrink_correlation(self, returns_df, intensity=None):
        """Ledoit-Wolf-style shrinkage of a noisy sample correlation toward a constant-correlation
        target (lean, dependency-free variant): C* = (1-d)*C_sample + d*C_target, where C_target has
        every off-diagonal equal to the AVERAGE sample pairwise correlation. With only ~60 daily
        microcap observations the individual pairwise correlations are dominated by estimation noise;
        shrinking toward the common level stabilizes the barbell correlation penalty and the ES
        covariance. Returns a {ticker: {ticker: corr}} dict (same shape as df.corr().to_dict())."""
        try:
            corr = returns_df.corr()
            cols = list(corr.columns)
            n = len(cols)
            if n < 2:
                return corr.to_dict()
            if intensity is None:
                intensity = self.get_config().get("v5_guardrails", {}).get("covariance_shrinkage_intensity", 0.30)
            d = min(1.0, max(0.0, float(intensity)))
            C = corr.values.astype(float)
            iu = np.triu_indices(n, k=1)
            rbar = float(np.nanmean(C[iu])) if C[iu].size else 0.0
            T = np.full((n, n), rbar)
            np.fill_diagonal(T, 1.0)
            S = (1.0 - d) * C + d * T
            np.fill_diagonal(S, 1.0)
            return {cols[i]: {cols[j]: float(S[i, j]) for j in range(n)} for i in range(n)}
        except Exception as e:
            print(f"[!] Correlation shrinkage error: {e}")
            return returns_df.corr().to_dict()

    def robust_expected_shortfall(self, df_returns, weights, confidence_level=0.95, blend=None):
        """ES95 blended from the empirical tail and a parametric Gaussian tail. At 95% on ~60 daily
        observations the empirical tail is only ~3 points and whipsaws leverage run-to-run; blending
        toward a parametric Gaussian ES (mu - sigma * phi(z)/(1-a)) damps that noise while still
        responding to realized losses. `blend` is the weight on the parametric leg (0..1)."""
        try:
            df_aligned = df_returns.dropna()
            if df_aligned.empty:
                return 0.0
            import statistics as _st
            pr = df_aligned.dot(weights)
            cutoff = np.percentile(pr, (1 - confidence_level) * 100)
            tail = pr[pr <= cutoff]
            es_emp = float(tail.mean()) if len(tail) else float(pr.min())
            mu, sigma = float(pr.mean()), float(pr.std())
            nd = _st.NormalDist()
            z = nd.inv_cdf(confidence_level)
            es_param = mu - sigma * (nd.pdf(z) / (1.0 - confidence_level))
            if blend is None:
                blend = self.get_config().get("v5_guardrails", {}).get("es_parametric_blend", 0.5)
            w = min(1.0, max(0.0, float(blend)))
            return (1.0 - w) * es_emp + w * es_param
        except Exception as e:
            print(f"[!] Robust ES error: {e}")
            return self.calculate_expected_shortfall(df_returns, weights, confidence_level)

    async def get_liquidity_cap(self, ticker, fallback_volume=150000):
        guard = self.get_config().get("v5_guardrails", {})
        window = int(guard.get("adv_window_days", 90))
        method = guard.get("adv_method", "median")
        halflife = int(guard.get("adv_ewma_halflife_days", 30))

        def _fetch():
            try:
                t = yf.Ticker(ticker)
                # Phase 0 patch: a 90-session MEDIAN of daily volume cannot be inflated by a panic
                # spike the way a 10-day ADV is. Prefer it; fall back to the 3-month / 10-day info
                # fields (3-month before 10-day, as it is the less spike-sensitive of the two).
                hist = t.history(period=f"{window + 40}d")
                robust = _robust_adv_shares(hist, window, method, halflife)
                if robust and robust > 0:
                    return int(robust)
                info = t.info
                adv_shares = info.get('averageVolume') or info.get('averageVolume10Day') or fallback_volume
                return int(adv_shares)
            except Exception:
                return int(fallback_volume)
        return await asyncio.to_thread(_fetch)
    @staticmethod
    def catalyst_confidence(momentum, floor=0.5, mom_lo=-0.10, mom_hi=0.10):
        """Catalyst/momentum confidence in [floor, 1.0] used to haircut the Kelly drift (mu).

        Kelly mu is derived from total intrinsic Implied Upside converted over an assumed
        convergence window (~18mo). But markets can stay irrational longer than that window, so
        sizing the FULL convergence thesis purely on valuation invites value-trap exposure. This
        gate scales mu by how strongly the spear's own price action is CONFIRMING the catalyst:

            momentum <= mom_lo -> floor (no recognition / falling knife -> haircut the thesis)
            momentum >= mom_hi -> 1.0   (catalyst engaging -> full thesis)

        with a linear ramp in between. `momentum` is the spear's trailing cumulative return.
        Returns 1.0 (no haircut) when momentum is unavailable, preserving prior behavior on
        degraded data feeds."""
        if momentum is None or mom_hi <= mom_lo:
            return 1.0
        floor = min(1.0, max(0.0, floor))
        ramp = min(1.0, max(0.0, (momentum - mom_lo) / (mom_hi - mom_lo)))
        return floor + (1.0 - floor) * ramp

    def calculate_sizing(self, live_portfolio_value, u_implied, volatilities, corr_matrix, mri_score, limit_params, catalyst_factor=1.0):
        cfg = self.get_config()
        guard = cfg.get("v5_guardrails", {})
        
        # Load risk parameters from config
        fractional_kelly = guard.get("fractional_kelly_multiplier", 0.5)
        pos_liq_cap = guard.get("position_liquidity_cap_pct", 0.15)
        max_single_pos = guard.get("max_single_position_pct", 0.20)
        # STRUCTURAL INVARIANT — the 60% spear ceiling is permanent and NOT a tunable: config can
        # only ever TIGHTEN it (min), never raise it. A hand-edited v5_config.json (or a bad merge)
        # must not be able to loosen the book's one hard margin-of-safety constraint. It is also
        # deliberately absent from the dynamic-config ALLOWLIST. Do not "fix" this by making it
        # configurable. (NB: PHASE7_CONVICTION_MODE.md row 1 proposing its removal is SUPERSEDED.)
        SPEAR_CEILING_STRUCTURAL = 0.60
        try:
            max_spear_pos = min(float(guard.get("max_spear_position_pct", SPEAR_CEILING_STRUCTURAL)
                                      or SPEAR_CEILING_STRUCTURAL), SPEAR_CEILING_STRUCTURAL)
        except (TypeError, ValueError):
            max_spear_pos = SPEAR_CEILING_STRUCTURAL
        
        # Determine macro regime scaling multiplier
        if mri_score < 40:
            multiplier, macro_regime = 1.00, "Expansion / Risk-On"
        elif mri_score < 65:
            multiplier, macro_regime = 0.85, "Moderate Risk / Neutral"
        elif mri_score < 80:
            multiplier, macro_regime = 0.55, "Elevated Risk / Caution"
        else:
            multiplier, macro_regime = 0.25, "High Stress / Defensive"

        # 1. Multi-Asset Barbell Correlation Penalty
        groy_corr = corr_matrix.get("AGA.V", {}).get("GROY", 0.50)
        urc_corr = corr_matrix.get("AGA.V", {}).get("URC.TO", 0.50)
        gmx_corr = corr_matrix.get("AGA.V", {}).get("GMX.TO", 0.50)
        
        avg_ballast_corr = (groy_corr + urc_corr + gmx_corr) / 3.0
        correlation_penalty = 1.0 - max(0.0, avg_ballast_corr - 0.30) * 0.40

        # 2. Portfolio-Level Kelly Allocation
        # Dimensional coherence: u_implied is a TOTAL convergence-to-intrinsic return, whereas
        # port_variance is ANNUALIZED (returns std * sqrt(252)). Continuous Kelly f* = mu / sigma^2
        # requires mu and sigma^2 on the SAME horizon, so the total upside is first converted into
        # an expected ANNUALIZED drift over the assumed intrinsic convergence window.
        convergence_months = guard.get("intrinsic_convergence_months", 18.0)
        convergence_years = max(0.25, convergence_months / 12.0)
        catalyst_factor = min(1.0, max(0.0, catalyst_factor))
        port_vol = limit_params.get("port_vol", 0.40)
        port_variance = max(0.04, port_vol ** 2)

        # Pure convergence-thesis drift (point estimate), before any confidence haircuts.
        mu_raw = u_implied / convergence_years

        # Parameter-uncertainty haircut (uncertainty-adjusted Kelly): the implied edge is a single
        # point estimate and Kelly is hypersensitive to it. SE of an annualized drift estimated over
        # the convergence horizon T with annualized vol sigma is ~ sigma/sqrt(T); the edge confidence
        # kappa = mu^2 / (mu^2 + SE^2) -> 1 when the edge dwarfs the noise, -> 0 when it is fragile.
        # This is independent of (and composed multiplicatively with) the catalyst/momentum gate.
        unc_cfg = guard.get("edge_uncertainty", {})
        se_mu = unc_cfg.get("noise_vol_multiplier", 1.0) * port_vol / (convergence_years ** 0.5)
        denom = (mu_raw ** 2) + (se_mu ** 2)
        edge_confidence = (mu_raw ** 2) / denom if denom > 0 else 1.0
        edge_confidence = max(unc_cfg.get("min_confidence", 0.0), min(1.0, edge_confidence))

        # Catalyst/momentum overlay: haircut the drift until the spear's price action confirms the
        # thesis (catalyst_factor in [0,1]; 1.0 = full thesis). Both gates apply to the same drift.
        mu_annualized = mu_raw * catalyst_factor * edge_confidence
        raw_portfolio_kelly = (mu_annualized / port_variance) * fractional_kelly

        # Max aggregate leverage allowed (VIX-dampened)
        max_leverage_allowed = 1.5
        vix = limit_params.get("vix", 16.5)
        if vix > 15.0:
            max_leverage_allowed = max(0.60, 1.5 - ((vix - 15.0) * 0.045))

        # Tail-risk (ES95) throttle: scale aggregate leverage down as the 95% Expected Shortfall
        # deteriorates, fulfilling the documented ES95 -> PortfolioSizer relationship. es is a
        # DAILY mean tail loss expressed in percent (negative = loss), same scale as the Health Radar.
        es_cfg = guard.get("es_throttle", {"no_penalty_pct": -5.0, "max_penalty_pct": -12.0, "max_reduction": 0.5})
        es_pct = limit_params.get("expected_shortfall_95_pct", 0.0)
        no_pen = es_cfg.get("no_penalty_pct", -5.0)
        max_pen = es_cfg.get("max_penalty_pct", -12.0)
        max_red = es_cfg.get("max_reduction", 0.5)
        if es_pct < no_pen and no_pen > max_pen:
            severity = min(1.0, (no_pen - es_pct) / (no_pen - max_pen))
            es_throttle = 1.0 - max_red * severity
        else:
            es_throttle = 1.0

        target_portfolio_leverage = min(raw_portfolio_kelly, max_leverage_allowed) * correlation_penalty * es_throttle
        
        # Target capital before active ceilings
        e_target_raw = live_portfolio_value * target_portfolio_leverage
        e_target_capped = max(0.0, e_target_raw * multiplier)
        
        # 3. Position-Level Liquidity and Sizing Caps
        aga_price = limit_params.get("aga_price", 0.72)
        aga_adv = limit_params.get("aga_adv", 150000)
        jsf_score = limit_params.get("jsf_score", 4.0)
        
        # Implement dynamic, opportunistic flexibility:
        # If macro (MRI < 45) and micro (JSF >= 3.5) align, expand caps by 25% to allow for potential over-allocation
        is_aligned = (mri_score < 45.0) and (jsf_score >= 3.5)
        flexibility_mult = 1.25 if is_aligned else 1.0
        
        # Dynamic Liquidity Cap: Scales down from pos_liq_cap as macro stress approaches 100
        cap_percentage = max(0.02, pos_liq_cap * (1.0 - (mri_score / 100.0))) * flexibility_mult
        adv_cap_cad = aga_adv * cap_percentage * aga_price
        
        # ====================== ACTIVE CEILING APPLICATION ======================
        # Asset Weights inside the Barbell Portfolio — single validated source shared with the comps
        # worker and evaluate_master_architecture (no more divergent 60/15/15/10 literals).
        weights = _resolve_barbell_weights(cfg)
        
        # A. CONSTRAINT 1: Single Position Percentage Cap (max_single_position_pct)
        max_by_single_pos_cap = float('inf')
        for ticker, w in weights.items():
            limit_pct = max_spear_pos if ticker == "AGA.V" else max_single_pos
            # Opportunistic flexibility may expand sizing TOWARD a structural ceiling but never
            # THROUGH it. The 60/40 barbell is a hard margin-of-safety constraint, so the spear
            # (and every single position) is clamped to its base guardrail regardless of flex.
            # Flexibility therefore only loosens the liquidity/ADV cap above, not the position caps.
            limit_flex = min(limit_pct * flexibility_mult, limit_pct)
            cap_for_ticker = (live_portfolio_value * limit_flex) / w
            if cap_for_ticker < max_by_single_pos_cap:
                max_by_single_pos_cap = cap_for_ticker
                
        # B. CONSTRAINT 2: Position Liquidity Cap on the Spear (AGA.V)
        max_by_liquidity_cap = adv_cap_cad / weights["AGA.V"]
        
        # C. COMPUTE CONSTRAINED TARGET PORTFOLIO CAPITAL (Proportional Scaling Approach)
        e_target_final = min(e_target_capped, max_by_single_pos_cap, max_by_liquidity_cap)
        
        # Log active guardrail triggers for terminal UI
        active_ceiling_triggered = "None"
        if e_target_final < e_target_capped:
            if e_target_final == max_by_liquidity_cap:
                active_ceiling_triggered = "Liquidity"
            else:
                active_ceiling_triggered = "Sizing"
                
        # ---- Reported sizing metrics ----
        # The prior `kelly_multiple = live_portfolio_value / e_target_final` was the RECIPROCAL of the
        # deployed Kelly fraction (1/f*): unbounded, and inverted so that a MORE conservative target
        # produced a LARGER "multiple". Labeled "KELLY MULT" in the cockpit it read as a phantom
        # ~11.6x leverage on what is actually an ~8.6% deployment, and it perpetually tripped the
        # over-allocation/trim directives. It is split into two correctly-oriented, bounded metrics:
        #
        # (a) kelly_multiple := the risk-adjusted target leverage f* itself — the fraction/multiple of
        #     capital the model wants deployed AFTER every gate and the hard 60/40 barbell ceiling. It
        #     is natively bounded to [0, L_max(VIX)] (min() vs max_leverage_allowed above) and reads as
        #     a true institutional sizing constraint ("deploy f*x of capital").
        kelly_multiple = (e_target_final / live_portfolio_value) if live_portfolio_value > 0 else 0.0
        #
        # (b) allocation_ratio := how the (fully deployed) book compares to that Kelly target. >1 means
        #     holding more than the risk budget (trim toward target); <1 means room to add. Being the
        #     reciprocal of f* it is CLAMPED to a display cap so an illiquid/low-edge (tiny) target
        #     cannot send it to infinity, and a relative epsilon replaces the old hard $100 cliff
        #     (which discontinuously snapped the metric to 1.0).
        alloc_cfg = guard.get("allocation_directive", {})
        alloc_cap = alloc_cfg.get("display_cap", 5.0)
        eps_target = max(1.0, live_portfolio_value * 1e-3)
        allocation_ratio = min(alloc_cap, live_portfolio_value / max(eps_target, e_target_final))
        
        # Intermediate leverage states for the educational waterfall
        vix_capped_leverage = min(raw_portfolio_kelly, max_leverage_allowed)
        post_correlation_leverage = vix_capped_leverage * correlation_penalty
        post_es_leverage = post_correlation_leverage * es_throttle  # == target_portfolio_leverage
        post_regime_leverage = post_es_leverage * multiplier

        # Structured waterfall: each stage carries the surviving leverage, the multiplicative factor
        # applied, and whether it is the binding constraint — so the cockpit can render proportional
        # bars and call out exactly which gate is throttling deployment.
        waterfall = [
            {"stage": "raw_kelly", "label": "Uncertainty-adj. Kelly", "leverage": round(raw_portfolio_kelly, 4), "factor": None, "binding": False},
            {"stage": "vix_cap", "label": f"VIX cap @ {vix:.1f}", "leverage": round(vix_capped_leverage, 4),
             "factor": round(vix_capped_leverage / raw_portfolio_kelly, 3) if raw_portfolio_kelly > 0 else 1.0,
             "binding": raw_portfolio_kelly > max_leverage_allowed},
            {"stage": "correlation", "label": "Correlation penalty", "leverage": round(post_correlation_leverage, 4),
             "factor": round(correlation_penalty, 3), "binding": correlation_penalty < 0.999},
            {"stage": "es_throttle", "label": "ES95 throttle", "leverage": round(post_es_leverage, 4),
             "factor": round(es_throttle, 3), "binding": es_throttle < 0.999},
            {"stage": "regime", "label": f"Regime {macro_regime.split(' ')[0]}", "leverage": round(post_regime_leverage, 4),
             "factor": round(multiplier, 3), "binding": multiplier < 0.999},
        ]

        return {
            "e_target": round(e_target_final, 2),
            "kelly_multiple": round(kelly_multiple, 4),       # == risk-adjusted target leverage f* (bounded [0, L_max])
            "kelly_leverage": round(kelly_multiple, 4),       # explicit canonical alias for the UI to migrate to
            "allocation_ratio": round(allocation_ratio, 2),   # current book vs Kelly target (>1 => trim); clamped
            "macro_regime": macro_regime,
            "target_pct": round((e_target_final / live_portfolio_value) * 100 if live_portfolio_value > 0 else 0.0, 2),
            "adv_cap_cad": round(adv_cap_cad, 2),
            "avg_ballast_corr": round(avg_ballast_corr, 2),
            "correlation_penalty": round(correlation_penalty, 3),
            "cap_percentage": round(cap_percentage * 100, 2),
            "active_ceiling_triggered": active_ceiling_triggered,
            "es_throttle": round(es_throttle, 3),
            "max_single_position_value_cap": round(live_portfolio_value * max_spear_pos, 2),
            # Educational waterfall intermediates (read-only, does not alter sizing math)
            "raw_kelly_leverage": round(raw_portfolio_kelly, 4),
            "vix_capped_leverage": round(vix_capped_leverage, 4),
            "post_correlation_leverage": round(post_correlation_leverage, 4),
            "post_es_leverage": round(post_es_leverage, 4),
            "regime_multiplier": round(multiplier, 2),
            "catalyst_factor": round(catalyst_factor, 3),
            # Parameter-uncertainty (uncertainty-adjusted Kelly) diagnostics
            "edge_confidence": round(edge_confidence, 3),
            "mu_raw": round(mu_raw, 4),
            "mu_annualized": round(mu_annualized, 4),
            "se_mu": round(se_mu, 4),
            "waterfall": waterfall
        }


# ========================================================
# MAIN COMMODITYEX MONITOR SYSTEM (v5)
# ========================================================

class CommodityExMonitor:
    def __init__(self):
        # NB: this monitor never connects to a broker. Market data comes from Yahoo
        # (market_data.py) + FMP (fmp_client.py) + the engine's own yfinance fetches; there is
        # no IBKR/IB-Gateway integration (the old host/port/client_id scaffolding was vestigial —
        # assigned and never read — and was removed). Positions/weights are config-sourced.
        self.config_path = "v5_config.json"
        
        # Instantiate v5 Core Engine Modules
        self.macro_engine = MacroRegimeEngine(self.config_path)
        self.peer_engine = PeerEngine(self.config_path)
        self.forensic_engine = ForensicEngine(self.config_path)
        self.valuation_engine = ValuationEngine(self.config_path)
        self.sizer = PortfolioSizer(self.config_path)
        self.radar = HealthRadarEngine(self.config_path)

        # Phase 5b (ADDITIVE): build the Polymorphic Archetype Factory router once at
        # construction. It routes each portfolio name by cash-flow lifecycle and produces a
        # supplementary, CAD-normalized triangulated valuation in PARALLEL with the legacy
        # path — it never replaces any existing valuation. Wrapped defensively so a config or
        # router problem can never block monitor startup; on failure the archetype block is
        # simply omitted from terminal_state. (Snapshot of config at init; the router picks up
        # live FX each cycle, see _compute_archetype_valuations.)
        self.config: dict = {}
        self.archetype_router = None
        try:
            self.config = load_config(self.config_path)
            self.archetype_router = build_default_router(self.config)
        except Exception as e:
            logging.warning("Phase 5b archetype router unavailable (non-fatal): %s", e)

        # Engine-owned UI-context broker (cockpit <-> Flutter merge). The engine holds the
        # instance + routes + terminal_state; the manager is a small orchestrated module.
        self.ui = UIStateManager()
        self._agent_seq = 0          # monotonic id for the ambient agent-activity bus
        self.fmp = FMPClient() if FMPClient else None   # on-demand only (never in the eval loop)

        # Dynamic config overlay (engine-owned): v5_config.json = defaults, SQLite = overrides,
        # merged into self.config and hot-reloaded each loop. Reduces hardcoding over time.
        try:
            self.dconfig = DynamicConfigManager(self.config)
            self.config = self.dconfig.effective()
        except Exception as e:
            self.dconfig = None
            logging.warning("dynamic config overlay unavailable (non-fatal): %s", e)

        # Route EVERY core engine's get_config() through the single effective-config provider so the
        # confirmed overlay (and live file edits) actually reach valuation / JSF / sizing / radar /
        # directives. Without this the engines re-read the raw file and the /confirm overlay was a
        # no-op on the live book (it only ever touched what-ifs / archetypes). One read per cycle.
        for _eng in (self.macro_engine, self.peer_engine, self.forensic_engine,
                     self.valuation_engine, self.sizer, self.radar):
            _eng._config_provider = self._effective_config

        self.last_macro_update = 0
        self.last_price_update = 0
        self.last_cftc_update = 0
        self.last_peer_update = 0
        
        self.cached_prices = {}
        self.cached_mean_peer_ev_oz = None
        self.macro_fail_count = 0
        
        self.shares = {}
        self.uroy_call_price = 0.60
        self.last_csv_mtime = 0

        # Thread safety lock for in-memory cache access
        self.state_lock = threading.Lock()
        
        # Thread-safe in-memory cache for decoupled background tasks
        self.state_cache = {
            # Cold-start defaults aligned to the PeerEngine fallbacks (~$2.5 CAD/oz, ~$0.48/oz disc cost)
            # so the first eval cycle before the peer worker populates live comps is realistic, not a
            # stale $65/oz placeholder that would flash an absurd intrinsic/directive on startup.
            "mean_peer_ev": 2.5,
            "peer_details": [],
            "avg_disc_cost": 0.48,
            
            "y10": 4.35,
            "y30": 4.65,
            "spr": 2.71,
            "ted": 0.05,
            "eff": 4.33,
            "vix": 16.5,
            "macro_status": "LIVE",
            
            "prices": {
                "CL=F": 89.5, "DX-Y.NYB": 99.0, "SI=F": 74.8,
                "AGA.V": 0.72, "GROY": 3.22, "GMX.TO": 2.04, "URC.TO": 4.82,
                "USDCAD=X": 1.38, "^VIX3M": 18.5
            },
            "prices_status": "LIVE",
            
            "dxy_mom": 0.0,
            "current_dxy": 99.0,
            "dxy_status": "LIVE",
            
            "usd_to_cad": 1.38,
            
            "real_yield": 1.0,
            "ry_status": "LIVE",
            
            "copper": 4.2,
            "gold": 2350.0,
            
            "m1_price": 74.8,
            "m180_price": 74.8,
            
            "cftc_net_longs": 35000.0,
            "cftc_status": "LIVE",

            # Per-feed point-in-time stamps (epoch secs) for the data-freshness layer; seeded at
            # construction so the cockpit doesn't false-alarm before the first worker cycle.
            "prices_ts": time.time(), "macro_ts": time.time(), "ry_ts": time.time(),
            "dxy_ts": time.time(), "cftc_ts": time.time(), "peers_ts": time.time(),

            "forensic_metrics": {
                "AGA.V": {
                    "sloan_cfo": 0.021, "sloan_bs": 0.024, "shares_t0": 208600000, "shares_t1": 208600000, "sga_t0": 450000,
                    "cfo_t0": None, "cfo_t1": None, "cash_t0": None
                },
                "GROY": {"sloan_cfo": 0.02, "sloan_bs": 0.02},
                "URC.TO": {"sloan_cfo": 0.02, "sloan_bs": 0.02},
                "GMX.TO": {"sloan_cfo": 0.02, "sloan_bs": 0.02}
            },
            
            "df_rets": None,
            "corr_matrix": {
                "AGA.V": {"GROY": 0.25, "URC.TO": 0.28, "GMX.TO": 0.30},
                "GROY": {"URC.TO": 0.40, "GMX.TO": 0.35},
                "URC.TO": {"GMX.TO": 0.45}
            },
            "vols": {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42},
            # ES95 convention (v5.1 fix): a SIGNED DECIMAL daily tail loss (negative = loss), the
            # same scale the comps worker writes (robust_expected_shortfall) and that the display/
            # plumbing converts to a signed percent via *100. The prior seed (5.2) was a positive
            # percent: *100 -> +520, which is neither < the -5% throttle floor nor below the Health
            # free band, so the entire tail-risk machinery sat INERT until the first comps cycle (~4h).
            # -0.052 == a coherent ~-5.2% cold-start so the throttle/Health penalty are live from t0.
            "es_95": -0.052,
            "port_vol": 0.40,
            "avg_corr": 0.45,

            "aga_adv": 150000,

            # Phase 0: trailing per-driver history feeding the MRI rolling-percentile bounds.
            # Empty until the macro worker seeds it; calculate_mri falls back to static norms meanwhile.
            "mri_history": {}
        }

        # A1.9 (atomic snapshot-swap): readers (/state, /ws, GET buses) are served _published_state
        # — a complete frame swapped in one reference assignment after each eval cycle / interactive
        # mutation — never the live working dict mid-write. None until the first publish (readers
        # fall back to terminal_state through the published_state property, same as before).
        self._published_state = None
        self.terminal_state = {
            "macro_regime": "Pending Data...",
            "directive": "Waiting for tape...",
            "metrics": {
                "10Y": {"value": 4.45, "status": "STALE_FALLBACK"},
                "30Y": {"value": 4.98, "status": "STALE_FALLBACK"},
                "WTI": {"value": 87.36, "status": "STALE_FALLBACK"},
                "DXY": {"value": 98.9, "status": "STALE_FALLBACK"},
                "Spot_Ag": {"value": 75.62, "status": "STALE_FALLBACK"},
                "Spreads": {"value": 2.72, "status": "STALE_FALLBACK"},
                "TED": {"value": 0.05, "status": "STALE_FALLBACK"},
                "EFFR": {"value": 4.33, "status": "STALE_FALLBACK"},
                "VIX": {"value": 15.74, "status": "STALE_FALLBACK"},
                "CFTC_Silver_Net_Longs": {"value": 35000.0, "status": "INITIAL_BASELINE"},
                "PHYSICAL_STRESS": {"value": False, "status": "INITIAL_BASELINE"},
                "DXY_MOMENTUM": {"value": 0.0, "status": "INITIAL_BASELINE"}
            },
            "nodes": {},
            "v4_valuation": {},
            "conviction_mode": {"status": "pending", "view": "conviction", "primary": True, "baskets": []},
            "agent_activity": [],   # ambient stream of what the agents are doing (hooks/agents POST here)
            "agent_annotations": {},  # ticker -> [badge/insight] left by agents (pin_insight/highlight)
            "agent_reply": None,    # the agent's latest full reply text (for the cockpit's prompt panel)
            "treasury_curve": None,  # full US Treasury curve via FMP (1mo…30yr), refreshed ~4x/day
            "pipeline": {"status": "idle", "theme": None, "stage": None, "started": None,
                         "updated": None, "events": [], "result": None, "verdicts": {}},
            "forensics": {
                "jsf_score": 4.0,
                "penalty_factor": 1.0,
                "runway": 70.8,
                "sloan_cfo": 0.02,
                "sloan_bs": 0.02
            },
            "portfolio_stats": {
                "expected_shortfall_95": 0.0,
                "avg_correlation": 0.0
            },
            "signals": [],
            "kill_switches": {"AGA_V": "SAFE (Pending Drill Assays)"},
            "systemic_stress": 0.0,
            "mri": 45.0,
            "metric_metadata": {
                "MRI": {
                    "definition": "Macro Regime Index. Aggregates systemic conditions by measuring tightness in dollar funding, credit, yield curve pressure, tail volatility, physical commodity strength, and speculative positioning.",
                    "calculation": "Linear blend of five normalized components: liquidity (0.30 weight), yields (0.20), volatility (0.20), commodities (0.15), and sentiment (0.15), calibrated via SOFR spread and Ag/Cu ranges.",
                    "actionability": "In the silver barbell portfolio, readings <45 favor full fractional Kelly allocation to the AGA.V spear under the REP Floor. Readings >65 trigger automatic reduction of the ADV liquidity cap, redirecting focus to ballast protection in GROY, URC.TO, and GMX.TO.",
                    "relationships": "Inversely affects dynamic ADV sizing cap; directly penalizes Health Rating; interacts with real yield to modulate ROV.",
                    "signals": "Green (<45): Favorable for deployment. Orange (45-65): Maintain guardrails. Red (>65): Prioritize capital preservation.",
                    "related_metrics": ["Health Rating", "ADV Cap", "Discovery Premium", "ROV", "Term Structure", "AISC Uplift", "10Y", "30Y", "TED", "DXY", "Spreads", "VIX", "WTI", "Spot_Ag", "CFTC_Silver_Net_Longs"]
                },
                "JSF": {
                    "definition": "Junior Survival Factor. A rigorous forensic accounting sieve scoring exploration and development assets against capital destruction risks.",
                    "calculation": "Discrete 0-4 point scale evaluating Cash Runway (>18mo), Accruals/Burn Acceleration (CBA <15% or Sloan <5%), Share Dilution (<2% QoQ), and SG&A Drag (<30% of burn).",
                    "actionability": "Scores <3.5 trigger strict allocation limits for AGA.V regardless of macro conditions, enforcing capital preservation against opaque balance sheet decay.",
                    "relationships": "Directly modulates the Forensic Penalty applied to IS-IAI valuation; heavily influences Health Rating.",
                    "signals": "Green (4.0): Risk shield secure. Orange (3.0-3.5): Mild drags, enforce caps. Red (<3.0): Severe forensic failure, extreme caution.",
                    "related_metrics": ["Health Rating", "Forensic Penalty", "IS-IAI", "CBA", "Dilution Sieve", "Sloan Ratios"]
                },
                "Health Rating": {
                    "definition": "A 1-10 composite score quantifying the overall reliability and safety of the terminal's valuation and sizing signals.",
                    "calculation": "Starts at 10.0, penalized by JSF degradation (forensics multiplier), high MRI (macro multiplier), stale data pipelines, and excessive ES95 tail risk.",
                    "actionability": "Determines the Tactical Ceiling for portfolio capital. A low rating indicates that model outputs contain high noise and should be treated as high-uncertainty limits rather than targets.",
                    "relationships": "Synthesizes JSF, MRI, ES95, and data pipeline status.",
                    "signals": "Green (>=8.5): High integrity, actionable. Orange (6.0-8.4): Moderate quality, exercise guardrails. Red (<6.0): High noise, extreme caution.",
                    "related_metrics": ["JSF", "MRI", "ES95"]
                },
                "REP Floor": {
                    "definition": "Resource, Execution, and Permitting Floor. The stressed, bare-minimum liquidation value of an asset.",
                    "calculation": "Aggregates raw cash treasury, heavily discounted inferred/measured ounces (symmetric 50% inferred haircut) RECONCILED to the sourced resource (filings magnitude + the real sitewide M&I/inferred split, not the optimistic config buckets), and permitting/infrastructure sunk costs, divided by shares outstanding.",
                    "actionability": "Serves as the ultimate downside support level for AGA.V. Buying near or below the REP Floor provides maximal margin of safety for the spear position.",
                    "relationships": "The COST leg of the Phase 4a triangulated AGA Intrinsic (confidence-tilted; ~30% stage weight for a pure explorer), reconciled to the SAME sourced resource base as the market leg. (The legacy fixed 15% weight is superseded.)",
                    "signals": "Green: Price < REP Floor (Deep value). Orange: Price near REP Floor. Red: Price significantly above REP Floor.",
                    "related_metrics": ["AGA.V Intrinsic"]
                },
                "ES95": {
                    "definition": "Expected Shortfall at 95% Confidence. Measures the average expected loss in the worst 5% of portfolio return scenarios.",
                    "calculation": "Derived from 60-day historical returns of the barbell components (AGA.V, GROY, URC.TO, GMX.TO) weighted by current allocation.",
                    "actionability": "Used to monitor tail risk. Reported as a SIGNED percent (negative = loss); a 95% ES worse than -5% (more negative) triggers Health-Rating penalties and throttles aggregate leverage via the ES95 Tail Brake in the Sizing Waterfall.",
                    "relationships": "Directly throttles Portfolio Sizer leverage (es_throttle); penalizes Health Rating via continuous convex function; interacts with Portfolio Volatility and Kelly Multiple.",
                    "signals": "Green (> -5%): Contained tail risk. Orange (-5% to -10%): Elevated tail risk. Red (< -10%): Severe downside exposure.",
                    "related_metrics": ["Health Rating", "VIX", "Kelly", "ADV Cap"]
                },
                "ADV Cap": {
                    "definition": "Average Daily Volume Liquidity Cap. The maximum dollar allocation permitted based on the asset's trading liquidity.",
                    "calculation": "Percentage (scaling down from max 15% as MRI increases) of the 10-day Average Daily Volume (ADV) in CAD.",
                    "actionability": "Prevents over-allocation into illiquid assets (AGA.V). Ensures exit liquidity without moving the tape, enforcing strict block execution frames.",
                    "relationships": "Inversely correlated with MRI; directly limits the E_Target (target capital allocation).",
                    "signals": "Green: Cap expanded (high liquidity/low macro stress). Orange: Cap standard. Red: Cap severely restricted.",
                    "related_metrics": ["MRI"]
                },
                "ROV": {
                    "definition": "Real Option Value (LEGACY). The old additive convexity premium for silver assets; superseded in Phase 4a by the stage-decayed option-convexity premium (1+pi_opt).",
                    "calculation": "Base premium (1.18x) modulated continuously by negative real yields (premium scales as yields drop <1%) and silver price volatility.",
                    "actionability": "Diagnostic only. The 'monetary battery' convexity it represented now flows through the option premium (realized vol + monetary carry) that multiplies the market leg, not a separate additive ROV term.",
                    "relationships": "SUPERSEDED: no longer carries an independent weight in the authoritative triangulated AGA Intrinsic (the legacy ~15% additive weight is retained only in the v4_valuation reconciliation baseline). Convexity now lives in the option premium on the market leg.",
                    "signals": "Green: High convexity environment (low yields, rising vol). Orange: Neutral. Red: Low convexity (high real yields).",
                    "related_metrics": ["10Y", "VIX", "Spot_Ag", "AGA.V Intrinsic"]
                },
                "Peer EV/oz": {
                    "definition": "Peer Enterprise Value per Ounce. The market-implied price paid for silver resources in the ground among comparable developers.",
                    "calculation": "Liquidity-weighted average of adjusted EV/oz across a basket of peers, factoring in stage multipliers, jurisdictional risk, and measured/indicated confidence.",
                    "actionability": "Provides the baseline multiple for valuing AGA.V's ounces in the IS-IAI metric. Identifies if the broad sector is undervalued or overheated.",
                    "relationships": "Directly multiplies effective ounces in IS-IAI calculation; informs Discovery Premium.",
                    "signals": "Green: Sector heavily discounted. Orange: Fair value. Red: Sector overvalued.",
                    "related_metrics": ["IS-IAI"]
                },
                "Sloan Ratios": {
                    "definition": "Sloan Accrual Ratios (CFO & Balance Sheet). Measures the quality of earnings and cash flow persistence.",
                    "calculation": "(Net Income - Operating Cash Flow) / Total Assets, and similar balance sheet accrual derivations.",
                    "actionability": "High accruals (>5%) indicate non-cash earnings inflation or opaque capital capitalization. Used in the JSF to flag potential accounting stress in ballast assets (GROY, URC.TO, GMX.TO).",
                    "relationships": "Core component of the JSF; drives forensic penalties on ballast valuations.",
                    "signals": "Green (<5%): Clean cash-backed earnings. Orange: Monitor accruals. Red (>5%): Accrual overload, high accounting risk.",
                    "related_metrics": ["JSF"]
                },
                "Discovery Premium": {
                    "definition": "Discovery Premium Factor. The market reward multiple for active, high-grade exploration success and resource expansion.",
                    "calculation": "Product of commodity leverage (spot vs AISC), profit margins, and an explorer re-rating scalar, capped dynamically by macro conditions (MRI) and spot deviations.",
                    "actionability": "Diagnostic only (the v4_valuation reconciliation baseline). Speculative torque is no longer applied as a separate multiplier; it is captured once via the live peer EV/oz and once via the stage-decayed option premium.",
                    "relationships": "REMOVED in Phase 4a from the authoritative valuation: this ~3.3x operating-leverage multiple double-counted the silver level already priced into peer EV/oz, so it was deleted from the triangulated market leg (silver torque now flows ONCE via peer EV/oz, ONCE via the option premium).",
                    "signals": "Green: Market rewarding discovery. Orange: Neutral. Red: Market ignoring drill results (macro cap active).",
                    "related_metrics": ["MRI", "Spot_Ag", "AISC Uplift", "IS-IAI"]
                },
                "IS-IAI": {
                    "definition": "In-Situ Inferred & Indicated Valuation (LEGACY). The old comps-based core asset value; superseded in Phase 4a by the de-overlapped MARKET leg of the triangulation.",
                    "calculation": "LEGACY formula: Effective ounces * Peer EV/oz * Discovery Premium * Jurisdiction Uplift * Recovery * Capital Discount. The authoritative market leg DROPS the Discovery Premium multiplier (double-count) and grades ounces by Technical Quality instead.",
                    "actionability": "SUPERSEDED: the legacy 70%-weight IS-IAI is replaced by the confidence-tilted Cost+Market+Income triangulation. Its job — comps x effective ounces x geological confidence — now lives in the de-overlapped MARKET leg (peer EV/oz x technical quality x capital discount). Retained as a v4_valuation diagnostic only.",
                    "relationships": "Requires Peer EV/oz and the macro Capital Discount Factor; modulated by JSF Forensic Penalty. (No longer multiplied by the removed Discovery Premium.)",
                    "signals": "Green: High intrinsic value relative to price. Orange: Fairly valued. Red: Overvalued relative to peers.",
                    "related_metrics": ["JSF", "Peer EV/oz", "Discovery Premium", "AGA.V Intrinsic"]
                },
                "Priorities": {
                    "definition": "Actionable Strategic Directives generated by the Health Radar.",
                    "calculation": "Rule-based synthesis evaluating Implied Edge (valuation arbitrage), JSF Score (accounting safety), MRI (macro scaling), and Kelly Multiple (overallocation).",
                    "actionability": "Provides the 1-2-3 step execution plan for the portfolio manager. Determines whether to exploit spear arbitrage, enforce sizing caps, or trim overallocations.",
                    "relationships": "Aggregates all major engine outputs (Valuation, Forensics, Macro, Sizing) into plain text.",
                    "signals": "Green: Proceed with execution. Orange: Trim or hold with caution. Red: Defensive mitigation required.",
                    "related_metrics": []
                },
                "CBA": {
                    "definition": "Cash Burn Acceleration. Measures whether quarter-over-quarter cash outflow is expanding relative to the company's size.",
                    "calculation": "QoQ change in burn (Burn = -CFO) normalized by ENTERPRISE VALUE (a size proxy; gate ~3%) so a deliberately lean treasury does not self-incriminate. Falls back to the legacy /Total Cash basis (gate 15%) when EV is unavailable; both are recorded for audit.",
                    "actionability": "An accelerating burn (above the EV-normalized ~3% gate, or the legacy 15%-of-cash fallback) warns of explosive cash drain and imminent dilution; it fails the JSF accrual test and triggers capital-preservation caps.",
                    "relationships": "Core component of the JSF Score for explorers.",
                    "signals": "Green (<15%): Burn stable or decelerating. Red (>15%): Rapidly accelerating burn, dilution imminent.",
                    "related_metrics": ["JSF"]
                },
                "Dilution Sieve": {
                    "definition": "Weighted quarterly share count expansion screen designed to catch dilution-heavy juniors.",
                    "calculation": "(Shares_T0 - Shares_T1) / Shares_T1 (QoQ share count growth).",
                    "actionability": "Share dilution >= 2% QoQ fails the sieve, triggering a 35% weight penalty on the JSF explorer score to discount resources.",
                    "relationships": "Weights dilution at 35% of the explorer forensic penalty applied to IS-IAI.",
                    "signals": "Green (<2%): Protected from equity dilution. Red (>=2%): Sieve failure, high valuation decay.",
                    "related_metrics": ["JSF"]
                },
                "AISC Uplift": {
                    "definition": "Dynamic margin adjustment modeling energy and oil cost impacts on mining economics.",
                    "calculation": "Base AISC + max(0, WTI Crude Oil - 80.0) * 0.15.",
                    "actionability": "A high WTI price increases operating costs, which shrinks profit margins and compresses the Discovery Premium.",
                    "relationships": "Directly reduces phi profit margins and limits the Discovery Premium ceiling.",
                    "signals": "Green: Energy drag neutral (WTI < $80). Red: Energy inflation squeeze (WTI > $80).",
                    "related_metrics": ["WTI", "Discovery Premium"]
                },
                "Term Structure": {
                    "definition": "Futures curve pricing gradient measuring physical metal tightness.",
                    "calculation": "True if Month 1 futures price exceeds Month 6 price (Backwardation); False otherwise (Contango).",
                    "actionability": "Indicates direct immediate physical demand. Backwardation triggers a physical stress premium (up to 25%) on resources.",
                    "relationships": "Adds an immediate supply premium to the project Jurisdiction Uplift.",
                    "signals": "Green: Backwardation (Physical stress premium active). Red: Contango (Standard spot structure).",
                    "related_metrics": ["Spot_Ag", "Discovery Premium"]
                },
                "10Y": {
                    "definition": "10-Year US Treasury Yield. Standard benchmark for global risk-free discount rates.",
                    "calculation": "Live yield fetched from data pipelines.",
                    "actionability": "Direct component of real interest rate calculations, which in turn modulate silver Real Option Value (ROV).",
                    "relationships": "Feeds into MRI and Real Yield formulas.",
                    "signals": "Green (<3.75%): Accommodative. Orange (3.75-4.75%): Tightening. Red (>4.75%): Restrictive.",
                    "related_metrics": ["MRI", "ROV"]
                },
                "30Y": {
                    "definition": "30-Year US Treasury Yield. Standard long-term risk-free rate pricing.",
                    "calculation": "Live yield fetched from data pipelines.",
                    "actionability": "Used to monitor steepening vs. inversion of the long end of the yield curve.",
                    "relationships": "Feeds into MRI curve steepening formula.",
                    "signals": "Green (<4.00%): Stable. Red (>5.00%): Curve stress.",
                    "related_metrics": ["MRI"]
                },
                "TED": {
                    "definition": "SOFR Spread / TED Spread equivalent. Measures stress in money markets and commercial banking liquidity.",
                    "calculation": "3-Month SOFR rate minus 3-Month US Treasury bill yield.",
                    "actionability": "Spikes > 0.40% indicate systemic liquidity strain in the interbank repo market.",
                    "relationships": "Core component of MRI Liquidity weight.",
                    "signals": "Green (<0.20%): Liquid. Red (>0.45%): Acute interbank stress.",
                    "related_metrics": ["MRI", "Health Rating"]
                },
                "DXY": {
                    "definition": "US Dollar Index. Measures strength of the USD against a basket of foreign currencies.",
                    "calculation": "Live exchange rate index value.",
                    "actionability": "Strong USD (>104) typically suppresses global asset prices and compresses liquidity.",
                    "relationships": "Feeds into MRI Liquidity weight.",
                    "signals": "Green (<100): Weak dollar tailwind. Red (>104): Strong dollar headwind.",
                    "related_metrics": ["MRI"]
                },
                "Spreads": {
                    "definition": "High Yield Corporate Bond Option-Adjusted Spreads.",
                    "calculation": "Weighted index yield premium over Treasuries.",
                    "actionability": "Rising credit spreads indicate credit stress, raising financing costs for resource juniors.",
                    "relationships": "Feeds into MRI credit component.",
                    "signals": "Green (<3.50%): Tight spreads, healthy credit. Red (>5.00%): Wide spreads, elevated defaults.",
                    "related_metrics": ["MRI", "Health Rating"]
                },
                "VIX": {
                    "definition": "CBOE Volatility Index. Measures standard market-implied near-term tail risk.",
                    "calculation": "VIX implied volatility percentage index.",
                    "actionability": "High VIX (>23) triggers cash reserve preservation targets.",
                    "relationships": "Feeds into MRI volatility component and ROV expansion formula.",
                    "signals": "Green (<15.0): Low fear. Red (>23.0): Extreme market fear.",
                    "related_metrics": ["MRI", "ROV", "Health Rating"]
                },
                "WTI": {
                    "definition": "West Texas Intermediate Crude Oil spot price.",
                    "calculation": "Live dollar spot price per barrel.",
                    "actionability": "High oil costs (>80) increase energy fuel surcharges at remote mine sites, raising explorer AISC costs.",
                    "relationships": "Feeds into AISC energy uplift formula.",
                    "signals": "Green (<$75): Low mining fuel costs. Red (>$85): Inflationary energy squeeze.",
                    "related_metrics": ["MRI", "AISC Uplift"]
                },
                "Spot_Ag": {
                    "definition": "Spot Silver price per ounce in USD.",
                    "calculation": "Live global spot price.",
                    "actionability": "The primary macro pricing factor for silver leverage barbell components.",
                    "relationships": "Directly impacts Discovery Premium and Term Structure calculations.",
                    "signals": "Green (>$32): Bull market surge. Red (<$24): Bear market capitulation.",
                    "related_metrics": ["MRI", "ROV", "Discovery Premium", "Term Structure"]
                },
                "CFTC_Silver_Net_Longs": {
                    "definition": "CFTC Silver Non-Commercial Net Speculator Position.",
                    "calculation": "Speculator long contracts minus short contracts.",
                    "actionability": "Extreme net-shorts represent highly bullish contrarian capitulation setups.",
                    "relationships": "Feeds into MRI contrarian sentiment weight.",
                    "signals": "Green: Capitulation net-short. Red: Overcrowded net-long.",
                    "related_metrics": ["MRI"]
                },
                "GSR": {
                    "definition": "Gold/Silver Ratio. The number of silver ounces needed to buy one ounce of gold. A key macro indicator for precious metals relative valuation.",
                    "calculation": "Gold Spot Price / Silver Spot Price.",
                    "actionability": "GSR below 75 signals silver outperformance (bullish for the barbell thesis). GSR above 85 signals extreme silver undervaluation or risk-off conditions — historically a contrarian accumulation signal for silver assets.",
                    "relationships": "Inversely correlated with silver momentum; high GSR historically precedes silver rallies. Contextualizes MRI commodity component.",
                    "signals": "Green (<75): Silver outperforming, bullish momentum. Orange (75-85): Neutral ratio. Red (>85): Extreme undervaluation or risk-off.",
                    "related_metrics": ["MRI", "Spot_Ag", "Discovery Premium"]
                }
            }
        }

    def _effective_config(self) -> dict:
        """The single source of truth the engine providers read each call: the per-cycle effective
        config (`self.config` == file defaults + confirmed overrides), rebuilt once per cycle by
        `_refresh_effective_config`. Falls back to a raw file read if `self.config` is somehow empty
        (e.g. the overlay failed at construction) so an engine call can never be starved of config."""
        cfg = getattr(self, "config", None)
        if isinstance(cfg, dict) and cfg:
            return cfg
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _refresh_effective_config(self) -> dict:
        """Rebuild `self.config` for the cycle from a FRESH read of v5_config.json (so direct file
        edits to any key still hot-reload — most config is outside the dynamic-config allowlist and
        can only change via the file) layered with the confirmed SQLite overrides. One disk read per
        cycle replaces the per-engine-method reads, and every engine sees the SAME snapshot for the
        whole cycle (no mid-cycle TOCTOU). Returns the effective dict."""
        try:
            with open(self.config_path, "r") as f:
                defaults = json.load(f)
        except Exception as e:
            logging.warning("config reload failed; reusing last effective config: %s", e)
            return self._effective_config()
        if getattr(self, "dconfig", None) is not None:
            try:
                self.dconfig.set_defaults(defaults)
                self.config = self.dconfig.effective()
            except Exception as e:
                logging.warning("overlay merge failed; using raw file defaults: %s", e)
                self.config = defaults
        else:
            self.config = defaults
        return self.config

    def start_background_tasks(self):
        # A1.9: every worker is SUPERVISED — a crash (or an impossible return from an infinite
        # loop) is recorded into terminal_state["worker_health"], flips the status line on the
        # next eval, and republishes immediately. Surfacing only — no silent auto-restart.
        import task_supervision as _tsup
        health = self.terminal_state.setdefault("worker_health", {})

        def _on_death(name, error):
            logging.error("background worker %s DIED: %s", name, error)
            self.terminal_state["status"] = "DEGRADED_WORKER_DOWN: " + name
            self.publish_state()

        self.tasks = [
            _tsup.create_supervised("prices", self._prices_worker(), health=health, on_death=_on_death),
            _tsup.create_supervised("macro", self._macro_worker(), health=health, on_death=_on_death),
            _tsup.create_supervised("cftc", self._cftc_worker(), health=health, on_death=_on_death),
            _tsup.create_supervised("comps", self._comps_worker(), health=health, on_death=_on_death),
        ]
        return self.tasks

    def _load_shares_from_csv(self, force=False):
        # Glob the NEWEST holdings-report-*.csv (cwd or alongside the engine) instead of pinning to a
        # single dated filename, so the book's position truth isn't frozen to a stale snapshot.
        import glob
        _here = os.path.dirname(os.path.abspath(__file__))
        _cands = [p for p in set(glob.glob("holdings-report-*.csv")
                                 + glob.glob(os.path.join(_here, "holdings-report-*.csv")))
                  if os.path.exists(p)]
        holdings_path = max(_cands, key=os.path.getmtime) if _cands else None
        if not holdings_path:
            return False
        try:
            mtime = os.path.getmtime(holdings_path)
            self._holdings_csv = {"file": os.path.basename(holdings_path),
                                  "age_days": round(max(0.0, time.time() - mtime) / 86400.0, 1)}
            if not force and mtime == self.last_csv_mtime:
                return True

            df = pd.read_csv(holdings_path)
            new_shares = {}
            for _, row in df.iterrows():
                symbol = str(row.get('Symbol', '')).strip().upper()
                if not symbol or symbol == 'NAN':
                    continue
                try:
                    qty = float(row.get('Quantity', 0))
                except:
                    qty = 0
                if 'AGA' in symbol:
                    new_shares['AGA'] = qty
                elif 'URC' in symbol and 'UROY' not in symbol:
                    new_shares['URC'] = qty
                elif 'GROY' in symbol:
                    new_shares['GROY'] = qty
                elif 'GMX' in symbol:
                    new_shares['GMX'] = qty
                elif 'UROY' in symbol:
                    new_shares['UROY_CALL'] = qty
                    try:
                        self.uroy_call_price = float(row.get('Market Price', 0.60))
                    except Exception:
                        self.uroy_call_price = 0.60
            if new_shares:
                self.shares = new_shares
                self.last_csv_mtime = mtime
                print(f"Loaded share quantities from CSV: {self.shares}")
                return True
        except Exception as e:
            print(f"Failed to load shares from CSV: {e}")
        return False

    def _get_fallback_price(self, ticker):
        fallbacks = {
            "AGA.V": 0.71, "GROY": 3.22, "GMX.TO": 2.04,
            "URC.TO": 4.82, "SI=F": 74.8, "CL=F": 89.5, "DX-Y.NYB": 99.0,
            "^VIX3M": 18.5
        }
        return fallbacks.get(ticker, 0.0)

    # ==================== DECOUPLED BACKGROUND WORKERS ====================

    async def _prices_worker(self):
        while True:
            try:
                t_start = time.time()
                # Compute Month 6 forward silver contract ticker dynamically
                import datetime
                now = datetime.datetime.now()
                curr_month = now.month
                curr_year_short = now.year % 100
                if curr_month in [1, 2]: code, yr = "N", curr_year_short
                elif curr_month in [3, 4, 5]: code, yr = "Z", curr_year_short
                elif curr_month in [6, 7, 8]: code, yr = "H", curr_year_short + 1
                else: code, yr = "N", curr_year_short + 1
                m180_ticker = f"SI{code}{yr:02d}.CMX"

                # Standard consolidated tickers list (15 items) + the promoted EVAL set, so a
                # graduated candidate gets a live mark the cycle after promotion (config
                # hot-reloads through _refresh_effective_config; the worker re-reads each loop)
                eval_tks = eval_only_tickers(self.config)
                tickers = [
                    "CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO", "USDCAD=X",
                    "HG=F", "GC=F", "^IRX", "^TNX", "^TYX", "^VIX", m180_ticker
                ] + eval_tks

                # Perform a single bulk HTTP download to Yahoo
                def get_bulk_data():
                    try:
                        df = yf.download(tickers, period="10d", group_by="ticker", progress=False)
                        return df
                    except Exception as e:
                        print(f"[Prices Worker] yfinance bulk download failed: {e}")
                        return None

                df = await asyncio.to_thread(get_bulk_data)

                # 1. Parse Prices — provenance-aware (audit fix). A holding's CURRENT price prefers
                # the live intraday quote (regularMarketPrice): the daily bulk bar lags a session and
                # is frequently NaN on the latest day for an individual name, so the prior
                # df[t]['Close'].dropna().iloc[-1] silently served a 1-2 day-old close as if LIVE.
                # Now: intraday -> dated daily close (flagged stale if not today) -> last-good cache
                # -> hardcoded constant (last resort), STAMPING per-ticker as_of/stale so a stale
                # mark can never masquerade as live again. Intraday is independent of the bulk df,
                # so holdings still get a fresh mark even if the bulk download partially fails.
                import market_data
                md = getattr(self, "_md", None)
                if md is None:
                    md = market_data.MarketData(fmp=getattr(self, "fmp", None))
                    self._md = md
                today_d = now.date()
                hold_equities = {"AGA.V", "GROY", "GMX.TO", "URC.TO"} | set(eval_tks)
                last_good = _load_from_cache("prices", {})
                last_good_asof = _load_from_cache("prices_asof", {})

                def _intraday_for_holdings():
                    out = {}
                    for tk in hold_equities:
                        try:
                            q = md.yahoo_quote(tk)
                            if q and not q.get("stale") and _is_pos(q.get("price")):
                                out[tk] = float(q["price"])
                        except Exception:
                            pass
                    return out
                intraday_map = await asyncio.to_thread(_intraday_for_holdings)

                prices, prices_asof, prices_stale = {}, {}, {}
                primary_tickers = ["CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO", "USDCAD=X", "^VIX3M"] + eval_tks
                for t in primary_tickers:
                    daily = []
                    try:
                        if df is not None and t in df.columns.levels[0]:
                            ser = df[t]['Close'].dropna()
                            daily = [(idx.date(), float(v)) for idx, v in ser.items()]
                    except Exception as e:
                        print(f"[Prices Worker] Price parse error for {t}: {e}")
                        daily = []
                    lg = {"price": float(last_good[t]), "as_of": last_good_asof.get(t)} \
                        if _is_pos(last_good.get(t)) else None
                    r = market_data.resolve_freshness(daily_closes=daily,
                                                      intraday=intraday_map.get(t),
                                                      last_good=lg, today=today_d)
                    if r.get("price") is None:
                        r = {"price": self._get_fallback_price(t), "as_of": None,
                             "stale": True, "source": "hardcoded-fallback"}
                    prices[t] = r["price"]
                    prices_asof[t] = r["as_of"]
                    prices_stale[t] = bool(r["stale"])

                _save_to_cache("prices", prices)
                _save_to_cache("prices_asof", prices_asof)
                # Honest status: a stale/fallback mark on ANY holding demotes the feed from LIVE so
                # the cockpit/rating can flag it (the old code hard-coded "LIVE" right here, which is
                # how a multi-day-stale holding kept reading as live).
                _stale_holdings = sorted(t for t in hold_equities if prices_stale.get(t))
                prices_status = "DEGRADED" if _stale_holdings else "LIVE"
                if _stale_holdings:
                    print(f"[Prices Worker] DEGRADED — stale/fallback marks: {', '.join(_stale_holdings)}")

                # 2. Parse Copper and Gold
                copper, gold = 4.2, 2350.0
                try:
                    if df is not None and "HG=F" in df.columns.levels[0]:
                        cu_hist = df["HG=F"]['Close'].dropna()
                        if not cu_hist.empty: copper = float(cu_hist.iloc[-1])
                    if df is not None and "GC=F" in df.columns.levels[0]:
                        au_hist = df["GC=F"]['Close'].dropna()
                        if not au_hist.empty: gold = float(au_hist.iloc[-1])
                    _save_to_cache("copper_gold", {"copper": copper, "gold": gold})
                except Exception as e:
                    print(f"[Prices Worker] Copper/Gold parse error: {e}")
                    cached = _load_from_cache("copper_gold", {"copper": 4.2, "gold": 2350.0})
                    copper, gold = cached["copper"], cached["gold"]

                # 3. Silver Term Structure
                m1_price = prices.get("SI=F", 74.8)
                m180_price = m1_price
                try:
                    if df is not None and m180_ticker in df.columns.levels[0]:
                        m180_hist = df[m180_ticker]['Close'].dropna()
                        if not m180_hist.empty: m180_price = float(m180_hist.iloc[-1])
                except Exception as e:
                    print(f"[Prices Worker] Term structure parse error: {e}")

                # 4. Sovereign Rates & Volatility proxies (Real-Time backup / feed)
                try:
                    y10_val, y30_val, y3mo_val, vix_val = 4.45, 4.98, 4.33, 15.74
                    if df is not None and "^TNX" in df.columns.levels[0]:
                        hist_10 = df["^TNX"]['Close'].dropna()
                        if not hist_10.empty: y10_val = float(hist_10.iloc[-1])
                    if df is not None and "^TYX" in df.columns.levels[0]:
                        hist_30 = df["^TYX"]['Close'].dropna()
                        if not hist_30.empty: y30_val = float(hist_30.iloc[-1])
                    if df is not None and "^IRX" in df.columns.levels[0]:
                        hist_3m = df["^IRX"]['Close'].dropna()
                        if not hist_3m.empty: y3mo_val = float(hist_3m.iloc[-1])
                    if df is not None and "^VIX" in df.columns.levels[0]:
                        hist_v = df["^VIX"]['Close'].dropna()
                        if not hist_v.empty: vix_val = float(hist_v.iloc[-1])

                    _save_to_cache("yf_live_macro", {
                        "y10": y10_val,
                        "y30": y30_val,
                        "y3mo": y3mo_val,
                        "vix": vix_val
                    })
                except Exception as e:
                    print(f"[Prices Worker] Live yields parse error: {e}")

                # 5. Silver ADV volume
                aga_adv = 150000
                try:
                    aga_adv = await self.sizer.get_liquidity_cap("AGA.V")
                except Exception as e:
                    print(f"[Prices Worker] Liquidity cap error: {e}")

                # Update State Cache
                with self.state_lock:
                    self.state_cache["prices"] = prices
                    self.state_cache["prices_status"] = prices_status
                    self.state_cache["prices_asof"] = prices_asof
                    self.state_cache["prices_stale"] = prices_stale
                    self.state_cache["prices_ts"] = time.time()
                    self.state_cache["usd_to_cad"] = prices.get("USDCAD=X", 1.38)
                    self.state_cache["copper"] = copper
                    self.state_cache["gold"] = gold
                    self.state_cache["m1_price"] = m1_price
                    self.state_cache["m180_price"] = m180_price
                    self.state_cache["aga_adv"] = aga_adv

                elapsed = time.time() - t_start
                print(f"[*] [Prices Worker] Synchronized live prices successfully in {elapsed:.3f}s (1 consolidated yfinance call).")
            except Exception as ex:
                print(f"[!] [Prices Worker] Main Loop Error: {ex}")
            await asyncio.sleep(60)

    async def _macro_worker(self):
        while True:
            try:
                # 1. FRED macro data
                res, status = await self.macro_engine.fetch_macro_data()
                
                # 2. Real yield
                real_yield, ry_status = await self.macro_engine.fetch_real_yield()
                
                # 3. DXY momentum
                dxy_mom, current_dxy, dxy_status = await self.macro_engine.fetch_dxy_momentum()

                # 4. MRI rolling-percentile history (Phase 0): disk-cached with a 24h TTL, so polling
                #    it on the 30-min macro cadence almost always hits the cache and is near-free. Stored
                #    independently of `res` so the dynamic bounds survive a FRED/macro fetch failure.
                mri_history = await self.macro_engine.fetch_mri_history()
                if mri_history:
                    with self.state_lock:
                        self.state_cache["mri_history"] = mri_history

                # Update State Cache
                if res and len(res) >= 6:
                    with self.state_lock:
                        self.state_cache["y10"] = res[0]
                        self.state_cache["y30"] = res[1]
                        self.state_cache["spr"] = res[2]
                        self.state_cache["ted"] = res[3]
                        self.state_cache["eff"] = res[4]
                        self.state_cache["vix"] = res[5]
                        self.state_cache["macro_status"] = status
                        self.state_cache["macro_ts"] = time.time()

                        self.state_cache["real_yield"] = real_yield
                        self.state_cache["ry_status"] = ry_status
                        self.state_cache["ry_ts"] = time.time()

                        self.state_cache["dxy_mom"] = dxy_mom
                        self.state_cache["current_dxy"] = current_dxy
                        self.state_cache["dxy_status"] = dxy_status
                        self.state_cache["dxy_ts"] = time.time()
                    print(f"[*] [Macro Worker] Synchronized live FRED and macro parameters successfully.")
            except Exception as ex:
                print(f"[!] [Macro Worker] Main Loop Error: {ex}")
            await asyncio.sleep(1800) # 30 minutes

    async def _cftc_worker(self):
        retry_delay = 300  # 5 minutes for transient failures
        standard_sleep = 14400  # 4 hours
        
        while True:
            try:
                # Load configuration parameters
                cfg = self.peer_engine.get_config()
                cftc_cfg = cfg.get("cftc_params", {
                    "primary_contract_code": "CFTC_084691",
                    "fallback_contract_code": "CFTC_084691",
                    "managed_money_multiplier_0_to_1": 100000,
                    "managed_money_multiplier_0_to_100": 1000
                })
                primary_code = cftc_cfg["primary_contract_code"]
                fallback_code = cftc_cfg["fallback_contract_code"]

                def openbb_cftc():
                    from openbb import obb
                    # Direct, explicit retrieval of standard institutional Silver Futures
                    cftc_router = None
                    if hasattr(obb, "regulators") and hasattr(obb.regulators, "cftc"):
                        cftc_router = obb.regulators.cftc
                    elif hasattr(obb, "cftc"):
                        cftc_router = obb.cftc

                    if cftc_router is not None:
                        try:
                            # Prioritize direct lookup via precise code (CFTC_084691)
                            res = cftc_router.cot(code=primary_code)
                        except Exception:
                            try:
                                search_res = cftc_router.cot_search(query="silver")
                                df_search = search_res.to_dataframe()
                                if not df_search.empty:
                                    # Prioritize standard institutional code
                                    silver_rows = df_search[df_search['code'] == primary_code]
                                    if silver_rows.empty:
                                        # Filter out micro/mini/CBOT retail contracts explicitly
                                        silver_rows = df_search[df_search['name'].str.contains('SILVER', case=False, na=False)]
                                        silver_rows = silver_rows[~silver_rows['name'].str.contains('MICRO|MINI|E-MINI|CBOT', case=False, na=False)]
                                    target_code = str(silver_rows['code'].iloc[0]) if not silver_rows.empty else str(df_search['code'].iloc[0])
                                    res = cftc_router.cot(code=target_code)
                                else:
                                    res = cftc_router.cot(code=fallback_code)
                            except Exception:
                                res = cftc_router.cot(code=fallback_code)
                    elif hasattr(obb, "regulators") and hasattr(obb.regulators, "cftc"):
                        try:
                            res = obb.regulators.cftc.cot(id="silver")
                        except Exception:
                            res = obb.regulators.cftc.cot(symbol="silver")
                    else:
                        raise AttributeError("CFTC router missing.")
                    return res.to_dataframe()

                df_cot = await asyncio.to_thread(openbb_cftc)
                if not df_cot.empty:
                    # Map columns for O(1) homogeneous pairing lookup
                    col_map = {str(c).lower().replace("_", "").replace(" ", ""): c for c in df_cot.columns}
                    
                    # Homogeneous Speculator Category Preferences (Managed Money preferred for professional sentiment)
                    spec_categories = [
                        ("managedmoney", "mmoney"),
                        ("noncommercial", "noncomm")
                    ]
                    
                    long_col, short_col = None, None
                    for cat_aliases in spec_categories:
                        for alias in cat_aliases:
                            # Find all columns matching speculator category and containing 'long' or 'short'
                            longs = [orig for clean, orig in col_map.items() if alias in clean and "long" in clean]
                            shorts = [orig for clean, orig in col_map.items() if alias in clean and "short" in clean]
                            if longs and shorts:
                                # Filter out percentage columns first to prioritize raw counts
                                raw_longs = [c for c in longs if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                                raw_shorts = [c for c in shorts if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                                if raw_longs and raw_shorts:
                                    long_col, short_col = raw_longs[0], raw_shorts[0]
                                else:
                                    long_col, short_col = longs[0], shorts[0]
                                break
                        if long_col and short_col:
                            break

                    if long_col and short_col:
                        df_valid = df_cot.dropna(subset=[long_col, short_col])
                        if not df_valid.empty:
                            latest_row = df_valid.iloc[-1]
                            long_val, short_val = float(latest_row[long_col]), float(latest_row[short_col])
                            
                            # Handle percentage scale detection (unified contract counts conversion)
                            # Patched: Robustly classify values <= 100.0 (but > 1.0) as percentages even if column lacks 'pct'
                            is_pct = ("pct" in str(long_col).lower() or "percent" in str(long_col).lower() or 
                                      (abs(long_val) <= 100.0 and abs(short_val) <= 100.0 and (abs(long_val) > 1.0 or abs(short_val) > 1.0)))
                            is_decimal_fraction = (abs(long_val) <= 1.0 and abs(short_val) <= 1.0)
                            
                            if is_pct or is_decimal_fraction:
                                if is_decimal_fraction:
                                    # 0.0 - 1.0 scale
                                    scale_mult = cftc_cfg["managed_money_multiplier_0_to_1"]
                                else:
                                    # 0 - 100 scale (e.g. 45.0)
                                    scale_mult = cftc_cfg["managed_money_multiplier_0_to_100"]
                                net_position = (long_val - short_val) * scale_mult
                            else:
                                # Raw Contract Counts
                                net_position = long_val - short_val
                                
                            with self.state_lock:
                                self.state_cache["cftc_net_longs"] = net_position
                                self.state_cache["cftc_status"] = "LIVE"
                                self.state_cache["cftc_ts"] = time.time()
                            print(f"[*] [CFTC Worker] Speculative net positioning synced successfully: {net_position:+,}")
                            await asyncio.sleep(standard_sleep)
                            continue
                
                # If df_cot is empty, treat as failure
                raise ValueError("Retrieved COT dataframe is empty.")

            except Exception as e:
                print(f"[!] [CFTC Worker] Error occurred: {e}")
                with self.state_lock:
                    self.state_cache["cftc_status"] = "DEGRADED_STALE"
                print(f"[*] [CFTC Worker] Status degraded. Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

    async def _comps_worker(self):
        while True:
            try:
                # 1. Peer Comps ev/oz — pass the LIVE FX so USD-listed peers convert at the current
                # rate, not the hardcoded 1.38 default (the EV/oz blend drifts with CAD otherwise).
                with self.state_lock:
                    _usd_to_cad = self.state_cache.get("usd_to_cad", 1.38)
                mean_peer_ev, peer_details, avg_disc_cost = await self.peer_engine.fetch_and_calculate_weighted_comps(usd_to_cad=_usd_to_cad)
                
                # 2. Forensic metrics
                tickers = ["AGA.V", "GROY", "URC.TO", "GMX.TO"]
                forensic_data = {}
                for t in tickers:
                    try:
                        m = await self.forensic_engine.fetch_forensic_metrics(t)
                        if m:
                            forensic_data[t] = m
                    except Exception as e:
                        print(f"[Comps Worker] Forensic metric fetch error for {t}: {e}")

                # 3. Barbell tickers historical returns
                barbell_tickers = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]
                df_rets, corr_matrix, vols = await self.sizer.fetch_historical_returns(barbell_tickers)

                es_95 = -0.052          # signed decimal (negative = loss); overwritten by the live compute below
                port_vol = 0.40
                avg_corr = 0.45
                if df_rets is not None and not df_rets.empty:
                    # Derive the weight vector from the single barbell-weights source, ORDERED to the
                    # ticker list (the old literal np.array([0.60,0.15,0.10,0.15]) was one reorder from
                    # silently mis-weighting GMX vs URC).
                    _bw = _resolve_barbell_weights(self.config)
                    weights = np.array([_bw.get(t, 0.0) for t in barbell_tickers])
                    es_95 = self.sizer.robust_expected_shortfall(df_rets, weights)
                    port_returns = df_rets.dot(weights)
                    port_vol = float(port_returns.std() * np.sqrt(252))
                    corr_sum = 0.0
                    corr_count = 0
                    for i, t1 in enumerate(barbell_tickers):
                        for j, t2 in enumerate(barbell_tickers):
                            if i < j:
                                corr_sum += corr_matrix.get(t1, {}).get(t2, 0.0)
                                corr_count += 1
                    avg_corr = corr_sum / corr_count if corr_count > 0 else 0.0

                with self.state_lock:
                    self.state_cache["mean_peer_ev"] = mean_peer_ev
                    self.state_cache["peer_details"] = peer_details
                    self.state_cache["avg_disc_cost"] = avg_disc_cost
                    self.state_cache["peers_ts"] = time.time()
                    if forensic_data:
                        self.state_cache["forensic_metrics"].update(forensic_data)
                    if df_rets is not None:
                        self.state_cache["df_rets"] = df_rets
                        self.state_cache["corr_matrix"] = corr_matrix
                        self.state_cache["vols"] = vols
                        self.state_cache["es_95"] = es_95
                        self.state_cache["port_vol"] = port_vol
                        self.state_cache["avg_corr"] = avg_corr
                print(f"[*] [Comps Worker] Synced weighted comps, returns, and forensics successfully.")
            except Exception as ex:
                print(f"[!] [Comps Worker] Error: {ex}")
            await asyncio.sleep(14400) # 4 hours

    # ==================== ORCHESTRATOR LOOP (INSTANT CPU-BOUND CALCULATIONS) ====================

    # ================= PHASE 5b — ADDITIVE ARCHETYPE INTEGRATION =================
    # The three helpers below bridge the Polymorphic Archetype Factory into the live
    # loop. They are pure-Python, side-effect-free w.r.t. the legacy valuation, and the
    # only entry point (_compute_archetype_valuations) is fully isolated in try/except.

    def _build_regime_impact_vector(self, mri_score: float, real_yield: float,
                                    silver_vol: float, dxy_mom: float,
                                    cfg: "dict | None" = None) -> tuple:
        """Derive the Druckenmiller-style RegimeImpactVector
        ``(alpha_option, alpha_margin, alpha_cyclical, alpha_yield, alpha_delta)`` from the
        live macro state, each clamped to [-1, 1]. Positive alpha = a tailwind for that
        archetype's lifecycle (lean in); negative = headwind (fade).

        Layer A is fully config-driven via ``archetype_factory.regime_derivation``: the
        normalization pivots/scales AND the per-alpha signal weights are read from config,
        with EVERY value falling back to the in-code default below if the block is missing or
        a key is absent/malformed — so behavior is identical to the prior hardcoded version
        until the JSON is actively tuned. Pivots double as center+scale; ``*_scale`` keys are
        pure denominators (guarded against zero). The live ``cfg`` is passed in by the loop so
        edits to the JSON take effect on the next cycle (no restart)."""
        def c(x: float) -> float:
            return max(-1.0, min(1.0, x))

        # In-code defaults == the original hardcoded constants (the safety fallback).
        D = {
            "mri_pivot": 50.0, "neg_yield_breakeven": 1.0, "neg_yield_scale": 2.0,
            "vol_pivot": 0.30, "dxy_scale": 2.0,
            "alpha_option":   {"risk_on": 0.45, "vol_edge": 0.35, "neg_yield": 0.20},
            "alpha_margin":   {"neg_yield": 0.55, "stress": 0.45},
            "alpha_cyclical": {"risk_on": 0.55, "vol_edge": 0.25, "weak_usd": 0.20},
            "alpha_yield":    {"neg_yield": 0.70, "risk_on": 0.15},
            "alpha_delta":    {"risk_on": 0.50, "weak_usd": 0.30, "vol_edge": 0.20},
        }
        cfg = cfg if cfg is not None else self.config
        try:
            der = (cfg or {}).get("archetype_factory", {}).get("regime_derivation", {})
            der = der if isinstance(der, dict) else {}
        except Exception:
            der = {}

        def num(key: str, nonzero: bool = False) -> float:
            """Config value for `key`, else the in-code default; guarded finite (and nonzero
            for denominators)."""
            try:
                v = der.get(key, None)
                v = float(v) if v is not None else float(D[key])
                if v != v:                              # NaN guard
                    v = float(D[key])
            except (TypeError, ValueError):
                v = float(D[key])
            return float(D[key]) if (nonzero and v == 0.0) else v

        def wmap(key: str) -> dict:
            w = der.get(key, None)
            return w if isinstance(w, dict) else D[key]

        mri_pivot = num("mri_pivot", nonzero=True)
        ny_be     = num("neg_yield_breakeven")
        ny_scale  = num("neg_yield_scale", nonzero=True)
        vol_pivot = num("vol_pivot", nonzero=True)
        dxy_scale = num("dxy_scale", nonzero=True)

        signals = {
            "risk_on":   c((mri_pivot - mri_score) / mri_pivot),     # >0 risk-on (low MRI), <0 stress
            "neg_yield": c((ny_be - real_yield) / ny_scale),         # >0 when real yields are low/negative
            "vol_edge":  c(((silver_vol or vol_pivot) - vol_pivot) / vol_pivot),  # >0 elevated silver vol
            "weak_usd":  c(-(dxy_mom or 0.0) / dxy_scale),           # >0 when the dollar is rolling over
        }
        signals["stress"] = max(0.0, -signals["risk_on"])           # only the stress side

        def alpha(key: str) -> float:
            w = wmap(key)
            total = 0.0
            for sig, val in signals.items():
                try:
                    total += float(w.get(sig, 0.0)) * val
                except (TypeError, ValueError):
                    continue
            return c(total)

        return (alpha("alpha_option"), alpha("alpha_margin"), alpha("alpha_cyclical"),
                alpha("alpha_yield"), alpha("alpha_delta"))

    # ---- commodity-aware tailwind plumbing (gold ≠ silver ≠ uranium; royalties share the lean) ----
    def _name_commodity(self, tkr: str) -> str:
        """The underlying metal for a name (drives its commodity tailwind). Spear = silver;
        ballast from the (now-corrected) config tags."""
        if tkr == "AGA.V":
            return "silver"
        return (self.config.get("ballast_valuation", {}).get(tkr, {}) or {}).get("commodity", "silver")

    def _uranium_mom(self):
        """Uranium momentum (its own regime signal), fetched once and cached ~6h. Defensive."""
        if getattr(self, "_uranium_mom_ts", 0) and (time.time() - self._uranium_mom_ts) < 21600:
            return getattr(self, "_uranium_mom_val", None)
        self._uranium_mom_ts = time.time()
        self._uranium_mom_val = None
        try:
            import market_data
            if getattr(self, "_md", None) is None:
                self._md = market_data.MarketData(fmp=getattr(self, "fmp", None))
            um = self._md.uranium_momentum()
            self._uranium_mom_val = (um or {}).get("value")
        except Exception:
            pass
        return self._uranium_mom_val

    def _commodity_regime_lean(self, commodity: str):
        """Commodity-specific regime lean ∈ [-1,1] from the live macro signals. None on failure
        (the rating then falls back to the archetype+MRI blend — never a fabricated tailwind)."""
        try:
            import commodity_regime
            m = self.terminal_state.get("metrics", {}) or {}

            def mv(*keys, default=None):
                for k in keys:
                    v = m.get(k)
                    v = v.get("value") if isinstance(v, dict) else v
                    if v is not None:
                        return v
                return default
            tape = self.terminal_state.get("macro_tape", {}) or {}
            on, off = tape.get("risk_on_count", 0), tape.get("risk_off_count", 0)
            risk_on = ((on - off) / max(1, on + off)) if (on or off) else 0.0
            signals = {
                "real_yield": mv("REAL_YIELD", "Real_Yield", default=2.0),
                "dxy_mom": mv("DXY_MOMENTUM", default=0.0),
                "gsr": mv("GSR", default=80.0),
                "risk_on": risk_on,
                "uranium_mom": self._uranium_mom() or 0.0,
            }
            return commodity_regime.compute(commodity, **signals)
        except Exception:
            return None

    def _research_book_floor(self, tkr: str):
        """Real book-value/share floor (CAD) for a ballast name from the sourced research cache —
        replaces the 10%×reference placeholder. None when unsourced (engine keeps its own floor)."""
        try:
            import research_cache
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            bv = self._rc.value(tkr, "book_value_per_share")
            if bv is None:
                return None
            fx = 1.0
            if str(self._rc.value(tkr, "currency") or "CAD").upper() == "USD":
                try:
                    import market_data
                    if getattr(self, "_md", None) is None:
                        self._md = market_data.MarketData(fmp=getattr(self, "fmp", None))
                    fx = (self._md.yahoo_quote("USDCAD=X") or {}).get("price") or 1.39
                except Exception:
                    fx = 1.39
            return float(bv) * float(fx)
        except Exception:
            return None

    def _live_spots_usd(self) -> dict:
        """The live USD spots the engine already fetches, keyed for nav_mark's two-tier resolve
        (gold GC=F · silver SI=F · copper HG=F). Uranium has no live feed — it stays stamped."""
        prices = (self.state_cache.get("prices") or {}) if isinstance(
            getattr(self, "state_cache", None), dict) else {}
        return {"gold": prices.get("GC=F"), "silver": prices.get("SI=F"),
                "copper": prices.get("HG=F")}

    def _research_book_native(self, tkr: str, allow_book: bool = True):
        """Sourced book/NAV per share in the name's NATIVE currency (no FX) + its currency, from the
        research cache. Preference order (V1 mark-NAV-to-spot):
          1. ``nav_inventory`` — structured inputs recomputed LIVE each cycle (inventory × spot ×
             FX, carrying as the NRV floor; nav_mark.py). Quality/staleness stashed in
             ``self._nav_quality[tkr]`` for the ribbon + Story Card.
          2. ``nav_adj_per_share`` — the static hand-stamped mark (the dark-ship fallback).
          3. ``book_value_per_share`` — raw accounting book (only when ``allow_book`` is True).
        ``allow_book=False`` returns None unless a GENUINE NAV mark (tier 1/2) exists — callers that
        need a fair-value anchor use this, because raw accounting book systematically understates NAV
        for holdco/royalty/physical structures and would inject false downside. None when unsourced."""
        try:
            import research_cache
            if getattr(self, "_rc", None) is None:
                self._rc = research_cache.ResearchCache()
            if not hasattr(self, "_nav_quality"):
                self._nav_quality = {}
            ccy = str(self._rc.value(tkr, "currency") or "CAD").upper()
            # 1) live compute from structured inventory (ships dark behind the static fallback)
            inv = self._rc.value(tkr, "nav_inventory")
            if isinstance(inv, dict):
                try:
                    import nav_mark
                    fx = self.state_cache.get("usd_to_cad") if isinstance(
                        getattr(self, "state_cache", None), dict) else None
                    mark = nav_mark.nav_from_inventory(inv, live_spots=self._live_spots_usd(),
                                                       usd_to_cad=fx or 1.38)
                    if mark and mark.get("nav_per_share") and mark["nav_per_share"] > 0:
                        self._nav_quality[tkr] = mark
                        return float(mark["nav_per_share"]), ccy
                except Exception as e:
                    logging.warning("[NAV-mark] %s live compute failed (falling back to static): %s",
                                    tkr, e)
            # 2) static spot-adjusted NAV — accounting book understates NAV for names that carry
            #    physical inventory at cost (e.g. URC.TO uranium holdings).
            nav_adj = self._rc.value(tkr, "nav_adj_per_share")
            if nav_adj is not None and float(nav_adj) > 0:
                self._nav_quality.pop(tkr, None)            # static mark: no live-quality claim
                return float(nav_adj), ccy
            bv = self._rc.value(tkr, "book_value_per_share")
            if bv is None or not allow_book:
                return None
            return float(bv), ccy
        except Exception:
            return None

    def _ingestion_overlay_data(self) -> dict:
        """Phase 6: load ``data/ingestion_cache.json`` once, memoized by file mtime.
        Returns the cached ``{'macro': ..., 'tickers': ...}`` dict, or ``{}`` when the
        cache is absent (the normal pre-ingestion state) or unreadable. Never raises, so
        the orchestrator can never be brought down by the ingestion layer."""
        if load_ingestion_cache is None:
            return {}
        path = "data/ingestion_cache.json"
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return {}                                      # no cache yet -> silent no-op
        if getattr(self, "_ingestion_mtime", None) == mtime:
            return self._ingestion_overlay_cached
        env = load_ingestion_cache(path)
        data = env.get("data", {}) if isinstance(env, dict) else {}
        self._ingestion_mtime = mtime
        self._ingestion_overlay_cached = data or {}
        if data:
            logging.info("[Ingestion] overlay loaded from %s (%d tickers; macro: %s)",
                         path, len(data.get("tickers", {})), ",".join(sorted(data.get("macro", {}))))
        else:
            logging.warning("[Ingestion] cache present but empty/unreadable: %s", path)
        return self._ingestion_overlay_cached

    def _apply_ingestion_overlay(self, ticker: str, payload: dict) -> None:
        """Overlay cached open-source ingestion data onto a live-built payload. Live
        worker feeds take precedence; the cache only fills gaps. Fully graceful — an
        absent/stale cache is a no-op, so the legacy path is byte-for-byte unchanged
        when no ingestion cache is present."""
        data = self._ingestion_overlay_data()
        if not data:
            return
        macro = payload.setdefault("macro", {})
        for key, value in (data.get("macro") or {}).items():
            if macro.get(key) is None:
                macro[key] = value
        tov = (data.get("tickers") or {}).get(ticker) or {}
        for section in ("financials", "comps", "conviction_signals"):
            src = tov.get(section)
            if not src:
                continue
            dst = payload.get(section)
            if not isinstance(dst, dict):
                dst = {}
                payload[section] = dst
            for key, value in src.items():
                if dst.get(key) is None:
                    dst[key] = value
        if payload.get("shares_out") is None and tov.get("shares_out") is not None:
            payload["shares_out"] = tov["shares_out"]

    def _ingestion_status(self) -> dict:
        """Phase 6c: summarize the open-source ingestion cache (data/ingestion_cache.json)
        for the cockpit — availability, per-source freshness, and overlay coverage. Purely
        additive and read-only; returns a small JSON-safe dict and never raises."""
        if load_ingestion_cache is None:
            return {"available": False, "reason": "module_absent"}
        env = load_ingestion_cache("data/ingestion_cache.json")
        if not isinstance(env, dict):
            return {"available": False, "reason": "no_cache"}
        now = time.time()
        generated_at = env.get("generated_at")
        age = max(0.0, now - generated_at) if generated_at else None
        ttl = env.get("ttl_seconds")
        stale = bool(age is not None and ttl and age > ttl)
        cache_data = env.get("data") if isinstance(env.get("data"), dict) else {}
        sources = {}
        for name, meta in (env.get("sources") or {}).items():
            meta = meta if isinstance(meta, dict) else {}
            fetched_at = meta.get("fetched_at")
            sources[name] = {
                "status": meta.get("status", "unknown"),
                "age_minutes": round((now - fetched_at) / 60.0, 1) if fetched_at else None,
            }
        return {
            "available": True,
            "schema_version": env.get("schema_version"),
            "generated_at": generated_at,
            "age_minutes": round(age / 60.0, 1) if age is not None else None,
            "ttl_seconds": ttl,
            "stale": stale,
            "sources": sources,
            "ticker_count": len(cache_data.get("tickers", {})),
            "macro_keys": sorted(cache_data.get("macro", {})),
        }

    def _archetype_payload(self, ticker: str, cfg: dict, prices: dict, macro: dict,
                           dynamic_aisc: float, mean_peer_ev: float, forensic_metrics: dict) -> dict:
        """Assemble the per-ticker ``data_payload`` for the archetype factory from live state.
        Ballast names read ref_price / spot_ref / currency from config automatically, so their
        market & cost legs are fully live; income-leg inputs not present in the live feed
        (royalty cash flow, mine production) simply degrade out of the confidence-tilted blend."""
        bv = cfg.get("ballast_valuation", {}).get(ticker, {})
        fin = dict(forensic_metrics.get(ticker, {}))
        pmeta = cfg.get("portfolio_metadata", {}).get(ticker, {}) if isinstance(
            cfg.get("portfolio_metadata"), dict) else {}
        payload: dict = {
            "currency": bv.get("currency", "CAD"),
            "price": prices.get(ticker),
            "macro": dict(macro),
            "comps": {},
            "financials": fin,
            # 3rd taxonomy axis (display/correlation only; valuation unchanged): the sub-archetype
            # overlay + orthogonal sector tags, surfaced through the valuation summary.
            "subarchetype": pmeta.get("subarchetype"),
            "sector_tags": pmeta.get("sector_tags", []),
        }
        # Surface the ballast anchors so the archetype's market leg sees the SAME spot_ref it scales
        # against (_commodity_spot returns spot_ref for non-silver -> an exact neutral 1.0 factor;
        # absent these it would fall back to live silver spot and mis-scale the gold/uranium names).
        if bv:
            if bv.get("spot_ref") is not None:
                payload["spot_ref"] = bv.get("spot_ref")
            if bv.get("commodity"):
                payload["commodity"] = bv.get("commodity")
            # NO-HARDCODE: drive the intrinsic off the SOURCED NAV per share when we have it.
            # _research_book_native prefers nav_adj_per_share (spot-adjusted NAV) over the raw
            # accounting book_value_per_share, so names like URC.TO whose IFRS book understates NAV
            # (uranium at cost/NRV, not spot) get a market-leg anchor that reflects true NAV.
            #
            # Separation of concerns: book_value_per_share → cost leg (the thin asset-light floor);
            # nav_adj_per_share (or falling back to config ref_price) → ref_price market leg anchor.
            # The two can legitimately diverge — carrying-value book IS the floor, but the market
            # leg should reflect economic NAV (spot-marked inventory + royalty NPV), not IFRS cost.
            nat = self._research_book_native(ticker)
            if nat is not None:
                bv_native, bv_ccy = nat
                if _is_pos(bv_native):
                    payload["book_value_per_share"] = bv_native      # cost leg: accounting floor
                    payload["ref_price"] = bv_native                 # market-leg NAV anchor (sourced)
                    payload["currency"] = bv_ccy
            # If only raw book_value_per_share is available (no nav_adj), also set it on the cost
            # leg but do NOT override ref_price — the config ref_price is a better market anchor
            # than an understated accounting book (relevant for URC.TO before nav_adj is sourced).
            else:
                try:
                    import research_cache
                    if getattr(self, "_rc", None) is None:
                        self._rc = research_cache.ResearchCache()
                    raw_bv = self._rc.value(ticker, "book_value_per_share")
                    if raw_bv is not None and float(raw_bv) > 0:
                        bv_ccy = str(self._rc.value(ticker, "currency") or "CAD").upper()
                        payload["book_value_per_share"] = float(raw_bv)  # cost floor only
                        payload["currency"] = bv_ccy
                        # ref_price intentionally NOT overridden — config value is the NAV anchor
                except Exception:
                    pass
        if ticker == "AGA.V":
            # the Option-Convexity spear: live peer comp + dynamic AISC, plus a best-effort
            # explorer forensic feed (treasury & burn from config, dilution from the live feed)
            payload["shares_out"] = cfg.get("aga_shares_out")
            payload["aisc"] = dynamic_aisc
            payload["currency"] = "CAD"
            payload["comps"] = {"peer_ev_oz": mean_peer_ev}
            fin.setdefault("cash", cfg.get("rep_floor_params", {}).get("cash_treasury_m", 0.0) * 1e6)
            fin.setdefault("monthly_burn", cfg.get("cash_burn", {}).get("monthly_burn_rate"))
            if "sga_t0" in fin:
                fin.setdefault("sga_expense", fin["sga_t0"])
        self._apply_ingestion_overlay(ticker, payload)
        return payload

    def _register_eval_names(self, cfg: dict, router) -> None:
        """Hot-register newly promoted EVAL names (``portfolio_metadata[t].eval_only``) onto the
        archetype router so a promotion rates on the NEXT engine cycle — no restart. Mirrors
        build_default_router's routing precedence (explicit archetype, else the type map); an
        unknown archetype is skipped explicitly, never guessed. Idempotent and non-fatal."""
        try:
            from archetypes import ARCHETYPE_BY_TYPE, ARCHETYPE_REGISTRY
            known = set(router.registered_tickers())
            routing = {**ARCHETYPE_BY_TYPE, **(cfg.get("archetype_routing") or {})}
            for tkr in eval_only_tickers(cfg):
                if tkr in known:
                    continue
                meta = (cfg.get("portfolio_metadata") or {}).get(tkr) or {}
                name = meta.get("archetype") or routing.get(str(meta.get("type", "")).lower())
                cls = ARCHETYPE_REGISTRY.get(name) if isinstance(name, str) else None
                if cls is None:
                    logging.warning("eval name %s skipped: unknown archetype %r", tkr, name)
                    continue
                router.register_asset(tkr, cls(tkr, cfg, fx_rates=getattr(router, "fx_rates", None)),
                                      label=f"{meta.get('type', '?')}/{meta.get('stage', '?')} [eval]")
                logging.info("eval name %s hot-registered (archetype %s)", tkr, name)
        except Exception as e:                            # supplementary; never crashes the loop
            logging.warning("eval-name registration skipped (non-fatal): %s", e)

    def _compute_archetype_valuations(self, *, cfg: dict, prices: dict, spot_ag: float,
                                      gold: float, real_yield: float, silver_vol: float,
                                      dynamic_aisc: float, capital_discount_factor: float,
                                      mean_peer_ev: float, usd_to_cad: float, mri_score: float,
                                      dxy_mom: float, forensic_metrics: dict) -> dict:
        """Value every registered portfolio name through the Polymorphic Archetype Factory,
        in PARALLEL with the legacy valuation. Pure supplement — a per-ticker failure
        (incl. TickerNotRegisteredError) is captured per name and never propagates, so the
        main loop cannot crash. Returns the dict stored at
        ``terminal_state['archetype_valuation_detail']``."""
        router = self.archetype_router
        if router is None:
            return {"status": "unavailable", "results": {}}
        self._register_eval_names(cfg, router)

        regime_vector = self._build_regime_impact_vector(mri_score, real_yield, silver_vol, dxy_mom, cfg=cfg)
        macro = {"spot_ag": spot_ag, "gold": gold, "real_yield": real_yield,
                 "silver_vol": silver_vol, "capital_discount": capital_discount_factor,
                 "y30": self.state_cache.get("y30")}
        weights = {k: v for k, v in cfg.get("archetype_barbell_weights",
                   {"AGA.V": 0.60, "URC.TO": 0.15, "GROY": 0.15, "GMX.TO": 0.10}).items()
                   if not str(k).startswith("_")}

        results: dict = {}
        book_cad = 0.0
        for ticker in router.registered_tickers():
            try:
                # Push the LIVE USD->CAD rate onto the registered instance (the router was built
                # at init from a config snapshot) so USD names (GROY) normalize to CAD correctly.
                router.resolve(ticker).fx_rates["USD"] = usd_to_cad
                payload = self._archetype_payload(ticker, cfg, prices, macro, dynamic_aisc,
                                                  mean_peer_ev, forensic_metrics)
                summary = router.get_valuation(ticker, payload, regime_vector)
                results[ticker] = summary
                book_cad += weights.get(ticker, 0.0) * summary.get("intrinsic_after_forensic", 0.0)
            except TickerNotRegisteredError as e:
                results[ticker] = {"status": "not_registered", "error": str(e)}
            except Exception as e:                       # supplementary block must never crash the loop
                logging.warning("Phase 5b archetype valuation failed for %s (non-fatal): %s", ticker, e)
                results[ticker] = {"status": "error", "error": str(e)}

        # Stash the live inputs so on-demand what-if (run_whatif / POST /action/whatif) can
        # revalue any name against the very same base the dashboard is showing.
        self._whatif_base = {
            "macro": dict(macro), "regime_vector": list(regime_vector),
            "prices": dict(prices), "forensic_metrics": forensic_metrics,
            "dynamic_aisc": dynamic_aisc, "mean_peer_ev": mean_peer_ev,
            "usd_to_cad": usd_to_cad, "mri": mri_score, "real_yield": real_yield,
            "silver_vol": silver_vol, "dxy_mom": dxy_mom,
        }
        return {
            "status": "live",
            "regime_impact_vector": {name: round(v, 4) for name, v in zip(REGIME_ORDER, regime_vector)},
            "results": results,
            "barbell": {"weights": weights, "blended_intrinsic_cad": round(book_cad, 4)},
            "correlation_groups": router.correlation_groups(),
        }

    def run_whatif(self, ticker, overrides):
        """On-demand scenario revaluation (Iteration 2 action spine). Re-runs the archetype
        valuation for one name against the LAST live inputs with macro/peer/regime overrides and
        diffs base vs scenario. Backs POST /action/whatif and the run_valuation_whatif MCP tool, so
        a GUI button, the /whatif cockpit command and the agents all share one implementation."""
        from valuation_actions import (parse_overrides, parse_override, summarize_delta,
                                       REGIME_KEYS, MACRO_KEYS)
        router = self.archetype_router
        base = getattr(self, "_whatif_base", None)
        if router is None or base is None:
            return {"error": "engine warming up — no base valuation yet; retry shortly"}
        ticker = ticker or self.ui.focused_ticker          # default to whatever the GUI is showing
        if not ticker:
            return {"error": "no ticker given and no focused ticker in the GUI"}
        try:
            router.resolve(ticker)
        except Exception:
            return {"error": f"unknown ticker {ticker!r}", "available": list(router.registered_tickers())}
        # A bare overrides string naming a saved scenario loads that scenario's knobs.
        if (isinstance(overrides, str) and overrides.strip() and "=" not in overrides
                and getattr(self, "dconfig", None) is not None):
            scen = self.dconfig.get_scenario(overrides.strip())
            if scen:
                overrides = scen
        ov = parse_overrides(overrides)
        if not ov:
            return {"error": "no recognized overrides",
                    "knobs": ["silver", "gold", "ry", "vol", "peer", "mri", "dxy"],
                    "example": "silver=+5 ry=-0.5 peer=+20%"}

        cfg = self.config
        prices = base["prices"]; macro0 = base["macro"]; fm = base["forensic_metrics"]
        aisc = base["dynamic_aisc"]; peer0 = base["mean_peer_ev"]
        try:
            router.resolve(ticker).fx_rates["USD"] = base["usd_to_cad"]
        except Exception:
            pass

        # Base (recompute for an apples-to-apples diff against the scenario).
        base_payload = self._archetype_payload(ticker, cfg, prices, macro0, aisc, peer0, fm)
        base_summary = router.get_valuation(ticker, base_payload, base["regime_vector"])

        # Scenario: apply overrides to macro / peer / regime scalars.
        applied = {}
        macro_s = dict(macro0); peer_s = peer0
        rs = {"mri": base["mri"], "real_yield": base["real_yield"],
              "silver_vol": base["silver_vol"], "dxy": base["dxy_mom"]}
        regime_dirty = False
        for k, spec in ov.items():
            try:
                if k == "peer_ev_oz":
                    peer_s = parse_override(spec, peer0)
                    applied[k] = {"from": peer0, "to": round(peer_s, 4)}
                elif k in MACRO_KEYS:
                    cur = macro0.get(k); newv = parse_override(spec, cur)
                    macro_s[k] = newv; applied[k] = {"from": cur, "to": round(newv, 4)}
                    if k in REGIME_KEYS:
                        rs[k] = newv; regime_dirty = True
                elif k in REGIME_KEYS:           # mri / dxy (not macro fields)
                    cur = rs.get(k); newv = parse_override(spec, cur)
                    rs[k] = newv; applied[k] = {"from": cur, "to": round(newv, 4)}
                    regime_dirty = True
            except ValueError as e:
                return {"error": str(e)}

        # A silver move MUST reprice an explorer whose value rides peer EV/oz. The live comps already
        # embed the current metal level, so in a hypothetical we scale peer EV/oz with the operating
        # margin (spot − industry AISC) — a convex response — unless the user set peer by hand. Uses the
        # SAME peer_ev_margin_scaled helper as the scenario tornado so the two surfaces agree. Scoped to
        # the what-if only: base valuations and ratings are untouched.
        if "spot_ag" in applied and "peer_ev_oz" not in applied and peer0:
            aisc_ref = float(cfg.get("dynamic_discovery_v5", {}).get("estimated_industry_aisc_2026", 24.5) or 24.5)
            s0 = float(macro0.get("spot_ag") or 0.0)
            s1 = float(macro_s.get("spot_ag") or 0.0)
            if abs(s1 - s0) > 1e-9:
                peer_s = self.valuation_engine.peer_ev_margin_scaled(peer0, s0, s1, aisc_ref)
                applied["peer_ev_oz"] = {"from": round(peer0, 4), "to": round(peer_s, 4),
                                         "auto": "scaled with silver margin"}

        scen_payload = self._archetype_payload(ticker, cfg, prices, macro_s, aisc, peer_s, fm)
        # Re-assert overrides so they win over any ingestion overlay applied during payload build.
        for k in MACRO_KEYS:
            if k in applied:
                scen_payload.setdefault("macro", {})[k] = macro_s[k]
        if "peer_ev_oz" in applied:
            scen_payload.setdefault("comps", {})["peer_ev_oz"] = peer_s
        scen_regime = (self._build_regime_impact_vector(rs["mri"], rs["real_yield"], rs["silver_vol"],
                       rs["dxy"], cfg=cfg) if regime_dirty else base["regime_vector"])
        scen_summary = router.get_valuation(ticker, scen_payload, scen_regime)

        # The intrinsic is CAD-normalized but the payload price is NATIVE — pass the price in the
        # intrinsic's currency (CAD) so upside = intrinsic ÷ price is a correct ratio that matches
        # the conviction view (a USD name like GROY otherwise reads ~60% upside instead of +14%).
        native_price = base_payload.get("price")
        ccy = str(base_payload.get("currency", "CAD")).upper()
        price_cad = (native_price * base["usd_to_cad"]
                     if ccy == "USD" and native_price else native_price)
        out = summarize_delta(base_summary, scen_summary, price_cad, applied)
        out["ticker"] = ticker
        out["archetype"] = scen_summary.get("archetype")
        out["display_ccy"] = "CAD"      # whatif works in the valuation (CAD) basis end-to-end
        return out

    def set_ui_state(self, state: dict) -> dict:
        """A frontend reports what it is showing (read-side of the merge). Thin orchestration over
        the engine-owned UIStateManager; agents read it via GET /ui/state / get_ui_context."""
        return {"ok": True, "ui_state": self.ui.update(state)}

    # ------------------------------------------------------------------ A1.9 snapshot publish
    def publish_state(self) -> None:
        """Atomic snapshot-swap (audit A1.9): deep-copy the working ``terminal_state`` into the
        published frame readers are served. Called at the END of every eval cycle and after each
        interactive mutation (ui_command / annotation / activity / pipeline event), so interactivity
        stays immediate while a /state or /ws read can never observe a half-updated book (e.g. new
        prices beside the prior cycle's intrinsic). Failure keeps the prior frame — readers degrade
        to slightly stale-but-complete, never torn."""
        try:
            snap = copy.deepcopy(self.terminal_state)
            with self.state_lock:
                self._published_state = snap            # one reference assignment = the swap
        except Exception as e:
            logging.warning("state publish failed (readers keep the prior complete frame): %s", e)

    @property
    def published_state(self) -> dict:
        """The frame readers consume: the last complete published snapshot, or the live dict
        before the first publish (startup parity with the pre-A1.9 behavior)."""
        return self._published_state if self._published_state is not None else self.terminal_state

    def push_ui_command(self, cmd: dict) -> dict:
        """Agents steer the frontend (write-side). The command rides the existing /ws terminal_state
        feed under 'ui_command'; the frontend acts when 'seq' increases."""
        c = cmd or {}
        try:
            command = self.ui.command(c.get("action"), c.get("args", {}))
        except ValueError as e:
            return {"error": str(e)}
        self.terminal_state["ui_command"] = command
        if command.get("action") in ("pin_insight", "highlight", "clear_insight"):
            try:
                self.record_annotation(command)
            except Exception:
                pass            # a bad annotation must never disturb the command stream
        self.publish_state()    # interactive mutation -> immediate complete frame for readers
        return {"ok": True, "command": command}

    def record_annotation(self, command: dict) -> None:
        """Agents leave visual traces on the dashboard. pin_insight = persistent badge, highlight =
        transient (TTL), clear_insight = remove. Stored per-ticker in terminal_state so the cockpit
        renders badges/notes next to names. Bounded + self-pruning of expired entries."""
        args = command.get("args", {}) or {}
        action = command.get("action")
        ticker = str(args.get("ticker") or "").strip()
        store = self.terminal_state.setdefault("agent_annotations", {})
        now = time.time()
        for k in list(store.keys()):                       # prune expired everywhere first
            store[k] = [a for a in store[k] if not a.get("ttl") or (now - a.get("ts", now)) < a["ttl"]]
            if not store[k]:
                del store[k]
        if action == "clear_insight":
            store.pop(ticker, None) if ticker else store.clear()
            return
        if not ticker:
            return
        store.setdefault(ticker, []).append({
            "ticker": ticker,
            "badge": str(args.get("badge") or ("✦" if action == "pin_insight" else "◆"))[:2],
            "reason": str(args.get("reason") or args.get("note") or "")[:500],
            "level": str(args.get("level") or "info"),     # info | good | warn | risk
            "agent": str(args.get("agent") or command.get("agent") or "agent")[:24],
            "ts": now,
            "ttl": (None if action == "pin_insight" else float(args.get("ttl", 90) or 90)),
            "seq": command.get("seq"),
        })
        del store[ticker][:-5]                             # cap 5 per name

    def record_agent_activity(self, ev: dict) -> dict:
        """Ambient agent-activity bus. Claude Code hooks (and agents directly) POST what they are
        doing — prompt / tool / response / note / proposal — and it rides terminal_state under
        'agent_activity' so the cockpit streams the agents working without anyone calling a steer
        tool. Bounded ring buffer; never raises (a bad event must not disturb the eval loop)."""
        e = ev or {}
        self._agent_seq += 1
        entry = {
            "seq": self._agent_seq,
            "ts": time.time(),
            "agent": str(e.get("agent", "agent"))[:24],
            "kind": str(e.get("kind", "note"))[:16],
            "summary": " ".join(str(e.get("summary", "")).split())[:200],
            "ticker": (str(e.get("ticker"))[:12] if e.get("ticker") else None),
        }
        buf = self.terminal_state.setdefault("agent_activity", [])
        buf.append(entry)
        del buf[:-40]                 # keep only the most recent 40
        if e.get("text"):             # a full reply (Stop hook) -> the cockpit's prompt-output panel
            self.terminal_state["agent_reply"] = {
                "text": str(e.get("text"))[:6000],
                "agent": entry["agent"],
                "ts": entry["ts"],
            }
        self.publish_state()          # interactive mutation -> immediate complete frame
        return {"ok": True, "seq": entry["seq"]}

    def record_pipeline_event(self, ev: dict) -> dict:
        """Live status for a backgrounded research pipeline (scout→synthesis→verifier) so the cockpit
        shows progress while the user keeps chatting. The runner posts start/done; the headless agent
        posts stage transitions + per-name verdicts. Bounded; never raises."""
        e = ev or {}
        now = time.time()
        p = self.terminal_state.setdefault(
            "pipeline", {"status": "idle", "theme": None, "stage": None, "started": None,
                         "updated": None, "events": [], "result": None, "verdicts": {}})
        status = str(e.get("status") or p.get("status") or "running")[:16]
        stage = e.get("stage")
        msg = " ".join(str(e.get("message", "")).split())[:200]
        if status == "running" and (p.get("status") in (None, "idle", "done", "error") and not p.get("started")):
            p.update({"started": now, "events": [], "result": None, "verdicts": {}})
        if e.get("theme"):
            p["theme"] = str(e.get("theme"))[:80]
        if stage:
            p["stage"] = str(stage)[:24]
        p["status"] = status
        p["updated"] = now
        if e.get("ticker") and (e.get("verdict") or e.get("message")):
            tk = str(e["ticker"])[:12]
            cur = p.setdefault("verdicts", {}).get(tk)
            cur = dict(cur) if isinstance(cur, dict) else ({"verdict": str(cur)} if cur else {})
            if e.get("verdict"):
                cur["verdict"] = str(e["verdict"])[:16]
            if e.get("message"):
                cur["note"] = str(e["message"])[:240]
            p["verdicts"][tk] = cur
        if e.get("result"):
            p["result"] = str(e.get("result"))[:4000]
        if stage or msg:
            p.setdefault("events", []).append(
                {"ts": now, "stage": p.get("stage"), "status": status, "message": msg})
            del p["events"][:-30]
        self.publish_state()          # interactive mutation -> immediate complete frame
        return {"ok": True, "status": p["status"], "stage": p.get("stage")}

    # ---- research dossiers / decision memos (read-only; engine owns the file I/O) -------
    def list_decisions(self, limit: int = 50) -> dict:
        """Index the research dossiers under ``data/decisions/*.md`` (newest first) so the cockpit
        Dossier tab is a real research surface, not a placeholder. The cockpit stays a thin consumer:
        all file I/O and ticker inference live here. Agents write these via the /dossier skill."""
        import glob
        try:
            os.makedirs(DECISIONS_DIR, exist_ok=True)
        except OSError:
            pass
        items = []
        for path in glob.glob(os.path.join(DECISIONS_DIR, "*.md")):
            try:
                st = os.stat(path)
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(4000)
            except OSError:
                continue
            name = os.path.basename(path)
            title = next((ln.lstrip("# ").strip() for ln in head.splitlines() if ln.strip()), name)
            items.append({
                "name": name,
                "ticker": self._guess_decision_ticker(name, head),
                "title": title[:120],
                "mtime": st.st_mtime,
                "age_minutes": round((time.time() - st.st_mtime) / 60.0, 1),
                "size": st.st_size,
                "preview": " ".join(head.split())[:240],
            })
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return {"dir": DECISIONS_DIR, "count": len(items), "decisions": items[: max(1, int(limit))]}

    def read_decision(self, name: str) -> dict:
        """Return one dossier's markdown body. Path-traversal-guarded to ``data/decisions/``."""
        if not name or not str(name).endswith(".md"):
            return {"error": "name must be a .md file in the decisions dir"}
        base = os.path.abspath(DECISIONS_DIR)
        target = os.path.abspath(os.path.join(base, os.path.basename(str(name))))
        if os.path.dirname(target) != base or not os.path.isfile(target):
            return {"error": f"no such decision {name!r}"}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                return {"name": os.path.basename(target), "markdown": f.read(200_000)}
        except OSError as e:
            return {"error": str(e)}

    def delete_decision(self, name: str) -> dict:
        """Delete one dossier by file name. Path-traversal-guarded to ``data/decisions/``."""
        if not name or not str(name).endswith(".md"):
            return {"error": "name must be a .md file in the decisions dir"}
        base = os.path.abspath(DECISIONS_DIR)
        target = os.path.abspath(os.path.join(base, os.path.basename(str(name))))
        if os.path.dirname(target) != base or not os.path.isfile(target):
            return {"error": f"no such decision {name!r}"}
        try:
            os.remove(target)
            return {"ok": True, "deleted": os.path.basename(target)}
        except OSError as e:
            return {"error": str(e)}

    @staticmethod
    def _guess_decision_ticker(name: str, head: str):
        """Best-effort ticker tag for a dossier from its filename / first lines (book names first)."""
        blob = (name + " " + head).upper()
        for t in ("AGA.V", "GMX.TO", "URC.TO", "GROY"):
            if t in blob:
                return t
        return os.path.splitext(name)[0].split("_")[0].split("-")[0].upper() or None

    @staticmethod
    def _spear_quality_inputs(cfg: dict) -> dict:
        """Derive the spear's junior-miner quality lenses (ounce-weighted head grade, total
        contained AgEq ounces, ounce-weighted blended Ag+Au recovery) from the config resource
        model, for the Conviction Mode Q pillar. Graceful: missing data simply drops a lens."""
        buckets = cfg.get("project_buckets_oz_AgEq", {}) or {}
        projects = (cfg.get("technical_quality", {}) or {}).get("projects", {}) or {}
        out: dict = {}
        total_oz = sum(float(v) for v in buckets.values() if _is_pos(v))
        if total_oz > 0:
            out["resource_oz"] = total_oz
            g_num = r_num = 0.0
            for name, oz in buckets.items():
                if not _is_pos(oz):
                    continue
                p = projects.get(name, {}) if isinstance(projects.get(name), dict) else {}
                if _is_pos(p.get("grade_gpt_ageq")):
                    g_num += float(oz) * float(p["grade_gpt_ageq"])
                ag_s, au_s = p.get("ageq_share_ag"), p.get("ageq_share_au")
                ag_r, au_r = p.get("rec_ag"), p.get("rec_au")
                if all(_is_pos(x) or x == 0 for x in (ag_s, au_s, ag_r, au_r)) and (ag_s is not None):
                    r_num += float(oz) * (float(ag_s) * float(ag_r) + float(au_s) * float(au_r))
            if g_num > 0:
                out["grade_gpt"] = round(g_num / total_oz, 1)
            if r_num > 0:
                out["recovery"] = round(r_num / total_oz, 4)
        return out

    def _maybe_refresh_live_catalysts(self, cfg: dict, cat_cfg: dict, path: str) -> None:
        """PHASE 8 (debug fix): run the configured live providers (EDGAR / RSS / manual CSV) and
        rewrite the canonical feed file, but only when it is older than ``live_refresh_seconds`` so
        the eval loop never hammers the feeds. Fully robust: any failure logs and leaves the existing
        feed in place (we then serve whatever is on disk). Logs which providers succeeded/failed."""
        if refresh_catalyst_feed is None:
            logging.warning("Phase 8 live feeds requested but refresh_catalyst_feed is unavailable; "
                            "serving cached feed at %s", path)
            return
        ttl = float(cat_cfg.get("live_refresh_seconds", cat_cfg.get("ttl_seconds", 86400)) or 0.0)
        now = time.time()
        # In-process throttle (don't re-refresh every basket/eval cycle within one run).
        last = getattr(self, "_catalyst_live_refresh_ts", 0.0)
        if last and ttl and (now - last) < ttl:
            return
        # On-disk freshness: if the feed file was generated within the TTL, skip the network too.
        if ttl and os.path.exists(path):
            try:
                with open(path, "r") as fh:
                    gen = json.load(fh).get("generated_at")
                if gen:
                    import datetime as _dt
                    gen_ts = _dt.datetime.fromisoformat(str(gen).replace("Z", "")).timestamp()
                    if (now - gen_ts) < ttl:
                        self._catalyst_live_refresh_ts = now
                        return
            except (OSError, ValueError, json.JSONDecodeError):
                pass  # unreadable/corrupt -> fall through and refresh
        try:
            res = refresh_catalyst_feed(cfg, path=path)
            self._catalyst_live_refresh_ts = now
            logging.info("Phase 8 live catalyst refresh: status=%s providers=%s count=%s",
                         res.get("status"), res.get("providers"), res.get("count"))
        except Exception as e:                          # never let a feed problem break the eval loop
            self._catalyst_live_refresh_ts = now
            logging.warning("Phase 8 live catalyst refresh failed (serving cached feed at %s): %s",
                            path, e)

    def _catalyst_feed(self, cfg: dict) -> dict:
        """PHASE 8 (additive): serve the catalyst feed, memoized by file mtime so the eval loop does
        not re-read the file every cycle. Graceful: returns an empty feed on any problem.

        ``catalysts.use_live_feeds`` controls sourcing:
          * true  -> refresh the feed from the configured live providers (EDGAR/RSS/manual CSV) on a
                     TTL, then serve the rewritten file.
          * false -> serve EMPTY (the explicit fallback) so a stale checked-in file is never
                     presented as if it were live. Set ``serve_seed_when_disabled: true`` to instead
                     serve the on-disk seed for an offline demo."""
        if load_catalyst_feed is None:
            return {"status": "unavailable", "events": []}
        cat_cfg = cfg.get("catalysts", {}) if isinstance(cfg.get("catalysts"), dict) else {}
        if cat_cfg.get("enabled", True) is False:
            return {"status": "disabled", "events": []}
        path = cat_cfg.get("feed_path", "data/catalysts.json")
        use_live = bool(cat_cfg.get("use_live_feeds", False))
        if use_live:
            self._maybe_refresh_live_catalysts(cfg, cat_cfg, path)
        elif not cat_cfg.get("serve_seed_when_disabled", False):
            return {"status": "live_disabled", "events": [],
                    "reason": "catalysts.use_live_feeds is false (fallback: empty)"}
        try:
            mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
        except OSError:
            mtime = 0.0
        cache = getattr(self, "_catalyst_cache", None)
        if cache and cache.get("path") == path and cache.get("mtime") == mtime:
            return cache["feed"]
        feed = load_catalyst_feed(path)                  # events are historical -> use even if stale
        self._catalyst_cache = {"path": path, "mtime": mtime, "feed": feed}
        return feed

    def _regime_posture(self, mri_score: float) -> dict:
        """Forge Phase 3: the book-level regime posture (stance + size cap) from the live regime —
        the Druckenmiller master risk dial. Reads MRI + net_tilt + real_yield + DXY momentum from
        terminal_state and routes through the pure regime_posture module. Defensive: any problem ->
        a neutral BALANCED / 1.0x posture, never raises."""
        try:
            import regime_posture
            metrics = self.terminal_state.get("metrics", {}) or {}
            def _mv(*keys, default=None):
                for k in keys:
                    v = metrics.get(k)
                    if isinstance(v, dict):
                        v = v.get("value")
                    if v is not None:
                        return v
                return default
            tape = self.terminal_state.get("macro_tape", {}) or {}
            return regime_posture.compute(
                mri=mri_score,
                net_tilt=tape.get("net_tilt"),
                real_yield=_mv("REAL_YIELD", "Real_Yield", default=None),
                dxy_mom=_mv("DXY_MOMENTUM", default=None))
        except Exception:
            return {"code": "balanced", "label": "BALANCED", "cap": 1.0, "headwind": False,
                    "drivers": [], "rationale": "posture unavailable"}

    def _emit_cockpit_events(self) -> None:
        """Forge nervous system #1: turn this cycle's meaningful state deltas into semantic events.
        Every event rides the ephemeral desk-tape bus (/agent/activity); only the signal-worthy ones
        (posture flips, JSF trips) are persisted to the immutable Living Memory audit record — so the
        track record stays clean while the nervous system stays live. Never raises."""
        import cockpit_events
        curr = cockpit_events.snapshot(self.terminal_state)
        prev = getattr(self, "_event_prev", None)
        # Don't let a DEGENERATE cycle (conviction block errored -> no baskets -> empty gates)
        # become the baseline: it would make the next good cycle re-fire every still-applied gate
        # as a fresh "trip". Keep the last good snapshot as prev until real gates return.
        if curr.get("gates"):
            self._event_prev = curr
        events = cockpit_events.detect_events(prev or {}, curr)
        if not events:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code"),
                  "net_tilt": (self.terminal_state.get("macro_tape") or {}).get("net_tilt")}
        lm = None
        for e in events:
            try:                                          # ephemeral bus -> the desk tape
                self.record_agent_activity({"agent": "engine", "kind": e["kind"],
                                            "summary": e["summary"], "ticker": e.get("ticker")})
            except Exception:
                pass
            if not e.get("persist"):
                continue
            try:                                          # signal-worthy -> the audit record
                if lm is None:
                    import living_memory
                    lm = getattr(self, "_lm", None) or living_memory.LivingMemory()
                    self._lm = lm
                mtype = "regime_snapshot" if e["kind"] == "posture" else "note"
                lm.write(mtype, text=e["summary"], ticker=e.get("ticker"), regime=regime,
                         source="engine", tags=[e["kind"], "event"])
            except Exception:
                pass

        # Forge nervous system #5: reactive triggers — the desk talks back. DECISION-SUPPORT ONLY
        # (pin/highlight, never a book action); rate-limited via the cooldown ledger; loop-safe
        # (annotations are not state events, so they can't re-trigger). Defensive.
        try:
            import cockpit_triggers
            fired = getattr(self, "_trigger_fired", {})
            annos = self.terminal_state.setdefault("agent_annotations", {})
            badges = {"warn": "▲", "risk": "⚠", "good": "◆", "info": "●"}
            for a in cockpit_triggers.evaluate(events, fired=fired):
                slot = annos.setdefault(a.get("ticker") or "_book", [])
                slot.append({"badge": badges.get(a["level"], "✦"), "level": a["level"],
                             "reason": a["text"][:60], "agent": "desk"})
                del slot[:-3]
                fired[a["key"]] = time.time()
            self._trigger_fired = fired
        except Exception:
            pass

    def _turn_calibration_flywheel(self, *, horizon_days: int = 90, interval_s: int = 3600) -> None:
        """H3 capture loop, turned deterministically (the 'close the loop' fix). Once per ``interval_s``:
        freeze a gradeable DECISION for every held name that lacks an open one, and CLOSE open decisions
        at their horizon (or on a stance change) at the live mark — writing the same ``decision`` /
        ``outcome`` Living-Memory schema the MCP capture tools use, so both paths feed one shared ledger
        the scorecard and the agent prior already read. The decision logic is the pure, tested
        ``calibration.plan_flywheel_actions``; this method is just the engine-side I/O. Never raises."""
        import calibration
        now = time.time()
        if now - getattr(self, "_flywheel_ts", 0.0) < max(60, int(interval_s)):
            return
        conv = self.terminal_state.get("conviction_mode") or {}
        baskets = conv.get("baskets") or []
        if not baskets:
            return                                          # nothing rated yet — don't prime on an empty book
        # lazily bind the shared Living-Memory handle (same store the events path uses)
        lm = getattr(self, "_lm", None)
        if lm is None:
            import living_memory
            lm = living_memory.LivingMemory()
            self._lm = lm

        # Shape each HELD basket the way decision_from_rating expects (ladder + asymmetry{rho,φ} + gate),
        # exactly as get_conviction_ratings does — eval-only names are rated, NOT held, so they get no
        # decision; unpriced names (feed miss) are skipped until a mark returns.
        shaped = []
        for b in baskets:
            if b.get("eval_only") or not _is_pos((b.get("ladder") or {}).get("price")):
                continue
            V = (b.get("pillars") or {}).get("V", {}) if isinstance(b.get("pillars"), dict) else {}
            shaped.append({"ticker": b.get("ticker"), "directive": b.get("directive"),
                           "archetype": b.get("archetype"), "ladder": b.get("ladder") or {},
                           "asymmetry": {"rho": V.get("rho"), "floor_coverage": V.get("floor_coverage")},
                           "gate": b.get("gate") or {}})
        if not shaped:
            return

        # Open decisions = frozen decisions with no linked outcome yet (newest-first).
        closed_ids = set()
        for o in lm.query(type="outcome", limit=0):
            closed_ids.update(o.get("refs") or [])
        open_decisions = [d for d in lm.query(type="decision", limit=0)
                          if d.get("id") not in closed_ids]

        def _age(ts):
            d = _age_days_iso(ts)
            return None if d is None else int(d)

        plan = calibration.plan_flywheel_actions(open_decisions, shaped,
                                                 horizon_days=horizon_days, age_days_fn=_age)
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code"),
                  "net_tilt": (self.terminal_state.get("macro_tape") or {}).get("net_tilt")}
        n_closed = n_frozen = 0

        # CLOSE first (grade the old bet at the live mark) so a re-freeze of the same name is clean.
        for c in plan.get("close", []):
            dec = c["decision"]
            scored = calibration.score_outcome(dec.get("meta") or {}, c["realized_price"],
                                               horizon_days=horizon_days)
            if scored.get("status") != "scored":
                continue
            # H5 — Brier-score the thesis's CONFIDENCE TRAIL against the realized result, so the
            # outcome records whether the desk's stated confidence was honest, not just directional.
            try:
                trail = [float((e.get("meta") or {}).get("confidence"))
                         for e in lm.query(type="conviction", limit=0, newest_first=False)
                         if dec.get("id") in (e.get("refs") or [])
                         and (e.get("meta") or {}).get("confidence") is not None]
                brier = calibration.brier_score(trail, scored.get("result")) if trail else None
                if brier:
                    scored["brier"] = brier
            except Exception:
                pass
            txt = (f"OUTCOME {scored['result'].upper()} {scored['realized_return']*100:+.0f}% "
                   f"@{horizon_days}d (leg {scored['leg_hit']}) · {c['reason']}")
            lm.write("outcome", text=txt, ticker=dec.get("ticker"),
                     tags=["outcome", scored["result"], "flywheel"], regime=regime,
                     meta=scored, refs=[dec.get("id")], source="engine-flywheel")
            n_closed += 1

        for b in plan.get("freeze", []):
            decision = calibration.decision_from_rating(b)
            legs = decision.get("legs", {}) or {}
            txt = (f"DECISION {decision.get('verdict','')} @ {decision.get('price')} "
                   f"[floor {legs.get('floor')} · bull {legs.get('bull')}]")
            lm.write("decision", text=txt, ticker=decision.get("ticker"),
                     tags=["decision", "flywheel"], regime=regime, meta=decision,
                     source="engine-flywheel")
            n_frozen += 1

        # Persist the per-archetype LEARNED base-rate roll-up (deduped once/day) — the durable,
        # regime-stamped artifact discovery (D4) and the agent prior anchor to, so a find is judged
        # against the desk's OWN closed track record, not only the published outside view.
        try:
            scored = [e.get("meta", {}) for e in lm.query(type="outcome", limit=0)
                      if (e.get("meta") or {}).get("status") == "scored"]
            learned = calibration.learned_base_rates(scored)
            if learned:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                recent = lm.query(type="calibration_snapshot", limit=1)
                if not (recent and str(recent[0].get("ts", ""))[:10] == today):
                    lm.write("calibration_snapshot",
                             text=f"per-archetype learned base rates ({len(learned)} archetype(s))",
                             tags=["calibration", "flywheel"], regime=regime,
                             meta={"learned": learned}, source="engine-flywheel")
        except Exception as e:
            logging.warning("calibration snapshot skipped (non-fatal): %s", e)

        self._flywheel_ts = now
        if n_closed or n_frozen:
            logging.info("calibration flywheel: froze %d, closed %d decision(s)", n_frozen, n_closed)

    def _record_valuation_ledger(self, cfg: dict) -> None:
        """Validation flywheel (Phase 1): stamp each name's full valuation state point-in-time
        into the append-only valuation ledger (``data/valuation_ledger.jsonl``) — the keystone
        record the replay harness grades. RECORDS the blocks this cycle already computed (the
        conviction baskets, the triangulation legs, the live regime) plus the research-cache
        input provenance copied BY VALUE; never recomputes anything. Cadence (daily mark +
        material change + seed) is enforced inside ``maybe_record``. Caller fences exceptions."""
        import valuation_ledger as _vl
        if getattr(self, "_vledger", None) is None:
            self._vledger = _vl.ValuationLedger()
            self._engine_git_sha = _vl.git_sha()
        conv = self.terminal_state.get("conviction_mode") or {}
        baskets = conv.get("baskets") or []
        if not baskets:
            return
        regime = {"mri": self.terminal_state.get("mri"),
                  "posture": (self.terminal_state.get("posture") or {}).get("code"),
                  "net_tilt": (self.terminal_state.get("macro_tape") or {}).get("net_tilt")}
        avd = (self.terminal_state.get("archetype_valuation_detail") or {})
        results = avd.get("results", {}) if isinstance(avd, dict) else {}
        cfg_hash = _vl.config_hash(cfg)
        rc = None
        try:
            import research_cache as _rcmod
            rc = _rcmod.ResearchCache()
        except Exception:
            rc = None
        # Phase 2.1 — the replay harness's ground truth: stamp today's price mark into the
        # daily-close store every cycle (same-day marks converge to the close; past dates are
        # immutable). Re-instantiated per call so a concurrent backfill is read, never clobbered.
        _hist = None
        try:
            import price_history as _ph
            _hist = _ph.PriceHistory()
        except Exception:
            _hist = None
        _hist_dirty = False
        today_utc = time.strftime("%Y-%m-%d", time.gmtime())
        for b in baskets:
            tkr = b.get("ticker")
            if not tkr:
                continue
            summ = results.get(tkr) if isinstance(results.get(tkr), dict) else {}
            inputs = _vl.inputs_from_provenance(rc.provenance(tkr)) if rc is not None else {}
            snap = _vl.snapshot_from_basket(
                b, inputs=inputs, regime=regime,
                legs={"values": (summ or {}).get("legs"),
                      "weights": (summ or {}).get("weights"),
                      "confidence": (summ or {}).get("confidence")},
                rep_floor=(cfg.get("rep_floor_params") if tkr == "AGA.V" else None),
                config_hash=cfg_hash, engine_git_sha=self._engine_git_sha)
            self._vledger.maybe_record(snap)
            if _hist is not None and snap.get("price"):
                r = _hist.record_mark(tkr, today_utc, snap["price"], today=today_utc, save=False)
                if r.get("ok") and not r.get("duplicate"):
                    _hist_dirty = True
        if _hist is not None and _hist_dirty:
            _hist._save()

    def _compute_conviction_mode(self, *, cfg: dict, cad_prices: dict, mri_score: float,
                                 net_tilt: str, forensic_metrics: dict) -> dict:
        """PHASE 7/8 (additive): build the primary Conviction Mode block — the 0-10 T-Q-V Asymmetry
        Rating per basket — from blocks already computed this cycle (``valuation_detail``,
        ``archetype_valuation_detail``, ``forensics``, ``mri``) plus live CAD prices, with a Phase 8
        live-catalyst overlay (drill/financing/permitting events nudge conviction / trip the forensic
        gate / advance the permitting lens) and a recent-catalyst list per card. It reads NONE of the
        diversified-book sizing machinery (caps / ES95 / shrinkage / Kelly). Isolated so it can never
        crash the eval loop."""
        if build_conviction_state is None:
            return {"status": "unavailable", "baskets": []}

        vd = self.terminal_state.get("valuation_detail", {}) or {}
        avd = self.terminal_state.get("archetype_valuation_detail", {}) or {}
        results = avd.get("results", {}) if isinstance(avd, dict) else {}
        forensics = self.terminal_state.get("forensics", {}) or {}
        meta = cfg.get("portfolio_metadata", {})

        # Phase 8: catalyst overlays per ticker (bounded; graceful empty when no feed).
        cat_feed = self._catalyst_feed(cfg)
        overlays = {}
        if build_catalyst_overlays is not None and cat_feed.get("events"):
            try:
                overlays = build_catalyst_overlays(cat_feed["events"], list(cad_prices), cfg)
            except Exception as e:
                logging.warning("Phase 8 catalyst overlay skipped (non-fatal): %s", e)

        def _dilution_velocity(tkr):
            m = forensic_metrics.get(tkr) or {}
            s0, s1 = m.get("shares_t0"), m.get("shares_t1")
            try:
                if s0 and s1 and s1 > 0:
                    return max(0.0, (float(s0) / float(s1) - 1.0)) * 4.0   # QoQ -> annualized
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            return None

        # Validation flywheel (Phase 5 interlock): the EMPIRICAL market-leg sigma — the measured
        # dispersion across the live peer comp — feeds the spear's distributional ribbon instead
        # of an assumed band. Defensive: absent peers/module -> None (the confidence map applies).
        peer_market_sigma = None
        try:
            import peer_normalization as _pn_audit
            _audit = _pn_audit.comp_audit(getattr(self.peer_engine, "peer_data_cache", None) or {})
            peer_market_sigma = (_audit or {}).get("rel_dispersion")
        except Exception:
            peer_market_sigma = None

        assets = []
        for tkr, price in cad_prices.items():
            summ = results.get(tkr, {}) if isinstance(results.get(tkr), dict) else {}
            legs = summ.get("legs", {}) if isinstance(summ.get("legs"), dict) else {}
            conf = summ.get("confidence", {}) if isinstance(summ.get("confidence"), dict) else {}
            pm = meta.get(tkr, {}) if isinstance(meta.get(tkr), dict) else {}
            is_spear = (tkr == "AGA.V")

            # Floor = the cost/REP leg; the spear prefers the authoritative triangulation cost leg.
            floor = (vd.get("legs", {}) or {}).get("cost") if is_spear else legs.get("cost")
            if not _is_pos(floor):
                floor = legs.get("cost")
            if not is_spear:                                  # ballast: prefer the REAL book-value floor
                _bvf = self._research_book_floor(tkr)         # (sourced filings) over the 10% placeholder
                if _is_pos(_bvf):
                    floor = _bvf

            if is_spear and isinstance(vd.get("scenarios"), dict):
                sc = vd["scenarios"]
                base_v, bull_v, bear_v = sc.get("base"), sc.get("bull"), sc.get("bear")
            else:
                # No per-asset scenario band -> single-point target (the ribbon widens to reflect it).
                base_v = summ.get("intrinsic_after_forensic") or summ.get("blended_intrinsic")
                bull_v = bear_v = None

            asset = {
                "ticker": tkr,
                # Phase 7.4 niche-tag hook (forward-looking, non-breaking): a future sub-archetype
                # (e.g. "accretive_acquirer" under asset_light_yield) could attach here via
                # asymmetry_rating.niche_tags_for(archetype) to specialize tooltips/weights/gates
                # WITHOUT changing the five core archetypes. Nothing reads it yet.
                "archetype": summ.get("archetype") or pm.get("archetype", "_default"),
                "archetype_code": summ.get("archetype_code"),
                # 3rd taxonomy axis — finer sort within the archetype + orthogonal sector tags
                # (display/correlation only; does not move the rating). Prefer the valuation
                # summary's resolved values, fall back to the config metadata.
                "subarchetype": summ.get("subarchetype") or pm.get("subarchetype"),
                "subarchetype_label": summ.get("subarchetype_label"),
                "sector_tags": summ.get("sector_tags") or pm.get("sector_tags", []),
                "price": price,
                "floor": floor,
                "base": base_v,
                "bull": bull_v,
                "bear": bear_v,
                "mri": mri_score,
                "regime_alpha": summ.get("regime_alpha", 0.0),
                # commodity-aware tailwind: each name's metal regime (gold ≠ silver ≠ uranium),
                # blended with the shared archetype lean in asymmetry_rating._pillar_macro_tailwind
                "commodity": self._name_commodity(tkr),
                "commodity_regime": self._commodity_regime_lean(self._name_commodity(tkr)),
                "forensic_score": (forensics.get("jsf_score") if is_spear else summ.get("forensic_score")),
                "conviction": summ.get("conviction", 0.5),
                "data_quality": summ.get("data_quality", "full" if summ else "sparse"),
                "runway_months": (forensics.get("runway") if is_spear else None),
                "dilution_velocity": _dilution_velocity(tkr),
                "fraser_index": pm.get("fraser_index"),
                "stage": pm.get("stage"),
                "management_score": pm.get("management_score"),
                "thesis_slot": pm.get("thesis_slot"),
                "thesis_slot_desc": pm.get("thesis_slot_desc"),
                # EVAL-set marker: rated alongside the book but holds no weight and enters no
                # sizing — the cockpit badges it so an eval row can never read as a holding.
                "eval_only": bool(pm.get("eval_only")),
                "market_confidence": conf.get("market"),
                # V1 mark-NAV-to-spot quality: tier (live|stamped) + staleness of the spot the NAV
                # was marked at — the ribbon widens on a stale stamp; the Story Card shows the tier.
                "nav_quality": getattr(self, "_nav_quality", {}).get(tkr),
                # Validation flywheel (Phase 3): the triangulation legs + their confidence tilts
                # reach the rating so the confidence ribbon becomes a propagated P10/P50/P90
                # ESTIMATE band (uncertainty.py) instead of a heuristic ±.
                "legs": legs or None,
                "leg_weights": summ.get("weights") if isinstance(summ.get("weights"), dict) else None,
                "leg_confidence": conf or None,
            }
            if is_spear and peer_market_sigma:
                # the spear's market leg is the peer comp — use its MEASURED dispersion as sigma
                asset["leg_sigma"] = {"market": peer_market_sigma}
            if is_spear:
                # Junior-miner quality checklist (grade / scale / metallurgy) from the config
                # resource model, so the Q pillar reads like a mining investor's checklist.
                asset.update(self._spear_quality_inputs(cfg))
                if _is_pos(vd.get("avg_tq")):
                    asset["avg_tq"] = vd.get("avg_tq")

            # ---- Phase 8: apply the bounded live-catalyst overlay to the rating inputs ----
            ov = overlays.get(tkr, {})
            if ov:
                cd = ov.get("conviction_delta") or 0.0
                if cd:                                         # Q: conviction nudge
                    asset["conviction"] = max(0.0, min(1.0, float(asset.get("conviction") or 0.5) + cd))
                if ov.get("dilution_velocity") is not None:    # gate: financings can trip it
                    base_dil = asset.get("dilution_velocity") or 0.0
                    asset["dilution_velocity"] = max(base_dil, float(ov["dilution_velocity"]))
                if ov.get("permitting_stage"):                 # Q permitting lens
                    asset["stage"] = ov["permitting_stage"]
                # V: drill/grade/resource catalysts lift the bull/base scenario bands (bounded).
                bu, be = ov.get("bull_uplift_pct") or 0.0, ov.get("base_uplift_pct") or 0.0
                if bu and _is_pos(asset.get("bull")):
                    asset["bull"] = float(asset["bull"]) * (1.0 + bu)
                if be and _is_pos(asset.get("base")):
                    asset["base"] = float(asset["base"]) * (1.0 + be)
            assets.append(asset)

        context = {"mri": round(float(mri_score), 1), "regime": net_tilt,
                   "catalyst_feed": cat_feed.get("status", "n/a"),
                   "note": "Conviction Mode is assessment-only: no position caps, ES95 throttle, "
                           "covariance shrinkage, or Kelly de-leveraging. See Detailed Analysis for those."}
        state = build_conviction_state(assets, config=cfg, meta=context)
        # Phase 8 review: keep Conviction Mode calm — the catalyst feed is collapsed by default
        # ("collapsed" | "expanded" | "hidden"); the reactivity itself lives in the rating/V move.
        state["catalyst_display"] = (cfg.get("catalysts", {}) or {}).get("card_display", "collapsed")

        # Per-name DISPLAY CURRENCY (consistency fix): every valuation leg (price/floor/base/bull)
        # in the basket is CAD-normalized for the blended-book math, but the cockpit shows each name
        # next to its NATIVE-currency fundamentals (FMP 52-wk range, mcap…). Mixing the two made a
        # USD name (GROY) read price $2.88 (USD) beside floor $4.38 (CAD) — a contradiction, even
        # though φ/upside (ratios) were always right. Attach the native currency + the fx used + a
        # native ladder DERIVED from the same CAD legs by the same fx, so the absolute points
        # reconcile exactly with the ratios. CAD names get fx 1.0 (no change).
        usd_to_cad = float(self.state_cache.get("usd_to_cad") or 1.38)
        bv_all = cfg.get("ballast_valuation", {}) if isinstance(cfg.get("ballast_valuation"), dict) else {}
        pm_all = cfg.get("portfolio_metadata", {}) if isinstance(cfg.get("portfolio_metadata"), dict) else {}
        for b in state.get("baskets", []):
            ov = overlays.get(b.get("ticker"), {})
            if ov:
                b["catalysts"] = ov.get("recent", [])
                b["catalyst_signal"] = ov.get("net_signal", 0.0)
                b["catalyst_count"] = ov.get("count", 0)
                if ov.get("v_moved"):                          # flag that V was catalyst-adjusted
                    b["v_catalyst"] = {
                        "bull_uplift_pct": ov.get("bull_uplift_pct", 0.0),
                        "base_uplift_pct": ov.get("base_uplift_pct", 0.0),
                        "p_discovery_delta": ov.get("p_discovery_delta", 0.0),
                        "drivers": ov.get("v_drivers", []),
                    }
            tk = b.get("ticker")
            bv = bv_all.get(tk) or {}
            ccy = str(bv.get("currency") or (pm_all.get(tk) or {}).get("currency") or "CAD").upper()
            fx = usd_to_cad if ccy == "USD" else 1.0
            b["display_ccy"] = ccy
            b["fx_to_cad"] = round(fx, 4)
            nat = native_ladder(b.get("ladder") or {}, fx)    # CAD legs ÷ fx (φ/upside preserved)
            if nat:
                b["ladder_native"] = nat
            # V2 — probability-weighted scenario NAV: E[NAV] across the frozen ladder legs under
            # probabilities DERIVED from the live signals (a drill/grade catalyst's p_discovery_delta
            # GROUNDS it; the regime tilt refines it). No probability-mover → the honest breakeven
            # inversion. The intrinsic-input P10/P50/P90 band already ships on confidence_ribbon; this
            # is the complementary scenario-outcome expectation. CAD basis (the cockpit converts).
            try:
                import valuation_actions as _va
                lad = b.get("ladder") or {}
                if _is_pos(lad.get("price")):
                    b["scenario_nav"] = _va.scenario_nav(
                        lad, p_discovery_delta=(ov or {}).get("p_discovery_delta"),
                        regime_tilt=net_tilt, price=lad.get("price"))
            except Exception as e:
                logging.debug("scenario NAV skipped for %s: %s", tk, e)
        return state

    async def evaluate_master_architecture(self, force_macro=False):
        # Rebuild the per-cycle effective config ONCE (file defaults + confirmed overrides) and let
        # every engine read this same snapshot via its provider — overlay reaches the live book.
        cfg = self._refresh_effective_config()

        if not self.shares or force_macro:
            self._load_shares_from_csv(force=True)

        # 1. READ INSTANT SNAPSHOTS FROM WORKER CACHE UNDER THREAD LOCK
        with self.state_lock:
            mean_peer_ev = self.state_cache["mean_peer_ev"]
            peer_details = self.state_cache["peer_details"]
            avg_disc_cost = self.state_cache["avg_disc_cost"]
            
            y10 = self.state_cache["y10"]
            y30 = self.state_cache["y30"]
            spr = self.state_cache["spr"]
            ted = self.state_cache["ted"]
            eff = self.state_cache["eff"]
            vix = self.state_cache["vix"]
            macro_status = self.state_cache["macro_status"]
            
            prices = self.state_cache["prices"].copy()
            prices_status = self.state_cache["prices_status"]
            
            dxy_mom = self.state_cache["dxy_mom"]
            current_dxy = self.state_cache["current_dxy"]
            dxy_status = self.state_cache["dxy_status"]
            
            usd_to_cad = self.state_cache["usd_to_cad"]
            
            real_yield = self.state_cache["real_yield"]
            ry_status = self.state_cache["ry_status"]
            
            copper = self.state_cache["copper"]
            gold = self.state_cache["gold"]
            
            m1_price = self.state_cache["m1_price"]
            m180_price = self.state_cache["m180_price"]
            
            cftc_net_longs = self.state_cache["cftc_net_longs"]
            cftc_status = self.state_cache["cftc_status"]
            
            forensic_data = self.state_cache["forensic_metrics"].get("AGA.V")
            
            ballast_sloans = {}
            for ticker in ["GROY", "URC.TO", "GMX.TO"]:
                m = self.state_cache["forensic_metrics"].get(ticker)
                ballast_sloans[ticker] = m["sloan_cfo"] if m else 0.02
                
            df_rets = self.state_cache["df_rets"]
            corr_matrix = self.state_cache["corr_matrix"].copy()
            vols = self.state_cache["vols"].copy()
            es_95 = self.state_cache.get("es_95", -0.052)   # signed decimal (negative = loss); see seed note
            port_vol = self.state_cache.get("port_vol", 0.40)
            avg_corr = self.state_cache.get("avg_corr", 0.45)
            
            aga_adv = self.state_cache["aga_adv"]
            mri_history = self.state_cache.get("mri_history", {})
            feed_ts = {f: self.state_cache.get(f + "_ts", 0.0) for f in ("prices", "macro", "ry", "dxy", "cftc", "peers")}
            feed_status = {"prices": prices_status, "macro": macro_status, "ry": ry_status, "dxy": dxy_status, "cftc": cftc_status}

        self.cached_mean_peer_ev_oz = mean_peer_ev

        # --- Data freshness / point-in-time layer (v5.2) ---
        # Each feed refreshes on its own worker cadence (prices ~60s, macro ~30m, CFTC weekly), so
        # their vintages diverge. Expose every feed's age + a staleness flag vs configurable
        # thresholds, plus the cross-feed vintage skew, so stale-mix / look-ahead risk is visible
        # in the cockpit rather than silent.
        fresh_cfg = cfg.get("data_freshness", {})
        max_age = fresh_cfg.get("max_age_seconds", {
            "prices": 300, "macro": 5400, "ry": 5400, "dxy": 5400, "cftc": 172800, "peers": 86400
        })
        now_ts = time.time()
        freshness = {}
        any_stale = False
        for feed, ts in feed_ts.items():
            age = max(0.0, now_ts - ts) if ts else None
            thr = max_age.get(feed, 3600)
            stale = (age is None) or (age > thr) or (feed_status.get(feed) == "DEGRADED_STALE")
            any_stale = any_stale or stale
            freshness[feed] = {
                "age_seconds": round(age, 1) if age is not None else None,
                "age_minutes": round(age / 60.0, 1) if age is not None else None,
                "as_of": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else None,
                "threshold_seconds": thr,
                "stale": bool(stale),
                "status": feed_status.get(feed, "LIVE")
            }
        fast_ages = [now_ts - feed_ts[f] for f in ("prices", "macro", "ry", "dxy") if feed_ts.get(f)]
        vintage_skew = round(max(fast_ages) - min(fast_ages), 1) if len(fast_ages) >= 2 else 0.0
        # cache-file vintages so the cockpit can show provenance honestly (forensic = quarterly;
        # mri_history feeds the regime percentiles + realized-vol — should refresh intraday).
        for fkey, fpath, thr in (("forensic", ".cache/forensic_cache.json", 86400),
                                 ("mri_history", ".cache/disk_cache_mri_history.json", 43200)):
            try:
                mt = os.path.getmtime(fpath)
                age = max(0.0, now_ts - mt)
                freshness[fkey] = {
                    "age_seconds": round(age, 1), "age_minutes": round(age / 60.0, 1),
                    "as_of": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mt)),
                    "threshold_seconds": thr, "stale": bool(age > thr), "status": "CACHED"}
                any_stale = any_stale or freshness[fkey]["stale"]
            except OSError:
                pass
        self.terminal_state["data_freshness"] = {
            "feeds": freshness,
            "stale_feed_count": sum(1 for v in freshness.values() if v["stale"]),
            "vintage_skew_seconds": vintage_skew,
            "skew_warn_seconds": fresh_cfg.get("skew_warn_seconds", 5400),
            "any_stale": bool(any_stale),
            "holdings_csv": getattr(self, "_holdings_csv", None)   # which holdings file + its age (days)
        }

        # 2. POPULATE METRICS IN TERMINAL STATE
        self.terminal_state["metrics"].update({
            "10Y": {"value": y10, "status": macro_status}, 
            "30Y": {"value": y30, "status": macro_status},
            "Spreads": {"value": spr, "status": macro_status}, 
            "TED": {"value": ted, "status": macro_status},
            "EFFR": {"value": eff, "status": macro_status}, 
            "VIX": {"value": vix, "status": macro_status}
        })

        p_aga = prices.get("AGA.V", 0.71)
        p_urc = prices.get("URC.TO", 4.82)
        p_groy = prices.get("GROY", 3.22)
        p_gmx = prices.get("GMX.TO", 2.04)
        spot_ag = prices.get("SI=F", 74.8)
        wti_price = prices.get("CL=F", 80.0)

        self.terminal_state["metrics"]["Spot_Ag"] = {"value": spot_ag, "status": prices_status}
        self.terminal_state["metrics"]["WTI"] = {"value": wti_price, "status": prices_status}
        self.terminal_state["metrics"]["DXY"] = {"value": current_dxy, "status": dxy_status}
        self.terminal_state["metrics"]["DXY_MOMENTUM"] = {"value": dxy_mom, "status": dxy_status}
        self.terminal_state["metrics"]["CFTC_Silver_Net_Longs"] = {"value": cftc_net_longs, "status": cftc_status}

        # Gold/Silver Ratio — derived from existing state, no additional API call
        gsr = gold / spot_ag if spot_ag > 0 else 80.0
        self.terminal_state["metrics"]["GSR"] = {"value": round(gsr, 2), "status": prices_status}

        # 3. PORTFOLIO EQUITY VALUE CALCULATION
        live_portfolio_value = (
            self.shares.get('AGA', 0) * p_aga + self.shares.get('URC', 0) * p_urc +
            self.shares.get('GMX', 0) * p_gmx + self.shares.get('GROY', 0) * p_groy * usd_to_cad +
            self.shares.get('UROY_CALL', 0) * 100.0 * self.uroy_call_price * usd_to_cad
        )
        if live_portfolio_value < 1000: live_portfolio_value = cfg.get("target_capital", 5360.0)

        # 4. SET LIVE VS DEGRADED STATUS (status flags OR age-based staleness from the freshness layer)
        if any_stale or "DEGRADED_STALE" in [macro_status, prices_status, dxy_status, ry_status, cftc_status]:
            self.terminal_state["status"] = "DEGRADED_STALE"
        else:
            self.terminal_state["status"] = "LIVE"
        # A1.9: a dead background worker means the data it owns is silently freezing — the status
        # line must say so (grounded-or-silent at the process level), whatever the feeds claim.
        try:
            import task_supervision as _tsup
            _dead = _tsup.dead_workers(self.terminal_state.get("worker_health"))
            if _dead:
                self.terminal_state["status"] = "DEGRADED_WORKER_DOWN: " + ",".join(_dead)
        except Exception:
            pass

        mri_score, mri_detail = self.macro_engine.calculate_mri(
            self.terminal_state["metrics"], spot_ag, real_yield, copper, gold, dxy_mom,
            return_detail=True, history=mri_history
        )
        self.terminal_state["mri"] = mri_score
        self.terminal_state["mri_decomposition"] = mri_detail

        # --- Fluid Macro Tape (v5.2): the key cross-asset signals the regime read is built on,
        # each with a value, a directional regime bias, and a short read, so the cockpit can render
        # a dense, glanceable macro strip. All derived from existing state (+ optional VIX term
        # structure) — no extra network round-trips beyond the consolidated price call. ---
        vix_val = float(self.terminal_state["metrics"].get("VIX", {}).get("value", 16.5))
        vix3m = prices.get("^VIX3M", 0.0) or 0.0
        vix_term = (vix3m / vix_val) if (vix_val > 0 and vix3m > 0) else None  # >1 contango (calm), <1 backwardation (stress)
        cu_au = (copper / gold * 1000.0) if gold > 0 else None
        dxy_gold = (current_dxy / gold * 1000.0) if gold > 0 else None
        cftc_cfg = cfg.get("cftc_params", {"norm_low": -15000, "norm_high": 85000})
        cftc_pctile = max(0.0, min(100.0, (cftc_net_longs - cftc_cfg["norm_low"]) /
                                   max(1e-9, (cftc_cfg["norm_high"] - cftc_cfg["norm_low"])) * 100.0))

        def _tape(key, label, value, bias, read, fmt="{:.2f}"):
            return {"key": key, "label": label,
                    "value": round(value, 4) if isinstance(value, (int, float)) else value,
                    "display": (fmt.format(value) if isinstance(value, (int, float)) else "—"),
                    "bias": bias, "read": read}

        macro_tape = [
            _tape("gsr", "Gold/Silver", gsr,
                  "risk_off" if gsr > 85 else ("risk_on" if gsr < 75 else "neutral"),
                  "Silver cheap vs gold" if gsr > 85 else ("Silver leadership" if gsr < 75 else "Balanced")),
            _tape("cu_au", "Copper/Gold ×1k", cu_au if cu_au is not None else 0.0,
                  "risk_on" if (cu_au or 0) > 1.5 else "risk_off",
                  "Growth/reflation bid" if (cu_au or 0) > 1.5 else "Defensive / slowdown"),
            _tape("dxy_gold", "DXY/Gold ×1k", dxy_gold if dxy_gold is not None else 0.0,
                  "risk_off" if (dxy_gold or 0) > 45 else "risk_on",
                  "Dollar dominant" if (dxy_gold or 0) > 45 else "Gold dominant"),
            _tape("dxy", "DXY", current_dxy if current_dxy is not None else 0.0,
                  "risk_off" if (current_dxy or 0) > 104 else ("risk_on" if (current_dxy or 0) < 100 else "neutral"),
                  "Strong dollar" if (current_dxy or 0) > 104 else ("Weak dollar" if (current_dxy or 0) < 100 else "Neutral"), "{:.1f}"),
            _tape("real_yield", "Real Yield", real_yield,
                  "risk_off" if real_yield > 2.0 else ("risk_on" if real_yield < 0.5 else "neutral"),
                  "Headwind for metals" if real_yield > 2.0 else ("Tailwind for metals" if real_yield < 0.5 else "Neutral"), "{:.2f}%"),
            _tape("sofr_spread", "SOFR Spread", ted,
                  "risk_off" if ted > 0.20 else "risk_on",
                  "Funding stress" if ted > 0.20 else "Funding calm", "{:+.2f}%"),
            _tape("hy_spread", "HY Spread", spr,
                  "risk_off" if spr > 4.0 else "risk_on",
                  "Credit stress" if spr > 4.0 else "Credit benign", "{:.2f}%"),
            _tape("curve_2s30s", "30Y–10Y", (y30 - y10),
                  "risk_off" if (y30 - y10) < 0 else "neutral",
                  "Inverted (late cycle)" if (y30 - y10) < 0 else "Positive slope", "{:+.2f}%"),
            _tape("vix", "VIX", vix_val,
                  "risk_off" if vix_val > 22 else ("risk_on" if vix_val < 15 else "neutral"),
                  "Elevated fear" if vix_val > 22 else ("Complacent" if vix_val < 15 else "Normal")),
            _tape("cftc", "CFTC Net %ile", cftc_pctile,
                  "risk_off" if cftc_pctile > 80 else ("risk_on" if cftc_pctile < 25 else "neutral"),
                  "Crowded long" if cftc_pctile > 80 else ("Washed out (contrarian)" if cftc_pctile < 25 else "Mid-range"), "{:.0f}"),
        ]
        if vix_term is not None:
            macro_tape.append(_tape("vix_term", "VIX Term (3M/1M)", vix_term,
                                    "risk_off" if vix_term < 1.0 else "risk_on",
                                    "Backwardation (stress)" if vix_term < 1.0 else "Contango (calm)", "{:.2f}"))

        risk_off_count = sum(1 for t in macro_tape if t["bias"] == "risk_off")
        risk_on_count = sum(1 for t in macro_tape if t["bias"] == "risk_on")
        self.terminal_state["macro_tape"] = {
            "signals": macro_tape,
            "risk_off_count": risk_off_count,
            "risk_on_count": risk_on_count,
            "net_tilt": "RISK-OFF" if risk_off_count > risk_on_count else ("RISK-ON" if risk_on_count > risk_off_count else "BALANCED"),
            "top_mri_driver": mri_detail.get("top_driver", "n/a"),
            "vix_term_structure": round(vix_term, 3) if vix_term is not None else None
        }

        # Full US Treasury curve from FMP (free tier). Cached 6h -> ~4 real calls/day; the per-loop
        # call is an in-memory cache hit, and the rare network refresh runs off-thread so the eval
        # loop never blocks. Gives the cockpit a real curve (1mo…30yr), not just the 10s/30s pair.
        if getattr(self, "fmp", None):
            try:
                tr = await asyncio.to_thread(self.fmp.treasury)
                cur = tr.get("data") if isinstance(tr, dict) else None
                if isinstance(cur, dict):
                    self.terminal_state["treasury_curve"] = {
                        "date": cur.get("date"),
                        "tenors": {k: cur.get(k) for k in
                                   ("month1", "month3", "month6", "year1", "year2", "year3",
                                    "year5", "year7", "year10", "year20", "year30")},
                        "source": "FMP", "cached": bool(tr.get("cached", True)),
                    }
            except Exception:
                pass

        # 5. MICRO FORENSICS RUNWAY
        rf_floor = self.valuation_engine.calculate_rep_floor()
        monthly_burn = cfg["cash_burn"]["monthly_burn_rate"]
        
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        cash_runway_months = cash_component / monthly_burn if monthly_burn > 0 else 99.0

        if forensic_data:
            sloan_cfo = forensic_data["sloan_cfo"]
            sloan_bs = forensic_data["sloan_bs"]
            shares_t0 = forensic_data["shares_t0"]
            shares_t1 = forensic_data["shares_t1"]
            sga_expense = forensic_data["sga_t0"]
            cfo_t0 = forensic_data.get("cfo_t0")
            cfo_t1 = forensic_data.get("cfo_t1")
            cash_t0 = forensic_data.get("cash_t0")
            aga_enterprise_value = forensic_data.get("enterprise_value")
        else:
            sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense = 0.021, 0.024, 208600000, 208600000, 450000
            cfo_t0, cfo_t1, cash_t0 = None, None, None
            aga_enterprise_value = None

        forensic_score, forensic_penalty, forensic_details = self.forensic_engine.calculate_jsf_score(
            "AGA.V", cash_component, monthly_burn,
            sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense,
            cfo_t0=cfo_t0, cfo_t1=cfo_t1, cash_t0=cash_t0, enterprise_value=aga_enterprise_value
        )
        
        self.terminal_state["forensics"] = {
            "jsf_score": forensic_score,
            "penalty_factor": round(forensic_penalty, 3),
            "runway": round(cash_runway_months, 1),
            "sloan_cfo": round(sloan_cfo, 4),
            "sloan_bs": round(sloan_bs, 4),
            "details": forensic_details,
            "overrides_applied": forensic_details.get("overrides_applied", [])
        }

        # 6. DYNAMIC AISC AND VALUATION MARGINS
        base_aisc = cfg["dynamic_discovery_v5"]["estimated_industry_aisc_2026"]
        dynamic_aisc = base_aisc + max(0, wti_price - 80.0) * 0.15
        capital_discount_factor = self.valuation_engine.calculate_capital_discount_factor(y30)

        # Live realized silver vol (Phase 4a) feeds the option-premium vol term, replacing the old
        # hardcoded 0.25. Derived from the cached 5y MRI silver history; falls back to 0.30 if absent.
        silver_vol = _realized_vol(mri_history.get("silver", []), lookback=60) or 0.30

        # 7. TERM STRUCTURE STRESS PREMIUMS
        if m1_price > 0 and m180_price > 0 and m1_price > m180_price:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": True, "status": "LIVE"}
            uplift_premium = min(0.25, max(0.0, (m1_price - m180_price) / m1_price) * 5.0)
        else:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": False, "status": "LIVE"}
            uplift_premium = 0.0

        # ---- LEGACY valuation (v5.2) — retained for ONE release as the reconciliation baseline and to
        # keep the v4_valuation diagnostic keys populated. NOT authoritative. discovery_premium_factor
        # here is the opaque ~3.3x operating-leverage multiple (=1.68*(spot-AISC)/AISC) Phase 4a removes;
        # ROV here is the dead/incoherent additive term. Both are superseded by the triangulation below.
        phi_margin = max(0.58, (spot_ag - dynamic_aisc) / spot_ag) if spot_ag > dynamic_aisc else 0.05
        commodity_leverage = spot_ag / dynamic_aisc if dynamic_aisc > 0 else 1.0
        exp_scalar = cfg["dynamic_discovery_v5"].get("explorer_re_rating_scalar", 1.68)
        raw_factor = commodity_leverage * phi_margin * exp_scalar
        spot_dev = max(0, (spot_ag - 76.5) / 50)
        ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - mri_score / 100)
        discovery_premium_factor = max(0.50, min(raw_factor, ceiling))
        rov = self.valuation_engine.calculate_continuous_rov(real_yield, spot_ag, cfg.get("rov_default", 1.18))
        is_iai_per_share, jurisdiction_uplift = self.valuation_engine.calculate_is_iai(
            mean_peer_ev, discovery_premium_factor, spot_ag, capital_discount_factor
        )
        jurisdiction_uplift = jurisdiction_uplift * (1.0 + uplift_premium)
        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (exp.get("expected_future_oz", 0) * mean_peer_ev *
                             jurisdiction_uplift * exp.get("probability_of_discovery", 0.25))
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)
        legacy_aga_intrinsic = (
            (0.15 * rf_floor) + (0.70 * is_iai_per_share * forensic_penalty) + (0.15 * rov) + exp_per_share
        )

        # ---- 8. NEW (Phase 4a) TRIANGULATED INTRINSIC (AUTHORITATIVE) ----
        # Confidence-tilted Cost + (quality-graded, de-overlapped) Market + Income blend. Sector silver
        # strength flows ONCE through the live peer EV/oz (market) and ONCE through the stage-decayed
        # option-convexity premium (income/option) — the redundant discovery_premium_factor and the dead
        # additive ROV are gone, so a single silver move can no longer be triple-counted.
        spear_kwargs = dict(
            peer_ev_oz=mean_peer_ev, spot_ag=spot_ag, capital_discount_factor=capital_discount_factor,
            real_yield=real_yield, silver_vol=silver_vol, forensic_penalty=forensic_penalty,
            dynamic_aisc=dynamic_aisc, shares_outstanding=cfg["aga_shares_out"],
        )
        spear_detail = self.valuation_engine.calculate_spear_intrinsic(**spear_kwargs)
        aga_intrinsic = spear_detail["v_intrinsic"]
        scenario_range = self.valuation_engine.run_intrinsic_scenarios(spear_kwargs, silver_vol)
        reconciliation = {
            "legacy_intrinsic": round(legacy_aga_intrinsic, 3),
            "new_intrinsic": round(aga_intrinsic, 3),
            "delta": round(aga_intrinsic - legacy_aga_intrinsic, 3),
            "delta_pct": round((aga_intrinsic / legacy_aga_intrinsic - 1.0) * 100, 1) if legacy_aga_intrinsic else None,
            "removed_discovery_multiple": round(discovery_premium_factor, 2),
            "note": "Phase 4a removed the embedded ~%.2fx discovery/operating-leverage multiple and the dead additive ROV; silver torque now flows once via peer EV/oz and once via the stage-decayed option premium." % discovery_premium_factor,
            "legacy_components": {"rep_floor": round(rf_floor, 3), "is_iai_x_pen": round(is_iai_per_share * forensic_penalty, 3),
                                  "rov": round(rov, 3), "exp": round(exp_per_share, 3)},
        }

        # --- Currency normalization (v5.2): the blended index PPI and EV_Blended are computed in
        # CAD. GROY trades in USD (NYSE American) while AGA.V/URC.TO/GMX.TO trade in CAD (TSX/TSX-V).
        # Previously PPI summed GROY's raw USD price with three CAD prices and EV_Blended mixed a
        # USD-anchored GROY sleeve into a CAD blend, biasing Implied Upside. Convert every leg to CAD
        # up front. Per-name currency is config-tunable via `ballast_valuation[name].currency`.
        bv_cfg = cfg.get("ballast_valuation", {})
        def _fx_to_cad(name, default_ccy):
            nm = bv_cfg.get(name) or {}
            ccy = nm.get("currency", default_ccy)
            return usd_to_cad if str(ccy).upper() == "USD" else 1.0
        fx_urc, fx_groy, fx_gmx = _fx_to_cad("URC.TO", "CAD"), _fx_to_cad("GROY", "USD"), _fx_to_cad("GMX.TO", "CAD")
        p_aga_cad = p_aga * _fx_to_cad("AGA.V", "CAD")
        p_urc_cad, p_groy_cad, p_gmx_cad = p_urc * fx_urc, p_groy * fx_groy, p_gmx * fx_gmx

        bw = _resolve_barbell_weights(cfg)   # single validated barbell-weight source
        ppi = (bw["AGA.V"] * p_aga_cad) + (bw["URC.TO"] * p_urc_cad) + (bw["GROY"] * p_groy_cad) + (bw["GMX.TO"] * p_gmx_cad)

        ballast_cfg = cfg.get("ballast_multiples", {"URC.TO": 1.15, "GROY": 1.15, "GMX.TO": 1.20})
        urc_base = ballast_cfg.get("URC.TO", 1.15)
        groy_base = ballast_cfg.get("GROY", 1.15)
        gmx_base = ballast_cfg.get("GMX.TO", 1.20)

        urc_pen = 1.0 - min(0.30, max(0, ballast_sloans.get("URC.TO", 0.0) - 0.05) * 2.0)
        groy_pen = 1.0 - min(0.30, max(0, ballast_sloans.get("GROY", 0.0) - 0.05) * 2.0)
        gmx_pen = 1.0 - min(0.30, max(0, ballast_sloans.get("GMX.TO", 0.0) - 0.05) * 2.0)

        # Spot-linked ballast fair value (v5.2): anchor each sleeve to a fundamental reference
        # re-scaled by LIVE commodity spot, NOT by the name's own share price. This severs the
        # self-referential `price * multiple` feedback loop where a rally manufactured matching
        # "fair value" and Implied Upside never compressed. ref_price defaults to the engine's
        # documented reference prices (the same constants used as live-price fallbacks), spot_ref
        # to the silver reference frame; commodity/ref_price/spot_ref/spot_beta are config-tunable
        # per name via `ballast_valuation` so an analyst can plug in a true NAV anchor.
        spot_ref_default = {"silver": 74.8, "gold": gold if gold and gold > 0 else 2650.0}
        ballast_defaults = {
            "URC.TO": {"ref_price": 4.82, "commodity": "uranium"},
            "GROY":   {"ref_price": 3.22, "commodity": "gold"},
            "GMX.TO": {"ref_price": 2.04, "commodity": "diversified"},
        }

        ballast_anchors = {}

        def _ballast_fv(name, base_mult, forensic_pen, fx):
            nm = bv_cfg.get(name, {})
            dflt = ballast_defaults.get(name, {})
            commodity = nm.get("commodity", dflt.get("commodity", "silver"))
            ref_price = nm.get("ref_price", dflt.get("ref_price", 1.0))
            # Anchor fair value on a SOURCED NAV (research_cache: live nav_inventory mark, else the
            # stamped nav_adj_per_share) rather than the frozen legacy price snapshot the config
            # ref_price encodes (those constants are an old price mark, NOT a NAV — a self-referential
            # anchor). allow_book=False: raw accounting book understates NAV for these holdco/royalty/
            # physical structures (a project generator carries royalties at cost, ~0.71 book vs ~2.04
            # price), so we NEVER anchor on it — we keep the documented config ref_price and FLAG the
            # name as still on a legacy anchor until a real NAV is sourced.
            anchor = "config_ref_price (legacy snapshot)"
            nav = self._research_book_native(name, allow_book=False)
            if nav is not None and _is_pos(nav[0]):
                ref_price, nav_ccy = nav
                anchor = "research_cache_nav"
                fx = usd_to_cad if str(nav_ccy).upper() == "USD" else 1.0   # use the SOURCED currency
            # Spot-link the fair value ONLY for silver (the engine's live, correctly-framed spot).
            # gold/uranium/diversified config spot_refs are stale/silver-framed, so a naive ratio
            # would distort — keep them NAV-anchored (neutral factor); their commodity signal lives in
            # the T-pillar tailwind (commodity_regime) and — for a sourced NAV — in the live-marked NAV.
            if commodity == "silver" and spot_ag and spot_ag > 0:
                spot_now = spot_ag
                spot_ref = nm.get("spot_ref", spot_ref_default.get("silver", spot_ag))
            else:
                spot_now = spot_ref = 1.0                     # neutral: fair value = ref × base_mult
            spot_beta = nm.get("spot_beta", 1.0)
            mult = nm.get("base_mult", base_mult)
            fv_native = self.valuation_engine.calculate_ballast_fair_value(
                ref_price, mult, spot_now, spot_ref, spot_beta, forensic_pen
            )
            fv_cad = fv_native * fx  # normalize the name's native-currency fair value into CAD
            ballast_anchors[name] = {"anchor": anchor, "ref_price_native": round(ref_price, 4),
                                     "fair_value_cad": round(fv_cad, 4)}
            return fv_cad

        urc_fv = _ballast_fv("URC.TO", urc_base, urc_pen, fx_urc)
        groy_fv = _ballast_fv("GROY", groy_base, groy_pen, fx_groy)
        gmx_fv = _ballast_fv("GMX.TO", gmx_base, gmx_pen, fx_gmx)

        ev_blended = (
            (bw["AGA.V"] * aga_intrinsic) +
            (bw["URC.TO"] * urc_fv) +
            (bw["GROY"] * groy_fv) +
            (bw["GMX.TO"] * gmx_fv)
        )
        u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

        # Spear-level upside (triangulated intrinsic vs the spear's own CAD price) — used by the
        # directive gates (recalibrated for the de-inflated valuation) and the scenario band.
        spear_upside = (aga_intrinsic / p_aga_cad - 1.0) if p_aga_cad > 0 else 0.0
        if p_aga_cad > 0:
            scenario_range["implied_upside_pct"] = {
                k: round((scenario_range[k] / p_aga_cad - 1.0) * 100, 1) for k in ("bear", "base", "bull")
            }

        # Consolidated, auditable valuation breakdown (Phase 4a) — additive block; the legacy
        # v4_valuation keys remain populated so the cockpit never breaks mid-migration.
        self.terminal_state["valuation_detail"] = {
            "stage": spear_detail["stage"],
            "intrinsic": round(aga_intrinsic, 3),
            "spear_price_cad": round(p_aga_cad, 3),
            "spear_upside_pct": round(spear_upside * 100, 1),
            "legs": spear_detail["legs"],
            "weights": spear_detail["weights"],
            "confidence": spear_detail["confidence"],
            "v_mkt_defined": spear_detail["v_mkt_defined"],
            "v_exploration": spear_detail["v_exploration"],
            "tq_by_project": spear_detail["tq_by_project"],
            "avg_tq": spear_detail["avg_tq"],
            "option_premium": spear_detail["option_premium"],
            "mos_ledger": spear_detail["mos_ledger"],
            "silver_vol": round(silver_vol, 3),
            "scenarios": scenario_range,
            "reconciliation": reconciliation,
            "rep_floor_basis": spear_detail.get("rep_floor_basis"),
            "ballast_anchors": ballast_anchors,   # per-name: sourced NAV vs legacy config snapshot
        }

        # ============== PHASE 5b — ADDITIVE POLYMORPHIC ARCHETYPE VALUATIONS ==============
        # Supplementary, computed in PARALLEL with the legacy valuation_detail above; it never
        # replaces any legacy logic and is isolated so it can never crash the eval loop. Each
        # portfolio name is routed by cash-flow lifecycle and valued through the triangulated
        # archetype factory, FX-normalized to CAD, with the macro-asymmetry overlay driven by
        # the live MRI/yield/vol state. The cockpit may read this block when present, or ignore it.
        try:
            with self.state_lock:
                forensic_metrics = dict(self.state_cache.get("forensic_metrics", {}))
            self.terminal_state["archetype_valuation_detail"] = self._compute_archetype_valuations(
                cfg=cfg, prices=prices, spot_ag=spot_ag, gold=gold, real_yield=real_yield,
                silver_vol=silver_vol, dynamic_aisc=dynamic_aisc,
                capital_discount_factor=capital_discount_factor, mean_peer_ev=mean_peer_ev,
                usd_to_cad=usd_to_cad, mri_score=mri_score, dxy_mom=dxy_mom,
                forensic_metrics=forensic_metrics)
        except Exception as e:
            logging.warning("Phase 5b archetype valuation block skipped (non-fatal): %s", e)
            self.terminal_state["archetype_valuation_detail"] = {"status": "error", "error": str(e), "results": {}}

        # ============== PHASE 7 — CONVICTION MODE (PRIMARY VIEW, ADDITIVE) ==============
        # The 0-10 T-Q-V Asymmetry Rating per basket, assembled from the blocks just computed.
        # Assessment-only: it consumes NO position caps, ES95 throttle, covariance shrinkage, or
        # Kelly de-leveraging (those remain in Detailed Analysis). Isolated; never crashes the loop.
        try:
            with self.state_lock:
                fm_conv = dict(self.state_cache.get("forensic_metrics", {}))
            cad_prices = {"AGA.V": p_aga_cad, "URC.TO": p_urc_cad, "GROY": p_groy_cad, "GMX.TO": p_gmx_cad}
            # The promoted EVAL set rates alongside the book (no weight, no sizing). A name with
            # no live mark yet (feed miss -> 0.0 fallback) is skipped rather than rated at zero.
            pm_all = cfg.get("portfolio_metadata", {})
            for _tk in eval_only_tickers(cfg):
                _pe = prices.get(_tk)
                if _is_pos(_pe):
                    _ccy = str((pm_all.get(_tk) or {}).get("currency", "CAD"))
                    cad_prices[_tk] = float(_pe) * _fx_to_cad(_tk, _ccy)
            self.terminal_state["conviction_mode"] = self._compute_conviction_mode(
                cfg=cfg, cad_prices=cad_prices, mri_score=mri_score,
                net_tilt=self.terminal_state.get("macro_tape", {}).get("net_tilt", "BALANCED"),
                forensic_metrics=fm_conv)
        except Exception as e:
            logging.warning("Phase 7 conviction-mode block skipped (non-fatal): %s", e)
            self.terminal_state["conviction_mode"] = {"status": "error", "error": str(e), "baskets": []}

        # Forge Phase 3: the book-level regime POSTURE (master temperature dial). Composes onto every
        # name's verdict (size cap) and the cockpit's visual temperature — never a name-level signal.
        try:
            self.terminal_state["posture"] = self._regime_posture(mri_score)
        except Exception as e:
            logging.warning("Forge posture block skipped (non-fatal): %s", e)
            self.terminal_state["posture"] = {"code": "balanced", "label": "BALANCED", "cap": 1.0}

        # Validation flywheel (Phase 1): stamp the book point-in-time into the append-only
        # valuation ledger. RECORD-only — the ledger never recomputes engine output; the cadence
        # gate inside maybe_record (daily mark + material change) keeps the ~10s loop from
        # flooding the track record. Fenced: a ledger problem can never break the eval cycle.
        try:
            self._record_valuation_ledger(cfg)
        except Exception as e:
            logging.warning("valuation ledger stamp skipped (non-fatal): %s", e)

        # Forge nervous system #1: diff this cycle into SEMANTIC events (posture flip, JSF trip,
        # directive change) -> the desk tape (ephemeral /agent/activity bus), and persist ONLY the
        # signal-worthy ones to Living Memory (the immutable audit record stays clean). Defensive.
        try:
            self._emit_cockpit_events()
        except Exception as e:
            logging.warning("Forge event detection skipped (non-fatal): %s", e)

        # H3 — the calibration FLYWHEEL turn. The capture loop only has torque if decisions FREEZE at
        # the call and CLOSE at the horizon; until now a freeze needed a council to run and a close
        # needed an agent to remember the sweep tool. Turn it on the engine's own always-on heartbeat
        # (throttled): freeze a gradeable decision for every held name that lacks one, and grade open
        # decisions at horizon / on a stance change against the live mark. Defensive; quiet in steady
        # state (a held book with live, same-stance, pre-horizon bets writes nothing).
        try:
            self._turn_calibration_flywheel()
        except Exception as e:
            logging.warning("calibration flywheel turn skipped (non-fatal): %s", e)

        # Phase 6c: surface the open-source ingestion-cache provenance (additive, read-only).
        try:
            self.terminal_state["ingestion"] = self._ingestion_status()
        except Exception as e:
            logging.warning("Phase 6c ingestion status block skipped (non-fatal): %s", e)
            self.terminal_state["ingestion"] = {"available": False, "reason": "error"}

        # 9. PORTFOLIO STATISTICS
        self.terminal_state["portfolio_stats"] = {
            "expected_shortfall_95": round(es_95 * 100, 2),
            "avg_correlation": round(avg_corr, 2),
            "vols": vols,
            "correlations": corr_matrix
        }

        # 10. ACTIVE SIZING CALCULATIONS
        limit_params = {
            "aga_price": p_aga,
            "aga_adv": aga_adv,
            "port_vol": port_vol,
            "vix": vix,
            "jsf_score": forensic_score,
            "expected_shortfall_95_pct": round(es_95 * 100, 2)
        }

        # Catalyst/momentum gate on the Kelly drift: measure the spear's (AGA.V) trailing
        # cumulative return and let it confirm or haircut the intrinsic convergence thesis before
        # sizing. Defaults to no haircut (1.0) when the returns feed is unavailable.
        cat_overlay = cfg.get("v5_guardrails", {}).get("kelly_catalyst_overlay", {})
        overlay_on = cat_overlay.get("enabled", True)
        spear_momentum = None
        if overlay_on and df_rets is not None:
            try:
                if "AGA.V" in getattr(df_rets, "columns", []):
                    lb = int(cat_overlay.get("momentum_lookback_days", 20))
                    spear_rets = df_rets["AGA.V"].dropna().tail(lb)
                    if len(spear_rets) >= 5:
                        spear_momentum = float((1.0 + spear_rets).prod() - 1.0)
            except Exception as e:
                print(f"[!] Catalyst momentum calc error: {e}")
        catalyst_factor = self.sizer.catalyst_confidence(
            spear_momentum,
            floor=cat_overlay.get("confidence_floor", 0.5),
            mom_lo=cat_overlay.get("momentum_lower", -0.10),
            mom_hi=cat_overlay.get("momentum_upper", 0.10),
        ) if overlay_on else 1.0

        sizing_res = self.sizer.calculate_sizing(
            live_portfolio_value, u_implied, vols, corr_matrix, mri_score, limit_params,
            catalyst_factor=catalyst_factor
        )

        e_target_capped = sizing_res["e_target"]
        kelly_multiple = sizing_res["kelly_multiple"]          # risk-adjusted target leverage f* (<= L_max)
        allocation_ratio = sizing_res["allocation_ratio"]      # current book vs Kelly target (>1 => over-allocated)
        macro_regime = sizing_res["macro_regime"]
        
        # 11. STRATEGIC DIRECTIVES
        # Recalibrated for the de-inflated (double-count-removed) valuation: the high-conviction gate now
        # reads the SPEAR's own triangulated intrinsic-vs-price upside (robust, intuitive) rather than the
        # structurally-lower blended portfolio edge. JSF >= 3.5 still gates aggressive signals.
        spear_hc = cfg.get("directive_thresholds", {}).get("spear_upside_high_conviction", 0.80)
        if mri_score < 40 and spear_upside > spear_hc and forensic_score >= 3.5:
            directive = "HIGH CONVICTION ZONE - DEPLOY CAPITAL"
        elif mri_score < 40 and spear_upside > spear_hc and forensic_score < 3.5:
            directive = "CONVICTION GATED - JSF DEGRADED - SCALE CONSERVATIVELY"
        elif allocation_ratio > cfg.get("v5_guardrails", {}).get("allocation_directive", {}).get("trim_ratio", 2.0):
            directive = "CAUTION - OVER-ALLOCATED - TRIM EXPOSURE"
        elif mri_score > 65:
            directive = "DEFENSIVE MODE - PROTECT CAPITAL"
        else:
            directive = "HOLD POSITION - MONITOR TAPE"

        self.terminal_state["macro_regime"] = macro_regime
        self.terminal_state["directive"] = directive
        
        # Compute blended catalyst probability from config structural weights
        cat_probs = cfg.get("catalyst_probabilities", {})
        struct_weights = cfg.get("structural_weights", {})
        blended_probability = sum(
            cat_probs.get(k, 0.50) * struct_weights.get(k, 0.0)
            for k in struct_weights
        )
        if sum(struct_weights.values()) > 0:
            blended_probability = blended_probability / sum(struct_weights.values())
        else:
            blended_probability = 0.65

        guard = cfg.get("v5_guardrails", {})
        self.terminal_state["v4_valuation"] = {
            "Total_Equity": round(live_portfolio_value, 2), 
            "E_Target": round(e_target_capped, 2),
            "PPI": round(ppi, 3), 
            "EV_Blended": round(ev_blended, 3), 
            "Implied_Upside": round(u_implied * 100, 2),
            "AGA_Intrinsic": round(aga_intrinsic, 3),
            "REP_Floor": round(spear_detail["legs"]["cost"], 3),   # reconciled cost leg (authoritative; legacy rf_floor kept only for the reconciliation baseline)
            "Cash_Runway_Months": round(cash_runway_months, 1), 
            "Kelly_Multiple": round(kelly_multiple, 2),       # risk-adjusted target leverage f* (bounded [0, L_max])
            "Kelly_Leverage": round(kelly_multiple, 4),       # explicit canonical alias (same value, finer precision)
            "allocation_ratio": round(allocation_ratio, 2),   # book vs Kelly target (>1 => over-allocated); clamped
            "BVS": round(mri_score, 1),
            "MRI": round(mri_score, 1), 
            "IS_IAI_Per_Share": round(is_iai_per_share, 3),
            "Exp_Premium_Per_Share": round(exp_per_share, 3), 
            "ROV": round(rov, 2),
            "Probability": round(blended_probability, 3),
            "Forensic_Penalty": round(forensic_penalty, 3),
            "Discovery_Premium_Factor": round(discovery_premium_factor, 3),
            "Mean_Peer_EV_oz": round(mean_peer_ev, 2),
            "ADV_Cap_CAD": sizing_res["adv_cap_cad"],
            "ADV_Cap_Percentage": sizing_res["cap_percentage"],
            "Discovery_Efficiency_Comps": round(avg_disc_cost, 2),
            "fractional_kelly_multiplier": guard.get("fractional_kelly_multiplier", 0.5),
            "position_liquidity_cap_pct": guard.get("position_liquidity_cap_pct", 0.15),
            "max_single_position_pct": guard.get("max_single_position_pct", 0.20),
            "max_spear_position_pct": guard.get("max_spear_position_pct", 0.60),
            "intrinsic_convergence_months": guard.get("intrinsic_convergence_months", 18.0),
            "ES_Throttle": sizing_res["es_throttle"],
            "usd_to_cad": round(usd_to_cad, 4),
            # Educational waterfall intermediates from the sizing engine
            "raw_kelly_leverage": sizing_res.get("raw_kelly_leverage", 0.0),
            "vix_capped_leverage": sizing_res.get("vix_capped_leverage", 0.0),
            "post_correlation_leverage": sizing_res.get("post_correlation_leverage", 0.0),
            "post_es_leverage": sizing_res.get("post_es_leverage", 0.0),
            "regime_multiplier": sizing_res.get("regime_multiplier", 1.0),
            "catalyst_factor": sizing_res.get("catalyst_factor", 1.0),
            "spear_momentum_pct": round(spear_momentum * 100, 2) if spear_momentum is not None else None,
            # Parameter-uncertainty (uncertainty-adjusted Kelly) + structured waterfall for the cockpit
            "edge_confidence": sizing_res.get("edge_confidence", 1.0),
            "mu_raw": sizing_res.get("mu_raw", 0.0),
            "mu_annualized": sizing_res.get("mu_annualized", 0.0),
            "se_mu": sizing_res.get("se_mu", 0.0),
            "sizing_waterfall": sizing_res.get("waterfall", [])
        }

        self.terminal_state["nodes"] = {
            "AGA.V": {"price": round(p_aga, 3), "role": "The Spear", "shares": self.shares.get("AGA", 0.0)}, 
            "GROY": {"price": round(p_groy, 2), "role": "Ballast", "shares": self.shares.get("GROY", 0.0)},
            "GMX.TO": {"price": round(p_gmx, 2), "role": "Ballast", "shares": self.shares.get("GMX", 0.0)}, 
            "URC.TO": {"price": round(p_urc, 2), "role": "Ballast", "shares": self.shares.get("URC", 0.0)}
        }

        # 12. MODEL HEALTH RADAR
        is_stale = (self.terminal_state["status"] == "DEGRADED_STALE")
        es_val = self.terminal_state["portfolio_stats"]["expected_shortfall_95"]
        
        health_res = self.radar.calculate_health_rating(
            forensic_score, mri_score, es_val, is_stale
        )
        
        priority_res = self.radar.generate_priorities(
            self.terminal_state["v4_valuation"], forensic_score, mri_score, es_val, p_aga
        )
        
        health_rating = health_res["health_rating"]
        tactical_ceiling = e_target_capped * (health_rating / 10.0)

        self.terminal_state["health_radar"] = {
            "health_rating": health_rating,
            "rating_desc": health_res["rating_desc"],
            "rating_color": health_res["rating_color"],
            "health_summary": health_res["health_summary"],
            "tactical_ceiling": round(tactical_ceiling, 2),
            "priorities": priority_res
        }

        # --- Consolidated integrity panel (v5.2): one top-level block the cockpit can consume to
        # render model-risk alerts (data staleness + any active forensic waivers) prominently. ---
        df_summary = self.terminal_state.get("data_freshness", {})
        active_overrides = forensic_details.get("overrides_applied", [])
        stale_feeds = [name for name, v in df_summary.get("feeds", {}).items() if v.get("stale")]
        integrity_alerts = []
        if df_summary.get("any_stale"):
            integrity_alerts.append(f"STALE DATA: {', '.join(stale_feeds) or 'feed'} past freshness threshold")
        if df_summary.get("vintage_skew_seconds", 0) > df_summary.get("skew_warn_seconds", 5400):
            integrity_alerts.append(f"VINTAGE SKEW: feeds diverge by {df_summary.get('vintage_skew_seconds', 0)/60:.0f} min")
        for ov in active_overrides:
            integrity_alerts.append(
                f"FORENSIC WAIVER ACTIVE on AGA.V {ov.get('test', '').upper()} "
                f"(expires in {ov.get('days_until_expiry', '?')}d — confirm before relying on JSF)"
            )
        self.terminal_state["integrity"] = {
            "status": self.terminal_state.get("status", "LIVE"),
            "any_stale": bool(df_summary.get("any_stale", False)),
            "stale_feeds": stale_feeds,
            "stale_feed_count": df_summary.get("stale_feed_count", 0),
            "vintage_skew_seconds": df_summary.get("vintage_skew_seconds", 0),
            "forensic_overrides_active": active_overrides,
            "forensic_override_count": len(active_overrides),
            "requires_confirmation": any(o.get("requires_confirmation") for o in active_overrides),
            "alerts": integrity_alerts,
            "all_clear": (not integrity_alerts)
        }
        if integrity_alerts:
            print("─"*75)
            for a in integrity_alerts:
                print(f" [INTEGRITY] ⚠ {a}")

        # Terminal Print
        print("\n" + "═"*75)
        print(f" COMMODITYEX MONITOR v5.1 // CORE ENGINE LOG // {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("═"*75)
        print(f" [MACRO]    MRI: {mri_score:.1f} | REGIME: {macro_regime.upper()} ")
        print(f"            DXY Mom: {dxy_mom:+.2f}% | Expected Shortfall (95%): {es_val:.2f}% ")
        print(f"            DIRECTIVE: {directive}")
        print("─"*75)
        print(f" [RADAR]    Health Rating: {health_res['health_rating']:.1f}/10.0 ({health_res['rating_desc']})")
        for p in priority_res[:2]:
            print(f"            * {p['title']}: {p['desc'][:60]}...")
        print("─"*75)
        print(f" [SYNTHESIS] Equity Value: ${live_portfolio_value:,.2f} CAD")
        print(f"            Target Capital: ${e_target_capped:,.2f} CAD | ADV Sizing Cap: ${sizing_res['adv_cap_cad']:,.2f} CAD ({sizing_res['cap_percentage']:.1f}%)")
        print(f"            Kelly Leverage f*: {kelly_multiple:.3f}x | Alloc vs Target: {allocation_ratio:.2f}x | Implied Edge: {u_implied*100:.1f}%")
        print(f"            REP Floor:      ${spear_detail['legs']['cost']:.3f} | Cash Runway:  {cash_runway_months:.1f} mo")
        print("═"*75 + "\n")

        # A1.9: the eval cycle's writes are complete — publish one atomic frame for every reader.
        self.publish_state()

    async def _run_loop(self):
        while True:
            try:
                # evaluate_master_architecture() rebuilds self.config (file defaults + confirmed
                # overrides) at the top of every cycle via _refresh_effective_config(), so the prior
                # explicit hot-reload here is now redundant.
                await self.evaluate_master_architecture()
            except Exception as e:
                print(f"\n[!] Engine Loop Error: {e}")
            await asyncio.sleep(10)


# ====================== FASTAPI SETUP ======================

engine = CommodityExMonitor()
active_websockets = []

async def websocket_broadcaster():
    last_broadcast_state = None
    while True:
        current_state_json = json.dumps(engine.published_state)   # A1.9: complete frames only
        if current_state_json != last_broadcast_state:
            dead_sockets = []
            for ws in active_websockets:
                try: 
                    await ws.send_text(current_state_json)
                except Exception: 
                    dead_sockets.append(ws)
            for ws in dead_sockets: 
                active_websockets.remove(ws)
            last_broadcast_state = current_state_json
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the worker tasks (A1.9: all supervised — a dead loop must be visible, never silent)
    import task_supervision as _tsup
    tasks = engine.start_background_tasks()
    _health = engine.terminal_state.setdefault("worker_health", {})
    engine_task = _tsup.create_supervised("eval_loop", engine._run_loop(), health=_health)
    broadcaster_task = _tsup.create_supervised("ws_broadcaster", websocket_broadcaster(), health=_health)
    yield
    engine_task.cancel()
    broadcaster_task.cancel()
    for t in tasks:
        t.cancel()
    import os
    os._exit(0)

app = FastAPI(title="CommodityEx Terminal Engine", lifespan=lifespan)

@app.get("/state")
async def get_state():
    # A1.9: serve the last COMPLETE published frame, never the live working dict mid-write.
    return engine.published_state

@app.post("/action/whatif")
async def action_whatif(body: dict):
    """Shared action spine (Iteration 2): scenario revaluation. Body: {ticker, overrides}.
    The run_valuation_whatif MCP tool, the /whatif cockpit command and a future Flutter button
    all POST here, so every face computes the identical result."""
    return engine.run_whatif(body.get("ticker"), body.get("overrides", {}))

@app.get("/ui/state")
async def get_ui_state():
    """What a frontend is currently showing — read by agents via the get_ui_context MCP tool."""
    return engine.ui.get()

@app.post("/ui/state")
async def post_ui_state(body: dict):
    """A frontend (Flutter) reports its on-screen context: {focused_ticker, active_view,
    current_scenario, visible_tickers, selected_whatif}. Partial patches are merged."""
    return engine.set_ui_state(body)

@app.post("/ui/command")
async def post_ui_command(body: dict):
    """Agents steer the frontend: {action: focus|view|scenario|highlight|alert, args:{...}}
    -> broadcast on /ws under terminal_state['ui_command']."""
    return engine.push_ui_command(body)

# ---- Ambient agent-activity bus (Claude Code hooks / agents -> live cockpit stream) ----
@app.post("/agent/activity")
async def agent_activity_post(body: dict):
    """Record what an agent is doing: {agent, kind, summary, ticker?}. kind is prompt | tool |
    response | note | proposal. Rides terminal_state['agent_activity'] (and /ws), so the cockpit
    Signals rail streams agent work with zero extra polling. Used by the .claude/hooks scripts."""
    return engine.record_agent_activity(body)

@app.get("/agent/activity")
async def agent_activity_get():
    return {"agent_activity": engine.published_state.get("agent_activity", [])}

@app.post("/pipeline/event")
async def pipeline_event_post(payload: dict):
    return engine.record_pipeline_event(payload or {})

@app.get("/pipeline")
async def pipeline_get():
    return engine.published_state.get("pipeline", {})

# ---- FMP (free-tier: fundamentals + treasury; hard-cached + daily-budget-capped, on-demand) ----
@app.get("/fmp/fundamentals")
async def fmp_fundamentals(ticker: str = ""):
    if not getattr(engine, "fmp", None):
        return {"error": "FMP unavailable (no key / module). Set FMP_API_KEY in .env."}
    if not ticker:
        return {"error": "ticker required"}
    return engine.fmp.profile(ticker)

@app.get("/fmp/treasury")
async def fmp_treasury():
    if not getattr(engine, "fmp", None):
        return {"error": "FMP unavailable (no key / module). Set FMP_API_KEY in .env."}
    return engine.fmp.treasury()

@app.get("/fmp/budget")
async def fmp_budget():
    if not getattr(engine, "fmp", None):
        return {"available": False}
    return {"available": True, "calls_remaining": engine.fmp.calls_remaining(),
            "daily_budget": engine.fmp.daily_budget}

# ---- Dynamic configuration (overlay on v5_config.json; hot-reloaded each loop) ----
def _dc_guard():
    if getattr(engine, "dconfig", None) is None:
        return {"error": "dynamic config unavailable"}
    return None

@app.get("/config/params")
async def config_params():
    """Effective tunables + which are overridden (the editable allowlist)."""
    return _dc_guard() or {"params": engine.dconfig.list_params()}

@app.post("/config/param")
async def config_set(body: dict):
    """Set an override directly — HUMAN-ONLY (audit A2.2: the proposal gate is a hard line, not
    etiquette). Only the cockpit/human channel may write directly; any agent source is refused and
    told to route through /config/propose -> the /confirm gate. {key, value} -> hot-applies."""
    if (g := _dc_guard()):
        return g
    src_id = str(body.get("source", "cockpit"))
    if not (src_id == "cockpit" or src_id.startswith("human")):
        return {"refused": True, "source": src_id,
                "error": "direct param writes are human-only — agents must use /config/propose "
                         "(propose_param_change) and the operator's /confirm gate"}
    try:
        res = engine.dconfig.set_param(body.get("key"), body.get("value"),
                                       source=body.get("source", "cockpit"), reason=body.get("reason"))
        engine._refresh_effective_config()   # file defaults + overrides -> reaches every engine provider
        return {"ok": True, **res}
    except ConfigError as e:
        return {"error": str(e)}

@app.post("/config/param/reset")
async def config_reset(body: dict):
    if (g := _dc_guard()):
        return g
    res = engine.dconfig.reset_param(body.get("key"))
    engine._refresh_effective_config()   # file defaults + overrides -> reaches every engine provider
    return {"ok": True, **res}

@app.post("/config/propose")
async def config_propose(body: dict):
    """Agents propose a change with reasoning -> pending queue (nothing applies until confirmed)."""
    if (g := _dc_guard()):
        return g
    try:
        return {"ok": True, **engine.dconfig.propose(body.get("key"), body.get("value"),
                                                     body.get("reason"), body.get("proposed_by", "agent"))}
    except ConfigError as e:
        return {"error": str(e)}

@app.get("/config/pending")
async def config_pending():
    return _dc_guard() or {"pending": engine.dconfig.pending()}

@app.post("/config/confirm")
async def config_confirm(body: dict):
    """Human confirms a pending change -> applied + hot-reloaded."""
    if (g := _dc_guard()):
        return g
    try:
        res = engine.dconfig.confirm(int(body.get("id")), source=body.get("source", "cockpit"))
        engine._refresh_effective_config()   # file defaults + overrides -> reaches every engine provider
        return {"ok": True, **res}
    except (ConfigError, TypeError, ValueError) as e:
        return {"error": str(e)}

@app.post("/config/reject")
async def config_reject(body: dict):
    if (g := _dc_guard()):
        return g
    return {"ok": True, **engine.dconfig.reject(int(body.get("id")))}

@app.get("/config/scenarios")
async def config_scenarios():
    return _dc_guard() or {"scenarios": engine.dconfig.list_scenarios()}

@app.post("/config/scenario")
async def config_scenario(body: dict):
    """Save a named what-if scenario {name, overrides}. Loadable via /whatif <TICKER> <name>."""
    if (g := _dc_guard()):
        return g
    try:
        return {"ok": True, **engine.dconfig.save_scenario(body.get("name"), body.get("overrides"),
                                                           source=body.get("source", "cockpit"))}
    except ConfigError as e:
        return {"error": str(e)}

# ---- Research dossiers / decision memos (read-only; backs the cockpit Dossier tab) ----
@app.get("/decisions")
async def list_decisions(limit: int = 50):
    """Index of research dossiers in data/decisions/*.md (newest first). Agents write these via
    the /dossier skill; the cockpit renders them. Read-only."""
    return engine.list_decisions(limit)

@app.get("/decisions/item")
async def read_decision(name: str = ""):
    """Full markdown body of one dossier by file name (path-traversal-guarded). Read-only."""
    return engine.read_decision(name)

@app.post("/decisions/delete")
async def delete_decision(payload: dict):
    """Delete one dossier by file name (path-traversal-guarded)."""
    return engine.delete_decision((payload or {}).get("name", ""))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    await websocket.send_text(json.dumps(engine.terminal_state))
    try:
        while True: 
            await websocket.receive_text()
    except:
        if websocket in active_websockets: 
            active_websockets.remove(websocket)

if __name__ == "__main__":
    # access_log off + warning level: the ENGINE pane shows the capital/risk summary the loop
    # prints, not a wall of "GET /state 200 OK" — the cockpit polls several times a second.
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False, log_level="warning")