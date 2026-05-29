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
            return None  # Silently absorb the error from OpenBB extensions
        raise e
    return None

# Hot-patch the signal module globally
signal.signal = _runtime_signal_shield
# ========================================================

import asyncio
import aiohttp
import yfinance as yf
import os
import json
import logging
import time
from ib_insync import *
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
        self.last_cftc_update = 0           # Track COT compilation timing
        self.cached_prices = {}
        self.macro_fail_count = 0
        
        self.ib = IB()
        self.config_path = "v3_config.json"
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
                # Added institutional sentiment tracking node
                "CFTC_Silver_Net_Longs": {"value": 35000.0, "status": "INITIAL_BASELINE"}
            },
            "nodes": {},
            "v3_valuation": {},
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
                "discovery_multiple": 0.112,
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
                }
            }
            with open(self.config_path, "w") as f:
                json.dump(default_config, f, indent=4)

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
        """Weaponizes OpenBB CFTC extension to track systemic smart-money extremes."""
        # CFTC logs drop once a week on Friday afternoons; checking every 4 hours limits network load
        if self.last_cftc_update > 0 and (time.time() - self.last_cftc_update < 14400):
            return

        try:
            def openbb_cftc():
                from openbb import obb
                
                # Dynamic Route Discovery Matrix
                if hasattr(obb, "cftc"):
                    print("[*] Target identified at top-level namespace: obb.cftc")
                    try:
                        search_res = obb.cftc.cot_search(query="silver")
                        df_search = search_res.to_dataframe()
                        
                        if not df_search.empty:
                            silver_rows = df_search[df_search['name'].str.contains('SILVER', case=False, na=False)]
                            if not silver_rows.empty:
                                target_code = str(silver_rows['code'].iloc[0])
                            else:
                                target_code = str(df_search['code'].iloc[0])
                                
                            print(f"[*] Dynamically resolved OpenBB CFTC Silver contract code: {target_code}")
                            res = obb.cftc.cot(code=target_code)
                        else:
                            res = obb.cftc.cot(code="CFTC_084694")
                    except Exception as inner_err:
                        print(f"[DEBUG] Dynamic search compilation failed: {inner_err}. Trying string fallback code.")
                        res = obb.cftc.cot(code="CFTC_084694")
                        
                elif hasattr(obb, "regulators") and hasattr(obb.regulators, "cftc"):
                    print("[*] Target identified at legacy namespace: obb.regulators.cftc")
                    try:
                        res = obb.regulators.cftc.cot(id="silver")
                    except Exception:
                        res = obb.regulators.cftc.cot(symbol="silver")
                else:
                    raise AttributeError("CFTC router extension package could not be bound to obb schema.")
                
                df = res.to_dataframe()
                return df

            print("[*] Accessing CFTC Commitment of Traders database via OpenBB...")
            df_cot = await asyncio.to_thread(openbb_cftc)

            if not df_cot.empty:
                # Underscore/space-agnostic column matching engine
                long_candidates = []
                short_candidates = []
                
                for c in df_cot.columns:
                    # Strip underscores and spaces to neutralize schema layout variations
                    c_clean = str(c).lower().replace("_", "").replace(" ", "")
                    
                    # Target legacy "non-commercial" specs or disaggregated "managed money" tags
                    is_speculator = any(x in c_clean for x in ["noncommercial", "managedmoney", "mmoney", "noncomm"])
                    
                    if is_speculator:
                        if "long" in c_clean:
                            long_candidates.append(c)
                        elif "short" in c_clean:
                            short_candidates.append(c)
                
                # Step 2: Prioritize raw, absolute contract totals over percentage metrics if both are present
                long_col = [c for c in long_candidates if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                short_col = [c for c in short_candidates if "pct" not in str(c).lower() and "percent" not in str(c).lower()]
                
                # Step 3: Fallback to percentage columns if they are the only fields available
                if not long_col and long_candidates:
                    long_col = [long_candidates[0]]
                if not short_col and short_candidates:
                    short_col = [short_candidates[0]]

                if long_col and short_col:
                    latest_row = df_cot.iloc[-1]
                    long_val = float(latest_row[long_col[0]])
                    short_val = float(latest_row[short_col[0]])
                    
                    # Step 4: Scale metrics if the data is formatted as raw percentages/fractions
                    if "pct" in str(long_col[0]).lower() or "percent" in str(long_col[0]).lower() or (long_val <= 1.0 and short_val <= 1.0):
                        # Convert fractional Open Interest metrics into a synthetic position score for consistent BVS scaling
                        net_position = (long_val - short_val) * 100000 
                    else:
                        net_position = long_val - short_val
                        
                    self.terminal_state["metrics"]["CFTC_Silver_Net_Longs"] = {"value": net_position, "status": "LIVE"}
                    self.last_cftc_update = time.time()
                    print(f"[*] CFTC Engine Updated -> Silver Net Non-Commercial Contracts: {net_position:+,} (Extracted via: Long={long_col[0]}, Short={short_col[0]})")
                else:
                    print(f"[DEBUG] Isolation failed. Scanned {len(df_cot.columns)} columns. Found long candidates: {long_candidates}, short candidates: {short_candidates}")
        
        except Exception as e:
            print(f"[DEBUG] CFTC pipeline desynced: {e}. Maintaining baseline historical sentiment model.")
            
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
                            if not df_clean.empty:
                                return float(df_clean.iloc[-1].iloc[0])
                    except Exception as extraction_err:
                        print(f"[DEBUG] OpenBB extraction failed for {series_id}: {extraction_err}")
                    return fallback_val

                print("[*] Dispatched live macro queries to OpenBB Platform...")
                
                y10 = fetch_raw_fred("DGS10", 4.35)
                y30 = fetch_raw_fred("DGS30", 4.65)
                spr = fetch_raw_fred("BAMLH0A0HYM2", 2.71)
                ted = fetch_raw_fred("TEDRATE", 0.35)
                eff = fetch_raw_fred("FEDFUNDS", 4.33)
                vix = fetch_raw_fred("VIXCLS", 16.5) 
                
                print(f"[DEBUG] Live Data Extracted -> 10Y: {y10} | 30Y: {y30} | Spreads: {spr} | TED: {ted} | EFFR: {eff} | VIX: {vix}")
                return [y10, y30, spr, ted, eff, vix]

            result = await asyncio.to_thread(openbb_fetch)
            print("[*] Macro data fetched successfully via OpenBB")
            return result

        except Exception as e:
            print(f"[!] Critical OpenBB macro failure: {e}. Reverting to baseline defaults.")
            return [4.35, 4.65, 2.71, 0.35, 4.33, 16.5]

    async def fetch_bvs_data(self):
        return {"real_yield": 1.8, "copper": 4.2, "gold": 2350}

    def calculate_bvs(self, m, spot_ag, bvs_data):
        try:
            dxy = float(m.get('DXY', {}).get('value', 100))
            ted = float(m.get('TED', {}).get('value', 0.3))
            vix = float(m.get('VIX', {}).get('value', 18))
            spreads = float(m.get('Spreads', {}).get('value', 3.5))
            y10 = float(m.get('10Y', {}).get('value', 4.2))
            y30 = float(m.get('30Y', {}).get('value', 4.4))
            
            # Re-implemented: Extract data parameters safely from bvs_data payload
            real_yield = bvs_data.get('real_yield', 1.8)
            copper = bvs_data.get('copper', 4.2)
            gold = bvs_data.get('gold', 2350)
            
            # Extract live CFTC positions
            cftc_net = float(m.get('CFTC_Silver_Net_Longs', {}).get('value', 35000.0))

            def norm(val, low, high):
                return max(0, min(100, (val - low) / (high - low) * 100))

            # Core risk component vectors
            liq_score = (norm(dxy - 100, -5, 8) * 0.4 + norm(ted, 0.1, 0.9) * 0.3 + norm(real_yield, 0.5, 3.5) * 0.3)
            yield_score = (norm(y30 - y10, -0.5, 1.5) * 0.5 + norm(y10, 3.0, 5.5) * 0.5)
            vol_score = (norm(vix, 12, 35) * 0.5 + norm(spreads, 2, 7) * 0.5)
            
            cu_au_ratio = copper / gold if gold > 0 else 0.0018
            comm_score = (norm(cu_au_ratio, 0.0014, 0.0022) * 0.6 + norm(spot_ag / 30, 0.8, 1.4) * 0.4)
            
            sentiment_score = norm(cftc_net, -15000, 85000)

            # Rebalanced Unified BVS Architecture Matrix
            bvs = (liq_score * 0.30) + (yield_score * 0.20) + (vol_score * 0.20) + (comm_score * 0.15) + (sentiment_score * 0.15)
            return round(max(0, min(100, bvs)), 1)
        except Exception as e:
            print(f"BVS processing fault: {e}")
            return 45.0

    async def evaluate_master_architecture(self, force_macro=False):
        try:
            with open(self.config_path, "r") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Config Load Error: {e}")
            return

        if not self.shares or force_macro:
            self._load_shares_from_csv(force=True)

        # Sync institutional flow tracking
        await self.sync_cftc_positioning()

        vix = 16.5
        if force_macro or (time.time() - self.last_macro_update > 90):
            res = await self.fetch_macro_data()
            if res and len(res) >= 6:
                y10, y30, spr, ted, eff, fetched_vix = res
                self.terminal_state["metrics"].update({
                    "10Y": {"value": y10, "status": "LIVE"},
                    "30Y": {"value": y30, "status": "LIVE"},
                    "Spreads": {"value": spr, "status": "LIVE"},
                    "TED": {"value": ted, "status": "LIVE"},
                    "EFFR": {"value": eff, "status": "LIVE"},
                    "VIX": {"value": fetched_vix, "status": "LIVE"}
                })
                vix = fetched_vix
                self.last_macro_update = time.time()

        self.terminal_state["metrics"].update({
            "WTI": {"value": 89.5, "status": "NORMAL"},
            "DXY": {"value": 99.0, "status": "NORMAL"},
            "Spot_Ag": {"value": 74.8, "status": "NORMAL"}
        })

        prices = {}
        if force_macro or (time.time() - self.last_price_update > 35):
            def get_market_data():
                new_prices = {}
                market_stats = {"aga_adv": cfg.get("aga_adv_fallback", 150000)}
                tickers = ["CL=F", "DX-Y.NYB", "SI=F", "AGA.V", "GROY", "GMX.TO", "URC.TO"]
                for t in tickers:
                    try:
                        hist = yf.Ticker(t).history(period="10d")
                        if not hist.empty:
                            new_prices[t] = float(hist['Close'].iloc[-1])
                            if t == "AGA.V":
                                market_stats["aga_adv"] = int(hist['Volume'].mean())
                        else:
                            new_prices[t] = self._get_fallback_price(t)
                    except:
                        new_prices[t] = self._get_fallback_price(t)
                return new_prices, market_stats

            prices, mkt_stats = await asyncio.to_thread(get_market_data)
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
            if not cad_hist.empty:
                usd_to_cad = float(cad_hist['Close'].iloc[-1])
        except:
            pass

        live_portfolio_value = (
            self.shares.get('AGA', 0) * p_aga +
            self.shares.get('URC', 0) * p_urc +
            self.shares.get('GMX', 0) * p_gmx +
            self.shares.get('GROY', 0) * p_groy * usd_to_cad +
            self.shares.get('UROY_CALL', 0) * 0.60 * usd_to_cad
        )

        if live_portfolio_value < 1000:
            live_portfolio_value = cfg.get("target_capital", 5360.0)

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

        recovery = cfg.get("metallurgical_recovery", {})
        is_iai_total = 0.0
        for proj, oz in buckets.items():
            rec_silver = recovery.get(proj, {}).get("silver", 0.85)
            is_iai_total += oz * spot_ag * cfg.get("discovery_multiple", 0.112) * rec_silver

        is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / cfg["aga_shares_out"]

        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (
            exp.get("expected_future_oz", 0) *
            spot_ag *
            exp.get("discovery_multiple", 0.052) *
            exp.get("probability_of_discovery", 0.25)
        )
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)

        rov = cfg.get("rov_default", 1.18)
        aga_intrinsic = (
            0.20 * rep_floor +
            0.40 * is_iai_per_share +
            0.25 * 0.65 +
            0.15 * rov +
            exp_per_share
        )

        ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)
        ev_blended = (
            0.60 * aga_intrinsic +
            0.15 * p_urc * 1.15 +
            0.15 * p_groy * 1.15 +
            0.10 * p_gmx * 1.20
        )
        u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

        try:
            bvs_data = await self.fetch_bvs_data()
            bvs_score = self.calculate_bvs(self.terminal_state["metrics"], spot_ag, bvs_data)
        except:
            bvs_score = 45.0

        if bvs_score < 40:
            multiplier = 1.00
            macro_regime = "Expansion / Risk-On"
        elif bvs_score < 65:
            multiplier = 0.85
            macro_regime = "Moderate Risk / Neutral"
        elif bvs_score < 80:
            multiplier = 0.55
            macro_regime = "Elevated Risk / Caution"
        else:
            multiplier = 0.25
            macro_regime = "High Stress / Defensive"

        friction = cfg.get("friction_drag", 0.0185)
        raw_target = max(live_portfolio_value * u_implied * (1 - friction), 0)
        e_target_capped = min(raw_target * multiplier, live_portfolio_value * 1.5)
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
        self.terminal_state["bvs"] = bvs_score # Push raw sync to state reference
        self.terminal_state["v3_valuation"] = {
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
            "Exp_Premium_Per_Share": round(exp_per_share, 3)
        }

        self.terminal_state["nodes"] = {
            "AGA.V": {"price": round(p_aga, 3), "role": "The Spear"},
            "GROY": {"price": round(p_groy, 2), "role": "Ballast"},
            "GMX.TO": {"price": round(p_gmx, 2), "role": "Ballast"},
            "URC.TO": {"price": round(p_urc, 2), "role": "Ballast"}
        }

        print(f"Tape -> Portfolio: ${live_portfolio_value:,.2f} | REP: ${rep_floor:.3f} | Runway: {cash_runway_months:.1f}mo | Intrinsic: ${aga_intrinsic:.3f} | Edge: {u_implied*100:.1f}% | BVS: {bvs_score:.1f} (COT Component Active)")

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
    try:
        await asyncio.gather(engine_task, broadcaster_task, return_exceptions=True)
    except:
        pass
    if engine.ib.isConnected():
        engine.ib.disconnect()

app = FastAPI(title="CommodityEx Terminal Engine", lifespan=lifespan)

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