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
            except:
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
    except:
        pass
    return default_dict

# ========================================================
# v5 MODULAR ENGINE ARCHITECTURE
# ========================================================

class MacroRegimeEngine:
    def __init__(self, config_path):
        self.config_path = config_path
        
    def get_config(self):
        with open(self.config_path, "r") as f:
            return json.load(f)

    async def fetch_macro_data(self):
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
                        import urllib.request
                        import pandas as pd
                        import io
                        import numpy as np
                        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=5) as response:
                            csv_data = response.read().decode('utf-8')
                        df = pd.read_csv(io.StringIO(csv_data))
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
            _save_to_cache("macro_data", {
                "DGS10": result[0], "DGS30": result[1], "BAMLH0A0HYM2": result[2],
                "TEDRATE": result[3], "FEDFUNDS": result[4], "VIXCLS": result[5]
            })
        except Exception as e:
            print(f"[!] fetch_macro_data error: {e}")
            status = "DEGRADED_STALE"
            cached = _load_from_cache("macro_data", {
                "DGS10": 4.45, "DGS30": 4.98, "BAMLH0A0HYM2": 2.72,
                "TEDRATE": 0.05, # 5 bps neutral SOFR - DGS3MO spread fallback
                "FEDFUNDS": 4.33, "VIXCLS": 15.74
            })
            result = [
                cached["DGS10"], cached["DGS30"], cached["BAMLH0A0HYM2"],
                cached["TEDRATE"], cached["FEDFUNDS"], cached["VIXCLS"]
            ]
        return result, status

    async def fetch_real_yield(self):
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
                        import urllib.request
                        import pandas as pd
                        import io
                        import numpy as np
                        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req, timeout=5) as response:
                            csv_data = response.read().decode('utf-8')
                        df = pd.read_csv(io.StringIO(csv_data))
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
            _save_to_cache("real_yield", {"value": result})
        except Exception as e:
            print(f"[!] fetch_real_yield error: {e}")
            status = "DEGRADED_STALE"
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

    def calculate_mri(self, metrics, spot_ag, real_yield, copper, gold, dxy_mom=0.0):
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

            # 1. Liquidity & FX Score
            liq_score = (
                norm(dxy - 100, -5, 8) * 0.30 + 
                norm(ted, 0.1, 0.9) * 0.20 + 
                norm(real_yield, 0.5, 3.5) * 0.30 +
                norm(dxy_mom, -2.0, 2.0) * 0.20
            )
            
            # 2. Yield & Rate Curve Score
            yield_score = (
                norm(y30 - y10, -0.5, 1.5) * 0.50 + 
                norm(y10, 3.0, 5.5) * 0.50
            )
            
            # 3. Volatility & Systemic Stress Score
            vol_score = (
                norm(vix, 12, 35) * 0.50 + 
                norm(spreads, 2, 7) * 0.50
            )
            
            # 4. Physical Commodity Regimes (Re-calibrated for late May 2026 prices)
            cu_au_ratio = copper / gold if gold > 0 else 0.00136
            comm_score = (
                norm(cu_au_ratio, 0.0010, 0.0018) * 0.60 + 
                norm(spot_ag, 50.0, 100.0) * 0.40
            )
            
            # 5. Speculative Capitulation Score (Config-driven Normalization)
            cftc_cfg = self.get_config().get("cftc_params", {
                "norm_low": -15000,
                "norm_high": 85000
            })
            sentiment_score = norm(cftc_net, cftc_cfg["norm_low"], cftc_cfg["norm_high"])

            # Blended MRI Index
            mri = (
                (liq_score * 0.30) + 
                (yield_score * 0.20) + 
                (vol_score * 0.20) + 
                (comm_score * 0.15) + 
                (sentiment_score * 0.15)
            )
            return round(max(0, min(100, mri)), 1)
        except Exception as e:
            print(f"[!] MRI calculation error: {e}")
            return 45.0


