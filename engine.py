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
from fastapi import FastAPI, WebSocket
import uvicorn
from contextlib import asynccontextmanager

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

class CommodityExMonitor:
    def __init__(self, host='127.0.0.1', port=4002, client_id=1):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.last_macro_update = 0
        self.last_price_update = 0
        self.last_cftc_update = 0
        self.last_peer_update = 0
        self.cached_prices = {}
        self.cached_peer_ev_oz = {}
        self.cached_mean_peer_ev_oz = None
        self.macro_fail_count = 0
        
        self.config_path = "v4_config.json"
        self._ensure_config_exists()

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
                "CFTC_Silver_Net_Longs": {"value": 35000.0, "status": "INITIAL_BASELINE"}
            },
            "nodes": {},
            "v4_valuation": {},
            "signals": [],
            "kill_switches": {"AGA_V": "SAFE (Pending Drill Assays)"},
            "systemic_stress": 0.0,
            "bvs": 45.0
        }

    def _ensure_config_exists(self):
        if not os.path.exists(self.config_path):
            default_config = {
                "target_capital": 5360.0,
                "friction_drag": 0.0185,
                "aga_shares_out": 208600000,
                "aga_adv_fallback": 150000,
                "rep_floor_params": {
                    "cash_treasury_m": 53.07,
                    "stressed_resource_per_oz": 0.65,
                    "permitting_infra_premium_m": 12.0,
                    "conservatism_scalar": 0.85
                },
                "cash_burn": {
                    "monthly_burn_rate": 750000,
                    "warning_threshold_months": 24
                },
                "project_buckets_oz_AgEq": {
                    "red_mountain": 168600000,
                    "belmont_tailings": 27000000,
                    "hughes": 43200000,
                    "mogollon": 32100000
                },
                "metallurgical_recovery": {
                    "red_mountain": {"silver": 0.85, "gold": 0.94},
                    "belmont_tailings": {"silver": 0.89, "gold": 0.95},
                    "hughes": {"silver": 0.87, "gold": 0.95},
                    "mogollon": {"silver": 0.78, "gold": 0.92}
                },
                "exploration_upside": {
                    "expected_future_oz": 75000000,
                    "probability_of_discovery": 0.25,
                    "discovery_multiple": 0.052,
                    "weight": 0.12
                },
                "rov_default": 1.18,
                "conservatism_scalar": 0.88,
                "catalyst_probabilities": {
                    "belmont_tailings": 0.92,
                    "red_mtn_drill": 0.73,
                    "hughes_drill": 0.45,
                    "mogollon_drill": 0.18,
                    "kennedy_discovery": 0.22
                },
                "structural_weights": {
                    "belmont_tailings": 0.35,
                    "red_mtn_drill": 0.45,
                    "hughes_drill": 0.15,
                    "mogollon_drill": 0.05
                },
                # v4 additions
                "dynamic_discovery_v4": {
                    "peer_comp_tickers": ["DVI.V", "MAG", "BRC.V", "DSV.V"],
                    "peer_resources_oz_AgEq": {
                        "DVI.V": 150000000,
                        "MAG": 450000000,
                        "BRC.V": 120000000,
                        "DSV.V": 300000000
                    },
                    "stressed_resource_baseline": 0.65,
                    "estimated_industry_aisc_2026": 24.50,
                    "sentiment_damping_enabled": True
                },
                "v4_guardrails": {
                    "fractional_kelly_multiplier": 0.50,
                    "covariance_lookback_days": 60
                }
            }
            with open(self.config_path, "w") as f:
                json.dump(default_config, f, indent=4)
            print("[*] v4_config.json generated with dynamic discovery parameters.")

    def _load_shares_from_csv(self, force=False):
        holdings_path = "holdings-report-2026-05-24.csv"
        if not os.path.exists(holdings_path):
            return False
        try:
            mtime = os.path.getmtime(holdings_path)
            if not force and mtime == self.last_csv_mtime:
                return True

            import pandas as pd
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
                    latest_row = df_cot.iloc[-1]
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

    async def sync_peer_comps(self):
        # Throttle API calls to every 4 hours
        if self.last_peer_update > 0 and (time.time() - self.last_peer_update < 14400):
            return
            
        try:
            def fetch_peer_data():
                cfg = json.load(open(self.config_path))
                v4_data = cfg.get("dynamic_discovery_v4", {})
                tickers = v4_data.get("peer_comp_tickers", [])
                resources = v4_data.get("peer_resources_oz_AgEq", {})
                
                # Fetch live USD/CAD for normalization
                usd_to_cad = 1.38  # Safe fallback
                try:
                    cad_hist = yf.Ticker("USDCAD=X").history(period="1d")
                    if not cad_hist.empty:
                        usd_to_cad = float(cad_hist['Close'].iloc[-1])
                except Exception as e:
                    print(f"[!] Currency normalization fallback triggered: {e}")

                results = {}
                for t in tickers:
                    try:
                        ticker_obj = yf.Ticker(t)
                        info = ticker_obj.info
                        
                        # 1. Prioritize Enterprise Value over Market Cap
                        raw_val = info.get('enterpriseValue')
                        if not raw_val:
                            raw_val = info.get('marketCap', 0)
                            
                        # 2. Currency Normalization (Target: CAD)
                        currency = str(info.get('currency', 'CAD')).upper()
                        normalized_val = float(raw_val)
                        if currency == 'USD':
                            normalized_val = float(raw_val) * usd_to_cad
                            
                        # 3. Exact Key Lookup for Resources
                        oz = resources.get(t)
                        if not oz or oz <= 0:
                            print(f"[!] Warning: No resource ounces found for {t}. Skipping.")
                            continue
                            
                        if normalized_val > 0:
                            ev_oz = normalized_val / oz
                            results[t] = ev_oz
                            print(f"[*] Peer {t} | EV: ${normalized_val:,.0f} CAD | Oz: {oz:,.0f} | Ratio: ${ev_oz:.2f}/oz")
                        else:
                            print(f"[!] Warning: {t} returned 0 for EV/Market Cap. Skipping.")
                            
                    except Exception as e:
                        print(f"[!] Failed to fetch/parse peer {t}: {e}")
                
                # 4. Safely calculate the mean, fallback to historical standard if completely blind
                if not results:
                    print("[!] All peer valuations failed. Defaulting to historical baseline of $2.50 CAD/oz.")
                    return 2.50, {}
                    
                mean_ev = sum(results.values()) / len(results)
                return mean_ev, results

            mean_ev, _ = await asyncio.to_thread(fetch_peer_data)
            self.cached_mean_peer_ev_oz = mean_ev
            self.last_peer_update = time.time()
            print(f"[*] Peer Comps Updated -> Mean EV/oz: ${mean_ev:.2f} CAD")
            
        except Exception as e:
            print(f"[!] Peer comps master fallback triggered: {e}")
            self.cached_mean_peer_ev_oz = 2.50

    async def fetch_macro_data(self):
        try:
            def openbb_fetch():
                from openbb import obb
                def fetch_raw_fred(series_id, fallback_val):
                    try:
                        res = obb.economy.fred_series(symbol=series_id)
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
            return result
        except:
            return [4.35, 4.65, 2.71, 0.35, 4.33, 16.5]

    async def fetch_bvs_data(self):
        try:
            copper, gold, real_yield = 4.2, 2350.0, 1.8
            try:
                cu = yf.Ticker("HG=F").history(period="5d")
                au = yf.Ticker("GC=F").history(period="5d")
                if not cu.empty: copper = float(cu['Close'].iloc[-1])
                if not au.empty: gold = float(au['Close'].iloc[-1])
            except: pass
            return {"real_yield": real_yield, "copper": copper, "gold": gold}
        except:
            return {"real_yield": 1.8, "copper": 4.2, "gold": 2350}

    def calculate_bvs(self, m, spot_ag, bvs_data):
        try:
            dxy = float(m.get('DXY', {}).get('value', 100))
            ted = float(m.get('TED', {}).get('value', 0.3))
            vix = float(m.get('VIX', {}).get('value', 18))
            spreads = float(m.get('Spreads', {}).get('value', 3.5))
            y10 = float(m.get('10Y', {}).get('value', 4.2))
            y30 = float(m.get('30Y', {}).get('value', 4.4))
            
            real_yield = bvs_data.get('real_yield', 1.8)
            copper = bvs_data.get('copper', 4.2)
            gold = bvs_data.get('gold', 2350)
            cftc_net = float(m.get('CFTC_Silver_Net_Longs', {}).get('value', 35000.0))

            def norm(val, low, high):
                return max(0, min(100, (val - low) / (high - low) * 100))

            liq_score = (norm(dxy - 100, -5, 8) * 0.4 + norm(ted, 0.1, 0.9) * 0.3 + norm(real_yield, 0.5, 3.5) * 0.3)
            yield_score = (norm(y30 - y10, -0.5, 1.5) * 0.5 + norm(y10, 3.0, 5.5) * 0.5)
            vol_score = (norm(vix, 12, 35) * 0.5 + norm(spreads, 2, 7) * 0.5)
            
            cu_au_ratio = copper / gold if gold > 0 else 0.0018
            comm_score = (norm(cu_au_ratio, 0.0014, 0.0022) * 0.6 + norm(spot_ag / 30, 0.8, 1.4) * 0.4)
            sentiment_score = norm(cftc_net, -15000, 85000)

            bvs = (liq_score * 0.30) + (yield_score * 0.20) + (vol_score * 0.20) + (comm_score * 0.15) + (sentiment_score * 0.15)
            return round(max(0, min(100, bvs)), 1)
        except:
            return 45.0

    def calculate_discovery_premium_factor(self, spot_ag, bvs_score, cfg):
        mean_peer_ev = getattr(self, 'cached_mean_peer_ev_oz', 4.95)   # Better explorer baseline
        
        stressed_baseline = cfg["dynamic_discovery_v4"]["stressed_resource_baseline"]
        aisc = cfg["dynamic_discovery_v4"]["estimated_industry_aisc_2026"]
        j_prem = cfg["dynamic_discovery_v4"].get("jurisdiction_premium", 1.32)
        exp_scalar = cfg["dynamic_discovery_v4"].get("explorer_re_rating_scalar", 1.68)

        phi_margin = max(0.58, (spot_ag - aisc) / spot_ag if spot_ag > aisc else 0.79)
        
        raw_factor = (mean_peer_ev / stressed_baseline) * phi_margin * j_prem * exp_scalar
        
        # Generous but capped ceiling for current silver bull
        spot_dev = max(0, (spot_ag - 76.5) / 50)
        ceiling = 0.42 + (0.09 * min(1.0, spot_dev)) * (1.0 - bvs_score / 100)
        
        return max(1.85, min(raw_factor, ceiling))
    
    async def evaluate_master_architecture(self, force_macro=False):
        try:
            with open(self.config_path, "r") as f:
                cfg = json.load(f)
        except: return

        if not self.shares or force_macro:
            self._load_shares_from_csv(force=True)

        await self.sync_cftc_positioning()
        await self.sync_peer_comps()

        # Extract live macro trackers
        y10, y30, spr, ted, eff, vix = 4.35, 4.65, 2.71, 0.35, 4.33, 16.5
        if force_macro or (time.time() - self.last_macro_update > 90):
            res = await self.fetch_macro_data()
            if res and len(res) >= 6:
                y10, y30, spr, ted, eff, vix = res
                self.terminal_state["metrics"].update({
                    "10Y": {"value": y10, "status": "LIVE"}, "30Y": {"value": y30, "status": "LIVE"},
                    "Spreads": {"value": spr, "status": "LIVE"}, "TED": {"value": ted, "status": "LIVE"},
                    "EFFR": {"value": eff, "status": "LIVE"}, "VIX": {"value": vix, "status": "LIVE"}
                })
                self.last_macro_update = time.time()

        # Prices
        prices = {}
        if force_macro or (time.time() - self.last_price_update > 35):
            def get_market_data():
                new_prices = {}
                tickers = ["CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO"]
                for t in tickers:
                    try:
                        hist = yf.Ticker(t).history(period="10d")
                        new_prices[t] = float(hist['Close'].iloc[-1]) if not hist.empty else self._get_fallback_price(t)
                    except: new_prices[t] = self._get_fallback_price(t)
                return new_prices
            prices = await asyncio.to_thread(get_market_data)
            self.last_price_update = time.time()
        else:
            prices = getattr(self, 'cached_prices', {})
        self.cached_prices = prices

        p_aga = prices.get("AGA.V", 0.71)
        p_urc = prices.get("URC.TO", 4.82)
        p_groy = prices.get("GROY", 3.22)
        p_gmx = prices.get("GMX.TO", 2.04)
        spot_ag = prices.get("SI=F", 74.8)
        self.terminal_state["metrics"]["Spot_Ag"]["value"] = spot_ag

        usd_to_cad = 1.38
        try:
            cad_hist = yf.Ticker("USDCAD=X").history(period="1d")
            if not cad_hist.empty: usd_to_cad = float(cad_hist['Close'].iloc[-1])
        except: pass

        live_portfolio_value = (
            self.shares.get('AGA', 0) * p_aga + self.shares.get('URC', 0) * p_urc +
            self.shares.get('GMX', 0) * p_gmx + self.shares.get('GROY', 0) * p_groy * usd_to_cad +
            self.shares.get('UROY_CALL', 0) * 0.60 * usd_to_cad
        )
        if live_portfolio_value < 1000: live_portfolio_value = cfg.get("target_capital", 5360.0)

        # ==================== v4 DYNAMIC VALUATION ====================
        
        # Cost of capital discount
        capital_discount_factor = 1.0
        if y30 > 4.0:
            capital_discount_factor = max(0.40, 1.0 - ((y30 - 4.0) * 0.12))

        # Live market signal from peers
        mean_peer_ev = self.cached_mean_peer_ev_oz or 2.50
        
        # BVS early for ceiling
        bvs_data = await self.fetch_bvs_data()
        bvs_score = self.calculate_bvs(self.terminal_state["metrics"], spot_ag, bvs_data)

        # v4 Margin / Sentiment Premium Factor
        # Acts as a governor on the peer EV based on macro regime and margin safety
        discovery_premium_factor = self.calculate_discovery_premium_factor(spot_ag, bvs_score, cfg)

        # ROV (Real Option Value)
        cu_au = bvs_data["copper"] / bvs_data["gold"] if bvs_data["gold"] > 0 else 0.0018
        real_yield = bvs_data["real_yield"]
        rov = cfg.get("rov_default", 1.18)
        if cu_au > 0.0019 and real_yield < 2.0:
            rov = max(rov, min(1.45, rov * 1.20))
        elif real_yield > 2.5:
            rov = max(0.95, rov * 0.85)

        # REP Floor (Replacement Execution Protection)
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        infra_component = rf["permitting_infra_premium_m"] * 1_000_000
        buckets = cfg.get("project_buckets_oz_AgEq", {})
        total_oz = sum(buckets.values())
        resource_component = total_oz * rf["stressed_resource_per_oz"]
        total_rep_value = cash_component + resource_component + infra_component
        rep_floor = (total_rep_value * rf["conservatism_scalar"]) / cfg["aga_shares_out"]

        monthly_burn = cfg["cash_burn"]["monthly_burn_rate"]
        cash_runway_months = cash_component / monthly_burn if monthly_burn > 0 else 999.0

        # IN-SITU IAI (Peer-Calibrated EV/oz instead of Spot Multiples)
        jurisdiction_uplift = 1.35 if spot_ag > 50.0 else 1.15

        recovery = cfg.get("metallurgical_recovery", {})
        is_iai_total = 0.0
        for proj, oz in buckets.items():
            rec_silver = recovery.get(proj, {}).get("silver", 0.85)
            # Market Value = Ounces * Peer EV/oz * Premium Guardrail * Jurisdiction Uplift * Recovery * Cost of Capital
            is_iai_total += oz * mean_peer_ev * discovery_premium_factor * jurisdiction_uplift * rec_silver * capital_discount_factor

        is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / cfg["aga_shares_out"]

        # ====================================================================
        # RESTORED: Bounded Exploration Premium
        # ====================================================================
        
        # Tied to the peer EV/oz multiple rather than raw spot price to prevent hyper-inflation
        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (
            exp.get("expected_future_oz", 0) * mean_peer_ev * 
            jurisdiction_uplift * exp.get("probability_of_discovery", 0.25)
        )
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)

        # ====================================================================
        # AGA INTRINSIC VALUE (Recalibrated for a High-Grade Developer)
        # ====================================================================
        
        # Re-weighted: 15% Floor, 70% In-Situ Resource, 15% Real Option Value + Exploration Premium
        aga_intrinsic = (
            (0.15 * rep_floor) + 
            (0.70 * is_iai_per_share) + 
            (0.15 * rov) + 
            exp_per_share
        )

        # Portfolio & EV
        ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)
        ev_blended = (0.60 * aga_intrinsic) + (0.15 * p_urc * 1.15) + (0.15 * p_groy * 1.15) + (0.10 * p_gmx * 1.20)
        u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

        # Regime & Sizing
        if bvs_score < 40:
            multiplier, macro_regime = 1.00, "Expansion / Risk-On"
        elif bvs_score < 65:
            multiplier, macro_regime = 0.85, "Moderate Risk / Neutral"
        elif bvs_score < 80:
            multiplier, macro_regime = 0.55, "Elevated Risk / Caution"
        else:
            multiplier, macro_regime = 0.25, "High Stress / Defensive"

        max_leverage_allowed = 1.5
        if vix > 15.0:
            max_leverage_allowed = max(0.60, 1.5 - ((vix - 15.0) * 0.045))

        friction = cfg.get("friction_drag", 0.0185)
        raw_target = max(live_portfolio_value * u_implied * (1 - friction), 0)
        e_target_capped = min(raw_target * multiplier, live_portfolio_value * max_leverage_allowed)
        kelly_multiple = live_portfolio_value / e_target_capped if e_target_capped > 100 else 1.0

        if bvs_score < 40 and u_implied > 0.80:
            directive = "HIGH CONVICTION ZONE - DEPLOY CAPITAL"
        elif kelly_multiple > 1.5:
            directive = "CAUTION - OVER-ALLOCATED - TRIM EXPOSURE"
        elif bvs_score > 65:
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
            "REP_Floor": round(rep_floor, 3),
            "Cash_Runway_Months": round(cash_runway_months, 1), 
            "Kelly_Multiple": round(kelly_multiple, 2),
            "BVS": round(bvs_score, 1), 
            "IS_IAI_Per_Share": round(is_iai_per_share, 3),
            "Exp_Premium_Per_Share": round(exp_per_share, 3), 
            "ROV": round(rov, 2),
            "Discovery_Premium_Factor": round(discovery_premium_factor, 3),
            "Mean_Peer_EV_oz": round(self.cached_mean_peer_ev_oz or 2.5, 2)
        }

        self.terminal_state["nodes"] = {
            "AGA.V": {"price": round(p_aga, 3), "role": "The Spear"}, 
            "GROY": {"price": round(p_groy, 2), "role": "Ballast"},
            "GMX.TO": {"price": round(p_gmx, 2), "role": "Ballast"}, 
            "URC.TO": {"price": round(p_urc, 2), "role": "Ballast"}
        }

        print("\n" + "═"*75)
        print(f" COMMODITYEX MONITOR v4.0 // ENGINE LOG // {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("═"*75)
        
        # 1. Macro Risk Dashboard Row
        print(f" [MACRO]    BVS: {bvs_score:.1f} | REGIME: {macro_regime.upper()} ")
        print(f"            DIRECTIVE: {directive}")
        print("─"*75)
        
        # 2. Synthesis & Actionable Overview Row
        print(f" [SYNTHESIS] Current Value: ${live_portfolio_value:,.2f} CAD")
        print(f"            Target Capital: ${e_target_capped:,.2f} CAD")
        print(f"            Kelly Multiple: {kelly_multiple:.2f}x | Implied Edge: {u_implied*100:.1f}%")
        print(f"            REP Floor:     ${rep_floor:.3f} | Cash Runway:  {cash_runway_months:.1f} mo")
        print("─"*75)
        
        # 3. Detailed Forensic Breakdown Row
        print(f" [VALUATION] AGA Intrinsic: ${aga_intrinsic:.3f} | IS-IAI / Share: ${is_iai_per_share:.3f}")
        print(f"            Exp Premium:   ${exp_per_share:.3f} | ROV Multiple:   {rov:.2f}")
        print(f"            Blended PPI:   ${ppi:.3f} | EV Blended:     ${ev_blended:.3f}")
        print(f"            Disc. Premium: {discovery_premium_factor:.3f} | Mean Peer EV:   ${self.cached_mean_peer_ev_oz or 2.50:.2f}/oz")
        print("─"*75)
        
        # 4. Barbell Component Tapes Row
        print(f" [BARBELL]   AGA.V:  ${p_aga:.3f} (The Spear)")
        print(f"            GROY:   ${p_groy:.2f}  | GMX.TO: ${p_gmx:.2f} | URC.TO: ${p_urc:.2f}")
        print("═"*75 + "\n")

    async def _run_loop(self):
        while True:
            try:
                await self.evaluate_master_architecture()
            except Exception as e:
                print(f"\n[!] Engine Loop Error: {e}")
            await asyncio.sleep(8)


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
                try: await ws.send_text(current_state_json)
                except Exception: dead_sockets.append(ws)
            for ws in dead_sockets: active_websockets.remove(ws)
            last_broadcast_state = current_state_json
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    engine_task = asyncio.create_task(engine._run_loop())
    broadcaster_task = asyncio.create_task(websocket_broadcaster())
    yield
    engine_task.cancel()
    broadcaster_task.cancel()
    try: await asyncio.gather(engine_task, broadcaster_task, return_exceptions=True)
    except: pass

app = FastAPI(title="CommodityEx Terminal Engine", lifespan=lifespan)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    await websocket.send_text(json.dumps(engine.terminal_state))
    try:
        while True: await websocket.receive_text()
    except:
        if websocket in active_websockets: active_websockets.remove(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)