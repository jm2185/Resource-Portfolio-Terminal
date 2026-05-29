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
                    return fallback_val
                
                return [
                    fetch_raw_fred("DGS10", 4.35), fetch_raw_fred("DGS30", 4.65),
                    fetch_raw_fred("BAMLH0A0HYM2", 2.71), fetch_raw_fred("TEDRATE", 0.35),
                    fetch_raw_fred("FEDFUNDS", 4.33), fetch_raw_fred("VIXCLS", 16.5)
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
                "DGS10": 4.35, "DGS30": 4.65, "BAMLH0A0HYM2": 2.71,
                "TEDRATE": 0.35, "FEDFUNDS": 4.33, "VIXCLS": 16.5
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
            
            # 4. Physical Commodity Regimes
            cu_au_ratio = copper / gold if gold > 0 else 0.0018
            comm_score = (
                norm(cu_au_ratio, 0.0014, 0.0022) * 0.60 + 
                norm(spot_ag / 30, 0.8, 1.4) * 0.40
            )
            
            # 5. Speculative Capitulation Score
            sentiment_score = norm(cftc_net, -15000, 85000)

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
    def __init__(self, config_path):
        self.config_path = config_path

    def get_config(self):
        with open(self.config_path, "r") as f:
            return json.load(f)

    async def fetch_forensic_metrics(self, ticker, usd_to_cad=1.38):
        def _fetch():
            try:
                t = yf.Ticker(ticker)
                
                # Fetch quarterly statements
                bs = t.quarterly_balance_sheet
                cf = t.quarterly_cashflow
                inc = t.quarterly_financials
                
                if bs.empty or cf.empty or inc.empty:
                    return None

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
                    return None

                tot_assets_t0 = float(total_assets_series.iloc[0])
                net_inc_t0 = float(net_income_series.iloc[0])
                cfo_t0 = float(cfo_series.iloc[0])
                
                shares_t0 = float(share_count_series.iloc[0]) if (share_count_series is not None and len(share_count_series) > 0) else current_shares
                shares_t1 = float(share_count_series.iloc[1]) if (share_count_series is not None and len(share_count_series) > 1) else shares_t0
                
                sga_series = find_row(inc, ['Selling General and Administrative', 'General and Administrative', 'SG&A'])
                sga_t0 = float(sga_series.iloc[0]) if (sga_series is not None and len(sga_series) > 0) else 0.0

                # 1. Cash Flow Sloan Accrual Ratio
                sloan_cfo = (net_inc_t0 - cfo_t0) / tot_assets_t0 if tot_assets_t0 > 0 else 0.0
                
                cfo_t1 = float(cfo_series.iloc[1]) if len(cfo_series) > 1 else cfo_t0
                
                # 2. Balance Sheet Sloan Accrual Ratio
                ca_series = find_row(bs, ['Total Current Assets'])
                cl_series = find_row(bs, ['Total Current Liabilities'])
                cash_series = find_row(bs, ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'])
                da_series = find_row(cf, ['Depreciation And Amortization', 'Depreciation & Amortization'])
                
                sloan_bs = sloan_cfo
                cash_t0 = None
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
                    except:
                        pass

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
                print(f"[!] Forensic fetch error for {ticker}: {e}")
                return None

        res = await asyncio.to_thread(_fetch)
        return res

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
            if cba_pass:
                score += 1.0
                details["accrual"] = {"pass": True, "value": cba, "desc": f"CBA <= 15% ({cba*100:.1f}%)"}
            else:
                details["accrual"] = {"pass": False, "value": cba, "desc": f"Burn accelerating ({cba*100:.1f}%)"}
        else:
            # Standard Sloan Ratio Check
            sloan_pass = sloan_cfo < 0.05
            if sloan_pass:
                score += 1.0
                details["accrual"] = {"pass": True, "value": sloan_cfo, "desc": f"Sloan CFO < 5% ({sloan_cfo*100:.1f}%)"}
            else:
                details["accrual"] = {"pass": False, "value": sloan_cfo, "desc": f"Accrual overload ({sloan_cfo*100:.1f}%)"}

        # 3. Share Dilution Test
        dilution = 0.0
        if shares_t1 > 0:
            dilution = (shares_t0 - shares_t1) / shares_t1
            if dilution < 0: dilution = 0.0
        
        dilution_pass = dilution < 0.02
        if dilution_pass:
            score += 1.0
            details["dilution"] = {"pass": True, "value": dilution, "desc": f"Dilution < 2% QoQ ({dilution*100:.1f}%)"}
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

    def calculate_rep_floor(self):
        cfg = self.get_config()
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        infra_component = rf["permitting_infra_premium_m"] * 1_000_000
        buckets = cfg.get("project_buckets_oz_AgEq", {})
        total_oz = sum(buckets.values())
        resource_component = total_oz * rf["stressed_resource_per_oz"]
        total_rep_value = cash_component + resource_component + infra_component
        rep_floor = (total_rep_value * rf["conservatism_scalar"]) / cfg["aga_shares_out"]
        return rep_floor

    def calculate_continuous_rov(self, real_yield, spot_ag, rov_default=1.18, silver_vol=0.25):
        # Continuous Options Convexity
        negative_yield_premium = min(0.50, max(0.0, 1.0 - real_yield) * 0.25)
        vol_premium = max(0.0, (silver_vol - 0.20) * 0.50)
        rov = rov_default * (1.0 + negative_yield_premium) * (1.0 + vol_premium)
        return rov

    def calculate_is_iai(self, peer_ev_oz, discovery_premium_factor, spot_ag, capital_discount_factor):
        cfg = self.get_config()
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

        is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / cfg["aga_shares_out"]
        return is_iai_per_share, jurisdiction_uplift


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
        
        fractional_kelly = guard.get("fractional_kelly_multiplier", 0.5)
        pos_liq_cap = guard.get("position_liquidity_cap_pct", 0.15)
        max_single_pos = guard.get("max_single_position_pct", 0.20)
        
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

        # 2. Portfolio-Level Kelly Allocation (Blended Barbell Target Sizing)
        port_vol = limit_params.get("port_vol", 0.40)
        port_variance = max(0.04, port_vol ** 2)
        raw_portfolio_kelly = (u_implied / port_variance) * fractional_kelly
        
        # Max aggregate leverage allowed
        max_leverage_allowed = 1.5
        vix = limit_params.get("vix", 16.5)
        if vix > 15.0:
            max_leverage_allowed = max(0.60, 1.5 - ((vix - 15.0) * 0.045))
            
        target_portfolio_leverage = min(raw_portfolio_kelly, max_leverage_allowed) * correlation_penalty
        
        # Aggregate barbell target capital
        e_target_raw = live_portfolio_value * target_portfolio_leverage
        e_target_capped = max(0.0, e_target_raw * multiplier)
        
        # 3. Position-Level Liquidity and Sizing Caps (For information and UI breakdown)
        # Sizing Cap based on ADV Liquidity for the Spear (AGA.V)
        aga_price = limit_params.get("aga_price", 0.72)
        aga_adv = limit_params.get("aga_adv", 150000)
        
        # Cap scales down from 15% to 2% as macro stress approaches 100
        cap_percentage = max(0.02, 0.15 * (1.0 - (mri_score / 100.0)))
        adv_cap_cad = aga_adv * cap_percentage * aga_price
        
        # Kelly Multiple represents the actual portfolio value vs. target leveraged sizer
        kelly_multiple = live_portfolio_value / e_target_capped if e_target_capped > 100 else 1.0
        
        return {
            "e_target": round(e_target_capped, 2),
            "kelly_multiple": round(kelly_multiple, 2),
            "macro_regime": macro_regime,
            "target_pct": round(target_portfolio_leverage * 100, 2),
            "adv_cap_cad": round(adv_cap_cad, 2),
            "avg_ballast_corr": round(avg_ballast_corr, 2),
            "correlation_penalty": round(correlation_penalty, 3),
            "cap_percentage": round(cap_percentage * 100, 2)
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

        self.last_macro_update = 0
        self.last_price_update = 0
        self.last_cftc_update = 0
        self.last_peer_update = 0
        
        self.cached_prices = {}
        self.cached_mean_peer_ev_oz = None
        self.macro_fail_count = 0
        
        self.shares = {}
        self.last_csv_mtime = 0

        self.terminal_state = {
            "macro_regime": "Pending Data...",
            "directive": "Waiting for tape...",
            "metrics": {
                "10Y": {"value": 4.35, "status": "STALE_FALLBACK"},
                "30Y": {"value": 4.65, "status": "STALE_FALLBACK"},
                "WTI": {"value": 89.5, "status": "STALE_FALLBACK"},
                "DXY": {"value": 99.0, "status": "STALE_FALLBACK"},
                "Spot_Ag": {"value": 74.8, "status": "STALE_FALLBACK"},
                "Spreads": {"value": 2.71, "status": "STALE_FALLBACK"},
                "TED": {"value": 0.35, "status": "STALE_FALLBACK"},
                "EFFR": {"value": 4.33, "status": "STALE_FALLBACK"},
                "VIX": {"value": 16.5, "status": "STALE_FALLBACK"},
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
            "mri": 45.0
        }

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

    async def sync_cftc_positioning(self):
        if self.last_cftc_update > 0 and (time.time() - self.last_cftc_update < 14400):
            return
        try:
            def openbb_cftc():
                from openbb import obb
                if hasattr(obb, "cftc"):
                    try:
                        search_res = obb.cftc.cot_search(query="silver")
                        df_search = search_res.to_dataframe()
                        if not df_search.empty:
                            silver_rows = df_search[df_search['name'].str.contains('SILVER', case=False, na=False)]
                            target_code = str(silver_rows['code'].iloc[0]) if not silver_rows.empty else str(df_search['code'].iloc[0])
                            res = obb.cftc.cot(code=target_code)
                        else:
                            res = obb.cftc.cot(code="CFTC_084694")
                    except Exception:
                        res = obb.cftc.cot(code="CFTC_084694")
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
                long_candidates, short_candidates = [], []
                for c in df_cot.columns:
                    c_clean = str(c).lower().replace("_", "").replace(" ", "")
                    is_speculator = any(x in c_clean for x in ["noncommercial", "managedmoney", "mmoney", "noncomm"])
                    if is_speculator:
                        if "long" in c_clean: long_candidates.append(c)
                        elif "short" in c_clean: short_candidates.append(c)
                
                long_col = [c for c in long_candidates if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                short_col = [c for c in short_candidates if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                
                if not long_col and long_candidates: long_col = [long_candidates[0]]
                if not short_col and short_candidates: short_col = [short_candidates[0]]

                if long_col and short_col:
                    df_valid = df_cot.dropna(subset=[long_col[0], short_col[0]])
                    if not df_valid.empty:
                        latest_row = df_valid.iloc[-1]
                        long_val, short_val = float(latest_row[long_col[0]]), float(latest_row[short_col[0]])
                        if "pct" in str(long_col[0]).lower() or (long_val <= 1.0 and short_val <= 1.0):
                            net_position = (long_val - short_val) * 100000
                        else:
                            net_position = long_val - short_val
                        self.terminal_state["metrics"]["CFTC_Silver_Net_Longs"] = {"value": net_position, "status": "LIVE"}
                        self.last_cftc_update = time.time()
                        print(f"[*] CFTC Engine Updated -> Net speculative exposure: {net_position:+,}")
        except Exception as e:
            print(f"[DEBUG] CFTC fallback triggered: {e}")

    async def sync_term_structure(self):
        if not hasattr(self, 'last_term_structure_update'):
            self.last_term_structure_update = 0
            self.cached_term_structure = (0.0, 0.0)
        if time.time() - self.last_term_structure_update < 14400:
            return self.cached_term_structure
            
        try:
            def _fetch():
                import datetime
                m1_ticker = "SI=F"
                m1_hist = yf.Ticker(m1_ticker).history(period="1d")
                m1_price = float(m1_hist['Close'].iloc[-1]) if not m1_hist.empty else 0.0
                
                now = datetime.datetime.now()
                curr_month = now.month
                curr_year_short = now.year % 100
                
                if curr_month in [1, 2]: code, yr = "N", curr_year_short
                elif curr_month in [3, 4, 5]: code, yr = "Z", curr_year_short
                elif curr_month in [6, 7, 8]: code, yr = "H", curr_year_short + 1
                else: code, yr = "N", curr_year_short + 1
                    
                m180_ticker = f"SI{code}{yr:02d}.CMX"
                m180_hist = yf.Ticker(m180_ticker).history(period="1d")
                m180_price = float(m180_hist['Close'].iloc[-1]) if not m180_hist.empty else 0.0
                
                if m180_price == 0.0:
                    m180_price = m1_price
                    
                return (m1_price, m180_price, m180_ticker)
            
            m1_p, m180_p, m180_t = await asyncio.to_thread(_fetch)
            self.cached_term_structure = (m1_p, m180_p)
            self.last_term_structure_update = time.time()
            if m1_p > 0 and m180_p > 0:
                print(f"[*] Silver Term Structure Updated -> M1: ${m1_p:.2f} | M180 ({m180_t}): ${m180_p:.2f}")
        except Exception as e:
            print(f"[!] Futures term structure fetch error: {e}")
            self.last_term_structure_update = time.time() - 13800
        return self.cached_term_structure

    async def fetch_copper_gold(self):
        try:
            def _fetch():
                copper, gold = 4.2, 2350.0
                try:
                    cu = yf.Ticker("HG=F").history(period="5d")
                    au = yf.Ticker("GC=F").history(period="5d")
                    if not cu.empty: copper = float(cu['Close'].iloc[-1])
                    if not au.empty: gold = float(au['Close'].iloc[-1])
                    _save_to_cache("copper_gold", {"copper": copper, "gold": gold})
                except:
                    cached = _load_from_cache("copper_gold", {"copper": 4.2, "gold": 2350.0})
                    copper, gold = cached["copper"], cached["gold"]
                return copper, gold
            return await asyncio.to_thread(_fetch)
        except:
            cached = _load_from_cache("copper_gold", {"copper": 4.2, "gold": 2350.0})
            return cached["copper"], cached["gold"]

    async def evaluate_master_architecture(self, force_macro=False):
        cfg = self.peer_engine.get_config()

        if not self.shares or force_macro:
            self._load_shares_from_csv(force=True)

        await self.sync_cftc_positioning()

        # Phase 1: Weighted Peer Comps dynamic scraping
        mean_peer_ev, peer_details, avg_disc_cost = await self.peer_engine.fetch_and_calculate_weighted_comps()
        self.cached_mean_peer_ev_oz = mean_peer_ev

        # Extract macro metrics
        y10, y30, spr, ted, eff, vix = 4.35, 4.65, 2.71, 0.35, 4.33, 16.5
        macro_status = "LIVE"
        if force_macro or (time.time() - self.last_macro_update > 90):
            res, status = await self.macro_engine.fetch_macro_data()
            macro_status = status
            if res and len(res) >= 6:
                y10, y30, spr, ted, eff, vix = res
                self.terminal_state["metrics"].update({
                    "10Y": {"value": y10, "status": status}, "30Y": {"value": y30, "status": status},
                    "Spreads": {"value": spr, "status": status}, "TED": {"value": ted, "status": status},
                    "EFFR": {"value": eff, "status": status}, "VIX": {"value": vix, "status": status}
                })
                self.last_macro_update = time.time()

        # Prices
        prices = {}
        prices_status = "LIVE"
        if force_macro or (time.time() - self.last_price_update > 35):
            def get_market_data():
                new_prices = {}
                tickers = ["CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO"]
                for t in tickers:
                    try:
                        hist = yf.Ticker(t).history(period="10d")
                        if not hist.empty:
                            new_prices[t] = float(hist['Close'].iloc[-1])
                        else:
                            raise Exception(f"Empty hist for {t}")
                    except Exception as e:
                        print(f"[!] yfinance price fetch error for {t}: {e}")
                        new_prices[t] = self._get_fallback_price(t)
                return new_prices
            try:
                prices = await asyncio.to_thread(get_market_data)
                _save_to_cache("prices", prices)
                self.last_price_update = time.time()
            except Exception as e:
                print(f"[!] Price fetch parent error: {e}")
                prices_status = "DEGRADED_STALE"
                prices = _load_from_cache("prices", {
                    "CL=F": 80.0, "DX-Y.NYB": 99.0, "SI=F": 74.8,
                    "AGA.V": 0.72, "GROY": 3.22, "GMX.TO": 2.04, "URC.TO": 4.82
                })
        else:
            prices = getattr(self, 'cached_prices', {})
        self.cached_prices = prices

        p_aga = prices.get("AGA.V", 0.71)
        p_urc = prices.get("URC.TO", 4.82)
        p_groy = prices.get("GROY", 3.22)
        p_gmx = prices.get("GMX.TO", 2.04)
        spot_ag = prices.get("SI=F", 74.8)
        wti_price = prices.get("CL=F", 80.0)
        self.terminal_state["metrics"]["Spot_Ag"] = {"value": spot_ag, "status": prices_status}
        self.terminal_state["metrics"]["WTI"] = {"value": wti_price, "status": prices_status}

        # DXY momentum & MRI metrics
        dxy_mom, current_dxy, dxy_status = await self.macro_engine.fetch_dxy_momentum()
        self.terminal_state["metrics"]["DXY"] = {"value": current_dxy, "status": dxy_status}
        self.terminal_state["metrics"]["DXY_MOMENTUM"] = {"value": dxy_mom, "status": dxy_status}

        usd_to_cad = 1.38
        try:
            def fetch_usdcad():
                cad_hist = yf.Ticker("USDCAD=X").history(period="1d")
                if not cad_hist.empty:
                    val = float(cad_hist['Close'].iloc[-1])
                    _save_to_cache("usdcad", {"value": val})
                    return val
                raise Exception("USDCAD empty hist")
            usd_to_cad = await asyncio.to_thread(fetch_usdcad)
        except Exception as e:
            print(f"[!] USDCAD fetch error: {e}")
            cached_usdcad = _load_from_cache("usdcad", {"value": 1.38})
            usd_to_cad = cached_usdcad["value"]

        # Portfolio sizing prep
        live_portfolio_value = (
            self.shares.get('AGA', 0) * p_aga + self.shares.get('URC', 0) * p_urc +
            self.shares.get('GMX', 0) * p_gmx + self.shares.get('GROY', 0) * p_groy * usd_to_cad +
            self.shares.get('UROY_CALL', 0) * 0.60 * usd_to_cad
        )
        if live_portfolio_value < 1000: live_portfolio_value = cfg.get("target_capital", 5360.0)

        # Macro calculations
        real_yield, ry_status = await self.macro_engine.fetch_real_yield()
        copper, gold = await self.fetch_copper_gold()
        
        # Overall terminal state status
        if "DEGRADED_STALE" in [macro_status, prices_status, dxy_status, ry_status]:
            self.terminal_state["status"] = "DEGRADED_STALE"
        else:
            self.terminal_state["status"] = "LIVE"

        mri_score = self.macro_engine.calculate_mri(self.terminal_state["metrics"], spot_ag, real_yield, copper, gold, dxy_mom)
        self.terminal_state["mri"] = mri_score

        # Phase 1: Micro forensics & runway scaling
        rf_floor = self.valuation_engine.calculate_rep_floor()
        monthly_burn = cfg["cash_burn"]["monthly_burn_rate"]
        
        # Cash Component of the treasury
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        cash_runway_months = cash_component / monthly_burn if monthly_burn > 0 else 99.0
        
        # Scrape and score financials for AGA.V
        forensic_data = await self.forensic_engine.fetch_forensic_metrics("AGA.V")
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

        # Dynamic AISC & margins
        base_aisc = cfg["dynamic_discovery_v5"]["estimated_industry_aisc_2026"]
        dynamic_aisc = base_aisc + max(0, wti_price - 80.0) * 0.15
        
        phi_margin = max(0.58, (spot_ag - dynamic_aisc) / spot_ag) if spot_ag > dynamic_aisc else 0.05
        commodity_leverage = spot_ag / dynamic_aisc if dynamic_aisc > 0 else 1.0
        exp_scalar = cfg["dynamic_discovery_v5"].get("explorer_re_rating_scalar", 1.68)
        
        raw_factor = commodity_leverage * phi_margin * exp_scalar
        spot_dev = max(0, (spot_ag - 76.5) / 50)
        ceiling = 4.2 + (0.90 * min(1.0, spot_dev)) * (1.0 - mri_score / 100)
        discovery_premium_factor = max(0.50, min(raw_factor, ceiling))

        # Real Option Value
        rov = self.valuation_engine.calculate_continuous_rov(real_yield, spot_ag, cfg.get("rov_default", 1.18))

        # Capital Discount
        capital_discount_factor = 1.0
        if y30 > 4.0:
            capital_discount_factor = max(0.40, 1.0 - ((y30 - 4.0) * 0.12))

        # Physical stress
        m1_price, m180_price = await self.sync_term_structure()
        if m1_price > 0 and m180_price > 0 and m1_price > m180_price:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": True, "status": "LIVE"}
            uplift_premium = min(0.25, max(0.0, (m1_price - m180_price) / m1_price) * 5.0)
        else:
            self.terminal_state["metrics"]["PHYSICAL_STRESS"] = {"value": False, "status": "LIVE"}
            uplift_premium = 0.0

        # In-Situ IAI & Exploration Upside
        is_iai_per_share, jurisdiction_uplift = self.valuation_engine.calculate_is_iai(
            mean_peer_ev, discovery_premium_factor, spot_ag, capital_discount_factor
        )
        
        # Apply physical stress uplift premium to jurisdiction bounds
        jurisdiction_uplift = jurisdiction_uplift * (1.0 + uplift_premium)

        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (
            exp.get("expected_future_oz", 0) * mean_peer_ev * 
            jurisdiction_uplift * exp.get("probability_of_discovery", 0.25)
        )
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)

        # AGA Intrinsic Value
        # Apply Forensic Penalty directly to the Resource valuation to capture capital decay
        aga_intrinsic = (
            (0.15 * rf_floor) + 
            (0.70 * is_iai_per_share * forensic_penalty) + 
            (0.15 * rov) + 
            exp_per_share
        )

        # Blended PPI and Implied Upside
        ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)

        # Forensic penalties on ballast based on their Sloan metrics
        ballast_sloans = {}
        for ticker in ["GROY", "URC.TO", "GMX.TO"]:
            metrics = await self.forensic_engine.fetch_forensic_metrics(ticker)
            ballast_sloans[ticker] = metrics["sloan_cfo"] if metrics else 0.02
        
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

        # Phase 2: Volatilities, correlations, ES & sizer calculations
        barbell_tickers = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]
        df_rets, corr_matrix, vols = await self.sizer.fetch_historical_returns(barbell_tickers)
        
        if df_rets is not None and not df_rets.empty:
            weights = np.array([0.60, 0.15, 0.10, 0.15])
            es_95 = self.sizer.calculate_expected_shortfall(df_rets, weights)
            
            # Dynamic portfolio volatility standard deviation
            port_returns = df_rets.dot(weights)
            port_vol = float(port_returns.std() * np.sqrt(252))
            
            # Weighted average correlation
            corr_sum = 0.0
            corr_count = 0
            for i, t1 in enumerate(barbell_tickers):
                for j, t2 in enumerate(barbell_tickers):
                    if i < j:
                        corr_sum += corr_matrix.get(t1, {}).get(t2, 0.0)
                        corr_count += 1
            avg_corr = corr_sum / corr_count if corr_count > 0 else 0.0
        else:
            es_95 = 0.052  # 5.2% daily tail-risk fallback
            port_vol = 0.40
            avg_corr = 0.45
            corr_matrix = {"AGA.V": {"GROY": 0.5, "URC.TO": 0.5, "GMX.TO": 0.5}}
            vols = {"AGA.V": 0.45, "GROY": 0.35, "GMX.TO": 0.38, "URC.TO": 0.42}

        self.terminal_state["portfolio_stats"] = {
            "expected_shortfall_95": round(es_95 * 100, 2),
            "avg_correlation": round(avg_corr, 2),
            "vols": vols,
            "correlations": corr_matrix
        }

        # Fetch Average Daily Volume for Liquidity cap
        aga_adv = await self.sizer.get_liquidity_cap("AGA.V")
        limit_params = {
            "aga_price": p_aga, 
            "aga_adv": aga_adv,
            "port_vol": port_vol,
            "vix": vix
        }

        sizing_res = self.sizer.calculate_sizing(
            live_portfolio_value, u_implied, vols, corr_matrix, mri_score, limit_params
        )

        e_target_capped = sizing_res["e_target"]
        kelly_multiple = sizing_res["kelly_multiple"]
        macro_regime = sizing_res["macro_regime"]
        
        # Sizing directives
        if mri_score < 40 and u_implied > 0.80:
            directive = "HIGH CONVICTION ZONE - DEPLOY CAPITAL"
        elif kelly_multiple > 1.5:
            directive = "CAUTION - OVER-ALLOCATED - TRIM EXPOSURE"
        elif mri_score > 65:
            directive = "DEFENSIVE MODE - PROTECT CAPITAL"
        else:
            directive = "HOLD POSITION - MONITOR TAPE"

        self.terminal_state["macro_regime"] = macro_regime
        self.terminal_state["directive"] = directive
        
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
            "Discovery_Premium_Factor": round(discovery_premium_factor, 3),
            "Mean_Peer_EV_oz": round(mean_peer_ev, 2),
            "ADV_Cap_CAD": sizing_res["adv_cap_cad"],
            "ADV_Cap_Percentage": sizing_res["cap_percentage"],
            "Discovery_Efficiency_Comps": round(avg_disc_cost, 2)
        }

        self.terminal_state["nodes"] = {
            "AGA.V": {"price": round(p_aga, 3), "role": "The Spear"}, 
            "GROY": {"price": round(p_groy, 2), "role": "Ballast"},
            "GMX.TO": {"price": round(p_gmx, 2), "role": "Ballast"}, 
            "URC.TO": {"price": round(p_urc, 2), "role": "Ballast"}
        }

        # Terminal Print
        print("\n" + "═"*75)
        print(f" COMMODITYEX MONITOR v5.1 // CORE ENGINE LOG // {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("═"*75)
        
        print(f" [MACRO]    MRI: {mri_score:.1f} | REGIME: {macro_regime.upper()} ")
        print(f"            DXY Mom: {dxy_mom:+.2f}% | Expected Shortfall (95%): {es_95*100:.2f}% ")
        print(f"            DIRECTIVE: {directive}")
        print("─"*75)
        
        print(f" [SYNTHESIS] Equity Value: ${live_portfolio_value:,.2f} CAD")
        print(f"            Target Capital: ${e_target_capped:,.2f} CAD | ADV Sizing Cap: ${sizing_res['adv_cap_cad']:,.2f} CAD ({sizing_res['cap_percentage']:.1f}%)")
        print(f"            Kelly Multiple: {kelly_multiple:.2f}x | Implied Edge: {u_implied*100:.1f}%")
        print(f"            REP Floor:      ${rf_floor:.3f} | Cash Runway:  {cash_runway_months:.1f} mo")
        print("─"*75)
        
        print(f" [FORENSICS] JSF Score: {forensic_score:.1f}/4.0 | Penalty Discount: {forensic_penalty:.3f}x")
        print(f"            Sloan CFO: {sloan_cfo:+.4f} | Sloan Balance Sheet: {sloan_bs:+.4f}")
        print(f"            Average peer discovery cost: ${avg_disc_cost:.2f}/oz")
        print("─"*75)
        
        print(f" [VALUATION] AGA Intrinsic: ${aga_intrinsic:.3f} | IS-IAI / Share: ${is_iai_per_share:.3f}")
        print(f"            Exp Premium:   ${exp_per_share:.3f} | ROV Multiple:   {rov:.2f}")
        print(f"            Blended PPI:   ${ppi:.3f} | EV Blended:     ${ev_blended:.3f}")
        print(f"            Disc. Premium: {discovery_premium_factor:.3f} | Weighted Peer EV: ${mean_peer_ev:.2f}/oz")
        print("─"*75)
        
        print(f" [BARBELL]   AGA.V:  ${p_aga:.3f} (The Spear) | Vol: {vols.get('AGA.V', 0.45)*100:.1f}%")
        print(f"            GROY:   ${p_groy:.2f}  | GMX.TO: ${p_gmx:.2f} | URC.TO: ${p_urc:.2f}")
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
    engine_task = asyncio.create_task(engine._run_loop())
    broadcaster_task = asyncio.create_task(websocket_broadcaster())
    yield
    engine_task.cancel()
    broadcaster_task.cancel()
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