class PeerEngine:
    def __init__(self, config_path):
        self.config_path = config_path
        self.cached_mean_peer_ev_oz = 2.50
        self.peer_data_cache = {}

    def get_config(self):
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
                    
                    # Pull Volume metrics to calculate Average Daily Volume (ADV) in CAD
                    avg_vol = info.get('averageVolume10Day') or info.get('averageVolume') or 50000
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
                    raw_oz = reg.get("resources_oz_AgEq", 100_000_000)
                    mi_pct = reg.get("measured_indicated_pct", 0.50)
                    j_risk = reg.get("jurisdiction_risk", 0.20)
                    stage = reg.get("development_stage", "PEA")
                    disc_cost = reg.get("historical_discovery_cost_oz", 0.50)

                    # Calculate effective confidence-weighted resources
                    effective_oz = raw_oz * (mi_pct * mi_weight + (1.0 - mi_pct) * inf_weight)
                    
                    if effective_oz > 0 and normalized_ev > 0:
                        raw_ev_oz = normalized_ev / effective_oz
                        
                        risk_discount = 1.0 - j_risk
                        stage_multiplier = stage_multipliers.get(stage, 1.0)
                        adjusted_ev_oz = raw_ev_oz * risk_discount * stage_multiplier
                        
                        results[t] = {
                            "raw_ev_oz": raw_ev_oz,
                            "adjusted_ev_oz": adjusted_ev_oz,
                            "adv_cad": adv_cad,
                            "discovery_cost": disc_cost,
                            "effective_oz": effective_oz,
                            "price": price,
                            "jurisdiction_risk": j_risk,
                            "stage": stage
                        }
                except Exception as e:
                    print(f"[!] Failed to fetch/parse peer {t}: {e}")

            if not results:
                return 2.50, {}, 0.48

            # Liquidity weighting comps
            weighted_ev_oz = 0.0
            sum_weights = 0.0
            sum_disc_cost = 0.0
            
            for t, data in results.items():
                liq_weight = data["adv_cad"] / total_adv if total_adv > 0 else 1.0 / len(results)
                weighted_ev_oz += data["adjusted_ev_oz"] * liq_weight
                sum_weights += liq_weight
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
                
                current_shares = t.info.get('sharesOutstanding') or 208600000

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
                    "cash_t0": cash_t0
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

    def calculate_jsf_score(self, ticker, cash, monthly_burn, sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense, cfo_t0=None, cfo_t1=None, cash_t0=None):
        cfg = self.get_config()
        metadata = cfg.get("portfolio_metadata", {}).get(ticker, {})
        asset_type = metadata.get("type", "explorer")

        score = 0.0
        details = {}
        
        # 1. Cash Runway Test
        runway = cash / monthly_burn if monthly_burn > 0 else 99.0
        runway_pass = runway >= 18.0
        if runway_pass:
            score += 1.0
            details["runway"] = {"pass": True, "value": runway, "desc": f"Runway >= 18 mo ({runway:.1f} mo)"}
        else:
            details["runway"] = {"pass": False, "value": runway, "desc": f"Short Runway ({runway:.1f} mo)"}
            
        # 2. Accrual / Burn Test
        cba = 0.0
        if asset_type == "explorer":
            # Cash Burn Acceleration (CBA)
            total_cash = cash_t0 if cash_t0 is not None else cash
            curr_burn = -cfo_t0 if cfo_t0 is not None else (monthly_burn * 3.0)
            prev_burn = -cfo_t1 if cfo_t1 is not None else curr_burn
            cba = (curr_burn - prev_burn) / total_cash if total_cash > 0 else 0.0
            
            cba_pass = cba <= 0.15
            overrides = cfg.get("forensic_overrides", {}).get(ticker, {})
            if overrides.get("cba_insulated", False):
                cba_pass = True
                
            if cba_pass:
                score += 1.0
                desc = "CBA <= 15%" if not overrides.get("cba_insulated", False) else "CBA Insulated"
                details["accrual"] = {"pass": True, "value": cba, "desc": f"{desc} ({cba*100:.1f}%)"}
            else:
                details["accrual"] = {"pass": False, "value": cba, "desc": f"Burn accelerating ({cba*100:.1f}%)"}
        else:
            # Standard Sloan Ratio Check (Integrates both CFO and BS Accruals for high safety)
            sloan_pass = (sloan_cfo < 0.05) and (sloan_bs < 0.05)
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
        
        dilution_pass = dilution < 0.02
        overrides = cfg.get("forensic_overrides", {}).get(ticker, {})
        if overrides.get("dilution_insulated", False):
            dilution_pass = True
            
        if dilution_pass:
            score += 1.0
            desc = "Dilution < 2% QoQ" if not overrides.get("dilution_insulated", False) else "Dilution Insulated"
            details["dilution"] = {"pass": True, "value": dilution, "desc": f"{desc} ({dilution*100:.1f}%)"}
        else:
            details["dilution"] = {"pass": False, "value": dilution, "desc": f"Share count expanded ({dilution*100:.1f}%)"}

        # 4. SG&A Drag Test
        quarterly_burn = monthly_burn * 3.0
        sga_ratio = sga_expense / quarterly_burn if quarterly_burn > 0 else 0.0
        sga_pass = sga_ratio < 0.30
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
        
        return score, penalty_factor, details


class ValuationEngine:
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
        with open(self.config_path, "r") as f:
            return json.load(f)

    def calculate_rep_floor(self, shares_outstanding=None):
        cfg = self.get_config()
        shares = shares_outstanding if shares_outstanding is not None else cfg["aga_shares_out"]
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        infra_component = rf["permitting_infra_premium_m"] * 1_000_000
        
        buckets = cfg.get("project_buckets_oz_AgEq", {})
        target_mi_pct = cfg.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
        
        # Enforce symmetric inferred ounces haircut (50% discount to Inferred)
        total_effective_oz = 0.0
        for proj, oz in buckets.items():
            mi_pct = target_mi_pct.get(proj, 0.50)
            measured_indicated_oz = oz * mi_pct
            inferred_oz = oz * (1.0 - mi_pct)
            effective_oz = (measured_indicated_oz * 1.0) + (inferred_oz * 0.50)
            total_effective_oz += effective_oz
            
        resource_component = total_effective_oz * rf["stressed_resource_per_oz"]
        total_rep_value = cash_component + resource_component + infra_component
        rep_floor = (total_rep_value * rf["conservatism_scalar"]) / shares
        return rep_floor

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
        
        jurisdiction_uplift = 1.35 if spot_ag > 50.0 else 1.15
        
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


class HealthRadarEngine:
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
        with open(self.config_path, "r") as f:
            return json.load(f)

    def calculate_health_rating(self, jsf_score, mri_score, expected_shortfall_95, is_stale):
        cfg = self.get_config()
        radar_cfg = cfg.get("health_radar", {})
        
        forensics_mult = radar_cfg.get("forensics_multiplier", 1.25)
        macro_mult = radar_cfg.get("macro_multiplier", 1.5)
        stale_penalty = radar_cfg.get("stale_penalty", 2.0)
        es_thresholds = radar_cfg.get("es_thresholds", [
            {"threshold": -10.0, "penalty": 1.0},
            {"threshold": -5.0, "penalty": 0.5}
        ])

        score = 10.0
        
        # 1. Forensics penalty
        score -= (4.0 - jsf_score) * forensics_mult
        
        # 2. Macro penalty
        score -= (mri_score / 100.0) * macro_mult
        
        # 3. Pipeline cache penalty
        if is_stale:
            score -= stale_penalty
            
        # 4. Tail Risk expected shortfall penalty
        es_penalty = 0.0
        for item in es_thresholds:
            if expected_shortfall_95 <= item["threshold"]:
                es_penalty = max(es_penalty, item["penalty"])
        
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
        kelly = val_data.get("Kelly_Multiple", 1.0)
        adv_cap = val_data.get("ADV_Cap_CAD", 0.0)
        adv_cap_pct = val_data.get("ADV_Cap_Percentage", 15.0)
        aga_intrinsic = val_data.get("AGA_Intrinsic", 4.18)
        
        priorities = []
        
        # Priority 1: Valuation / Spear Arbitrage
        if implied_edge > 50:
            spear_upside = (aga_intrinsic / p_aga - 1.0) * 100 if p_aga > 0 else 0.0
            priorities.append({
                "icon": "shopping_cart_outlined",
                "color": "green",
                "title": "EXPLOIT SPEAR ARBITRAGE",
                "desc": f"AGA.V market price (${p_aga:.2f}) is trading at a massive discount to Intrinsic (${aga_intrinsic:.2f}) with {spear_upside:.0f}% raw upside, driving a portfolio-wide blended Implied Edge of {implied_edge:.0f}%."
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
        if kelly > 1.2:
            priorities.append({
                "icon": "balance_outlined",
                "color": "orange",
                "title": "TRIM OVERALLOCATION DRAG",
                "desc": f"Kelly Multiple ({kelly:.2f}x) indicates overallocation relative to risk ceilings. Trim barbell assets to reclaim capital buffer."
            })
        else:
            priorities.append({
                "icon": "check_circle_outline",
                "color": "green",
                "title": "ALLOCATIONS WITHIN RISK BOUNDS",
                "desc": f"Current allocations are safe at {kelly:.2f}x Kelly target. No urgent trim directives active."
            })
            
        return priorities


class PortfolioSizer:
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
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
            corr_matrix = df.corr().to_dict()
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

    async def get_liquidity_cap(self, ticker, fallback_volume=150000):
        def _fetch():
            try:
                t = yf.Ticker(ticker)
                info = t.info
                adv_shares = info.get('averageVolume10Day') or info.get('averageVolume') or fallback_volume
                return int(adv_shares)
            except Exception:
                return int(fallback_volume)
        return await asyncio.to_thread(_fetch)
    def calculate_sizing(self, live_portfolio_value, u_implied, volatilities, corr_matrix, mri_score, limit_params):
        cfg = self.get_config()
        guard = cfg.get("v5_guardrails", {})
        
        # Load risk parameters from config
        fractional_kelly = guard.get("fractional_kelly_multiplier", 0.5)
        pos_liq_cap = guard.get("position_liquidity_cap_pct", 0.15)
        max_single_pos = guard.get("max_single_position_pct", 0.20)
        max_spear_pos = guard.get("max_spear_position_pct", 0.60)
        
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
        port_vol = limit_params.get("port_vol", 0.40)
        port_variance = max(0.04, port_vol ** 2)
        raw_portfolio_kelly = (u_implied / port_variance) * fractional_kelly
        
        # Max aggregate leverage allowed (VIX-dampened)
        max_leverage_allowed = 1.5
        vix = limit_params.get("vix", 16.5)
        if vix > 15.0:
            max_leverage_allowed = max(0.60, 1.5 - ((vix - 15.0) * 0.045))
            
        target_portfolio_leverage = min(raw_portfolio_kelly, max_leverage_allowed) * correlation_penalty
        
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
        # Asset Weights inside the Barbell Portfolio (synchronized with evaluate_master_architecture)
        weights = {
            "AGA.V": 0.60,  # The Spear
            "GROY": 0.15,   # Ballast
            "URC.TO": 0.15,  # Ballast
            "GMX.TO": 0.10   # Ballast
        }
        
        # A. CONSTRAINT 1: Single Position Percentage Cap (max_single_position_pct)
        max_by_single_pos_cap = float('inf')
        for ticker, w in weights.items():
            limit_pct = max_spear_pos if ticker == "AGA.V" else max_single_pos
            limit_flex = limit_pct * flexibility_mult
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
                
        # Kelly Multiple represents the actual portfolio value vs. target leveraged sizer
        kelly_multiple = live_portfolio_value / e_target_final if e_target_final > 100 else 1.0
        
        return {
            "e_target": round(e_target_final, 2),
            "kelly_multiple": round(kelly_multiple, 2),
            "macro_regime": macro_regime,
            "target_pct": round((e_target_final / live_portfolio_value) * 100 if live_portfolio_value > 0 else 0.0, 2),
            "adv_cap_cad": round(adv_cap_cad, 2),
            "avg_ballast_corr": round(avg_ballast_corr, 2),
            "correlation_penalty": round(correlation_penalty, 3),
            "cap_percentage": round(cap_percentage * 100, 2),
            "active_ceiling_triggered": active_ceiling_triggered,
            "max_single_position_value_cap": round(live_portfolio_value * max_spear_pos * flexibility_mult, 2)
        }


# ========================================================
# MAIN COMMODITYEX MONITOR SYSTEM (v5)
# ========================================================

class CommodityExMonitor:
    def __init__(self, host='127.0.0.1', port=4002, client_id=1):
        self.host = host
        self.port = port
        self.client_id = client_id
        
        self.config_path = "v5_config.json"
        
        # Instantiate v5 Core Engine Modules
        self.macro_engine = MacroRegimeEngine(self.config_path)
        self.peer_engine = PeerEngine(self.config_path)
        self.forensic_engine = ForensicEngine(self.config_path)
        self.valuation_engine = ValuationEngine(self.config_path)
        self.sizer = PortfolioSizer(self.config_path)
        self.radar = HealthRadarEngine(self.config_path)

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
            "mean_peer_ev": 65.0,
            "peer_details": [],
            "avg_disc_cost": 4.5,
            
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
                "USDCAD=X": 1.38
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
            "es_95": 5.2,
            "port_vol": 0.40,
            "avg_corr": 0.45,
            
            "aga_adv": 150000
        }

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
                    "calculation": "Aggregates raw cash treasury, heavily discounted inferred/measured ounces (e.g., symmetric 50% inferred haircut), and permitting/infrastructure sunk costs, divided by shares outstanding.",
                    "actionability": "Serves as the ultimate downside support level for AGA.V. Buying near or below the REP Floor provides maximal margin of safety for the spear position.",
                    "relationships": "Forms the baseline component (15% weight) of the AGA Intrinsic value.",
                    "signals": "Green: Price < REP Floor (Deep value). Orange: Price near REP Floor. Red: Price significantly above REP Floor.",
                    "related_metrics": ["AGA.V Intrinsic"]
                },
                "ES95": {
                    "definition": "Expected Shortfall at 95% Confidence. Measures the average expected loss in the worst 5% of portfolio return scenarios.",
                    "calculation": "Derived from 60-day historical returns of the barbell components (AGA.V, GROY, URC.TO, GMX.TO) weighted by current allocation.",
                    "actionability": "Used to monitor tail risk. High ES95 (>5%) triggers penalties in the Health Rating and forces a reduction in aggregate portfolio leverage.",
                    "relationships": "Impacts Health Rating; interacts with Portfolio Volatility and Kelly Multiple.",
                    "signals": "Green (<5%): Contained tail risk. Orange (5-10%): Elevated tail risk. Red (>10%): Severe downside exposure.",
                    "related_metrics": ["Health Rating", "VIX"]
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
                    "definition": "Real Option Value. The convex optionality premium assigned to silver assets due to their nonlinear response to monetary debasement.",
                    "calculation": "Base premium (1.18x) modulated continuously by negative real yields (premium scales as yields drop <1%) and silver price volatility.",
                    "actionability": "Accounts for the 'monetary battery' characteristic of the barbell. Higher ROV justifies paying a premium over pure discounted cash flows during financial repression.",
                    "relationships": "Influenced by Real Yields and VIX/Silver Vol; contributes 15% weight to AGA Intrinsic.",
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
                    "actionability": "Quantifies the speculative torque of AGA.V. When high, justifies accumulating prior to resource updates; when compressed by macro stress, indicates the market will not reward drill results.",
                    "relationships": "Multiplies peer EV/oz in the IS-IAI calculation; constrained by MRI.",
                    "signals": "Green: Market rewarding discovery. Orange: Neutral. Red: Market ignoring drill results (macro cap active).",
                    "related_metrics": ["MRI", "Spot_Ag", "AISC Uplift", "IS-IAI"]
                },
                "IS-IAI": {
                    "definition": "In-Situ Inferred & Indicated Valuation. The core asset value based on peer multiples and expected resource recoveries.",
                    "calculation": "Effective ounces * Peer EV/oz * Discovery Premium * Jurisdiction Uplift * Recovery * Capital Discount.",
                    "actionability": "The primary valuation engine (70% weight) for AGA.V Intrinsic. Represents what the asset is worth based on comparable market transactions and geological confidence.",
                    "relationships": "Requires Peer EV/oz, Discovery Premium, and macro Capital Discount Factor; modulated by JSF Forensic Penalty.",
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
                    "definition": "Cash Burn Acceleration. Measures if cash outflow is expanding faster than remaining cash buffers.",
                    "calculation": "(Current Quarter Burn - Prior Quarter Burn) / Total Cash, where Burn = -CFO.",
                    "actionability": "High CBA (>15%) warns of explosive cash drain. Automatically triggers account stress mitigation protocols, capping buys and preserving capital.",
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
                }
            }
        }

    def start_background_tasks(self):
        self.tasks = [
            asyncio.create_task(self._prices_worker()),
            asyncio.create_task(self._macro_worker()),
            asyncio.create_task(self._cftc_worker()),
            asyncio.create_task(self._comps_worker())
        ]
        return self.tasks

    def _load_shares_from_csv(self, force=False):
        holdings_path = "holdings-report-2026-05-24.csv"
        if not os.path.exists(holdings_path):
            return False
        try:
            mtime = os.path.getmtime(holdings_path)
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
            "URC.TO": 4.82, "SI=F": 74.8, "CL=F": 89.5, "DX-Y.NYB": 99.0
        }
        return fallbacks.get(ticker, 0.0)

    # ==================== DECOUPLED BACKGROUND WORKERS ====================

    async def _prices_worker(self):
        while True:
            try:
                # 1. Fetch Prices
                def get_market_data():
                    new_prices = {}
                    tickers = ["CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO", "USDCAD=X"]
                    for t in tickers:
                        try:
                            hist = yf.Ticker(t).history(period="10d")
                            if not hist.empty:
                                new_prices[t] = float(hist['Close'].iloc[-1])
                            else:
                                raise Exception(f"Empty hist for {t}")
                        except Exception as e:
                            print(f"[Prices Worker] yfinance price fetch error for {t}: {e}")
                            new_prices[t] = self._get_fallback_price(t)
                    return new_prices

                prices = await asyncio.to_thread(get_market_data)
                _save_to_cache("prices", prices)
                prices_status = "LIVE"
                
                # 2. Fetch Copper and Gold
                copper, gold = 4.2, 2350.0
                try:
                    def fetch_cg():
                        cu = yf.Ticker("HG=F").history(period="5d")
                        au = yf.Ticker("GC=F").history(period="5d")
                        c_val = float(cu['Close'].iloc[-1]) if not cu.empty else 4.2
                        g_val = float(au['Close'].iloc[-1]) if not au.empty else 2350.0
                        return c_val, g_val
                    copper, gold = await asyncio.to_thread(fetch_cg)
                    _save_to_cache("copper_gold", {"copper": copper, "gold": gold})
                except Exception as e:
                    print(f"[Prices Worker] Copper/Gold fetch error: {e}")
                    cached = _load_from_cache("copper_gold", {"copper": 4.2, "gold": 2350.0})
                    copper, gold = cached["copper"], cached["gold"]
                
                # 3. Silver Term Structure
                m1_price, m180_price = 0.0, 0.0
                try:
                    def fetch_ts():
                        m1_ticker = "SI=F"
                        m1_hist = yf.Ticker(m1_ticker).history(period="1d")
                        m1_p = float(m1_hist['Close'].iloc[-1]) if not m1_hist.empty else 74.8
                        
                        import datetime
                        now = datetime.datetime.now()
                        curr_month = now.month
                        curr_year_short = now.year % 100
                        if curr_month in [1, 2]: code, yr = "N", curr_year_short
                        elif curr_month in [3, 4, 5]: code, yr = "Z", curr_year_short
                        elif curr_month in [6, 7, 8]: code, yr = "H", curr_year_short + 1
                        else: code, yr = "N", curr_year_short + 1
                            
                        m180_ticker = f"SI{code}{yr:02d}.CMX"
                        m180_hist = yf.Ticker(m180_ticker).history(period="1d")
                        m180_p = float(m180_hist['Close'].iloc[-1]) if not m180_hist.empty else m1_p
                        return m1_p, m180_p
                    m1_price, m180_price = await asyncio.to_thread(fetch_ts)
                except Exception as e:
                    print(f"[Prices Worker] Term structure error: {e}")
                    m1_price, m180_price = prices.get("SI=F", 74.8), prices.get("SI=F", 74.8)

                # 4. Silver ADV volume
                aga_adv = 150000
                try:
                    aga_adv = await self.sizer.get_liquidity_cap("AGA.V")
                except Exception as e:
                    print(f"[Prices Worker] Liquidity cap error: {e}")

                # Update State Cache
                with self.state_lock:
                    self.state_cache["prices"] = prices
                    self.state_cache["prices_status"] = prices_status
                    self.state_cache["usd_to_cad"] = prices.get("USDCAD=X", 1.38)
                    self.state_cache["copper"] = copper
                    self.state_cache["gold"] = gold
                    self.state_cache["m1_price"] = m1_price
                    self.state_cache["m180_price"] = m180_price
                    self.state_cache["aga_adv"] = aga_adv
                    
                print(f"[*] [Prices Worker] Synchronized live prices successfully.")
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
                        
                        self.state_cache["real_yield"] = real_yield
                        self.state_cache["ry_status"] = ry_status
                        
                        self.state_cache["dxy_mom"] = dxy_mom
                        self.state_cache["current_dxy"] = current_dxy
                        self.state_cache["dxy_status"] = dxy_status
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
                # 1. Peer Comps ev/oz
                mean_peer_ev, peer_details, avg_disc_cost = await self.peer_engine.fetch_and_calculate_weighted_comps()
                
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
                
                es_95 = 0.052
                port_vol = 0.40
                avg_corr = 0.45
                if df_rets is not None and not df_rets.empty:
                    weights = np.array([0.60, 0.15, 0.10, 0.15])
                    es_95 = self.sizer.calculate_expected_shortfall(df_rets, weights)
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

    async def evaluate_master_architecture(self, force_macro=False):
        cfg = self.peer_engine.get_config()

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
            es_95 = self.state_cache.get("es_95", 0.052)
            port_vol = self.state_cache.get("port_vol", 0.40)
            avg_corr = self.state_cache.get("avg_corr", 0.45)
            
            aga_adv = self.state_cache["aga_adv"]

        self.cached_mean_peer_ev_oz = mean_peer_ev

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

        # 3. PORTFOLIO EQUITY VALUE CALCULATION
        live_portfolio_value = (
            self.shares.get('AGA', 0) * p_aga + self.shares.get('URC', 0) * p_urc +
            self.shares.get('GMX', 0) * p_gmx + self.shares.get('GROY', 0) * p_groy * usd_to_cad +
            self.shares.get('UROY_CALL', 0) * 100.0 * self.uroy_call_price * usd_to_cad
        )
        if live_portfolio_value < 1000: live_portfolio_value = cfg.get("target_capital", 5360.0)

        # 4. SET LIVE VS DEGRADED STATUS (Including CFTC status)
        if "DEGRADED_STALE" in [macro_status, prices_status, dxy_status, ry_status, cftc_status]:
            self.terminal_state["status"] = "DEGRADED_STALE"
        else:
            self.terminal_state["status"] = "LIVE"

        mri_score = self.macro_engine.calculate_mri(self.terminal_state["metrics"], spot_ag, real_yield, copper, gold, dxy_mom)
        self.terminal_state["mri"] = mri_score

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
        else:
            sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense = 0.021, 0.024, 208600000, 208600000, 450000
            cfo_t0, cfo_t1, cash_t0 = None, None, None

        forensic_score, forensic_penalty, forensic_details = self.forensic_engine.calculate_jsf_score(
            "AGA.V", cash_component, monthly_burn,
            sloan_cfo, sloan_bs, shares_t0, shares_t1, sga_expense,
            cfo_t0=cfo_t0, cfo_t1=cfo_t1, cash_t0=cash_t0
        )
        
        self.terminal_state["forensics"] = {
            "jsf_score": forensic_score,
            "penalty_factor": round(forensic_penalty, 3),
            "runway": round(cash_runway_months, 1),
            "sloan_cfo": round(sloan_cfo, 4),
            "sloan_bs": round(sloan_bs, 4),
            "details": forensic_details
        }

        # 6. DYNAMIC AISC AND VALUATION MARGINS
        base_aisc = cfg["dynamic_discovery_v5"]["estimated_industry_aisc_2026"]
        dynamic_aisc = base_aisc + max(0, wti_price - 80.0) * 0.15
        
        phi_margin = max(0.58, (spot_ag - dynamic_aisc) / spot_ag) if spot_ag > dynamic_aisc else 0.05
        commodity_leverage = spot_ag / dynamic_aisc if dynamic_aisc > 0 else 1.0
        exp_scalar = cfg["dynamic_discovery_v5"].get("explorer_re_rating_scalar", 1.68)
        
        raw_factor = commodity_leverage * phi_margin * exp_scalar
        spot_dev = max(0, (spot_ag - 76.5) / 50)
        ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - mri_score / 100)
        discovery_premium_factor = max(0.50, min(raw_factor, ceiling))

        rov = self.valuation_engine.calculate_continuous_rov(real_yield, spot_ag, cfg.get("rov_default", 1.18))

        capital_discount_factor = 1.0
        if y30 > 4.0:
            capital_discount_factor = max(0.40, 1.0 - ((y30 - 4.0) * 0.12))

        # 7. TERM STRUCTURE STRESS PREMIUMS
        if m1_price > 0 and m180_price > 0 and m1_price > m180_price:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": True, "status": "LIVE"}
            uplift_premium = min(0.25, max(0.0, (m1_price - m180_price) / m1_price) * 5.0)
        else:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": False, "status": "LIVE"}
            uplift_premium = 0.0

        is_iai_per_share, jurisdiction_uplift = self.valuation_engine.calculate_is_iai(
            mean_peer_ev, discovery_premium_factor, spot_ag, capital_discount_factor
        )
        
        jurisdiction_uplift = jurisdiction_uplift * (1.0 + uplift_premium)

        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (
            exp.get("expected_future_oz", 0) * mean_peer_ev * 
            jurisdiction_uplift * exp.get("probability_of_discovery", 0.25)
        )
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)

        # 8. INTRINSIC AND PORTFOLIO VALUATIONS
        aga_intrinsic = (
            (0.15 * rf_floor) + 
            (0.70 * is_iai_per_share * forensic_penalty) + 
            (0.15 * rov) + 
            exp_per_share
        )

        ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)

        ballast_cfg = cfg.get("ballast_multiples", {"URC.TO": 1.15, "GROY": 1.15, "GMX.TO": 1.20})
        urc_base = ballast_cfg.get("URC.TO", 1.15)
        groy_base = ballast_cfg.get("GROY", 1.15)
        gmx_base = ballast_cfg.get("GMX.TO", 1.20)
        
        urc_pen = 1.0 - min(0.30, max(0, ballast_sloans.get("URC.TO", 0.0) - 0.05) * 2.0)
        groy_pen = 1.0 - min(0.30, max(0, ballast_sloans.get("GROY", 0.0) - 0.05) * 2.0)
        gmx_pen = 1.0 - min(0.30, max(0, ballast_sloans.get("GMX.TO", 0.0) - 0.05) * 2.0)

        ev_blended = (
            (0.60 * aga_intrinsic) + 
            (0.15 * p_urc * urc_base * urc_pen) + 
            (0.15 * p_groy * groy_base * groy_pen) + 
            (0.10 * p_gmx * gmx_base * gmx_pen)
        )
        u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

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
            "jsf_score": forensic_score
        }

        sizing_res = self.sizer.calculate_sizing(
            live_portfolio_value, u_implied, vols, corr_matrix, mri_score, limit_params
        )

        e_target_capped = sizing_res["e_target"]
        kelly_multiple = sizing_res["kelly_multiple"]
        macro_regime = sizing_res["macro_regime"]
        
        # 11. STRATEGIC DIRECTIVES
        # Gate expansion with JSF >= 3.5 to prevent aggressive signals when forensic quality is degraded
        if mri_score < 40 and u_implied > 0.80 and forensic_score >= 3.5:
            directive = "HIGH CONVICTION ZONE - DEPLOY CAPITAL"
        elif mri_score < 40 and u_implied > 0.80 and forensic_score < 3.5:
            directive = "CONVICTION GATED - JSF DEGRADED - SCALE CONSERVATIVELY"
        elif kelly_multiple > 1.5:
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
            "REP_Floor": round(rf_floor, 3),
            "Cash_Runway_Months": round(cash_runway_months, 1), 
            "Kelly_Multiple": round(kelly_multiple, 2),
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
            "usd_to_cad": round(usd_to_cad, 4)
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
        print(f"            Kelly Multiple: {kelly_multiple:.2f}x | Implied Edge: {u_implied*100:.1f}%")
        print(f"            REP Floor:      ${rf_floor:.3f} | Cash Runway:  {cash_runway_months:.1f} mo")
        print("═"*75 + "\n")

    async def _run_loop(self):
        while True:
            try:
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
        current_state_json = json.dumps(engine.terminal_state)
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
    # Start the worker tasks
    tasks = engine.start_background_tasks()
    engine_task = asyncio.create_task(engine._run_loop())
    broadcaster_task = asyncio.create_task(websocket_broadcaster())
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
    return engine.terminal_state

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
    uvicorn.run(app, host="127.0.0.1", port=8000)