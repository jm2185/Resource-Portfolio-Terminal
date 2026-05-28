import asyncio
import aiohttp
import yfinance as yf
import os
import json
import threading
import logging
import time
import nest_asyncio
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
        self.last_price_update = 0          # ← Added
        self.cached_prices = {}             # ← Added
        
        self.ib = IB()
        self.config_path = "v3_config.json"
        self._ensure_config_exists()

        self.shares = {}
        self.last_csv_mtime = 0

        self.terminal_state = {
            "macro_regime": "Pending Data...",
            "directive": "Waiting for tape...",
            "metrics": {
                "10Y": {"value": 0.0, "status": "NORMAL"},
                "30Y": {"value": 0.0, "status": "NORMAL"},
                "WTI": {"value": 0.0, "status": "NORMAL"},
                "DXY": {"value": 0.0, "status": "NORMAL"},
                "Spot_Ag": {"value": 0.0, "status": "NORMAL"},
                "Spreads": {"value": 0.0, "status": "NORMAL"},
                "TED": {"value": 0.0, "status": "NORMAL"},
                "EFFR": {"value": 0.0, "status": "NORMAL"},
                "VIX": {"value": 0.0, "status": "NORMAL"}
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
                "target_capital": 5200.0,
                "friction_drag": 0.0185,
                "aga_shares_out": 208600000,
                "aga_adv_fallback": 150000,
                "total_ageq_oz": 246600000,
                "discovery_multiple": 0.112,
                "rov_default": 1.18,
                "conservatism_scalar": 0.88,
                "catalyst_probabilities": {
                    "belmont_tailings": 0.92,
                    "red_mtn_drill": 0.73,
                    "hughes_drill": 0.45,
                    "mogollon_drill": 0.18,
                    "kennedy_longterm": 0.10
                },
                "structural_weights": {
                    "belmont_tailings": 0.35,
                    "red_mtn_drill": 0.45,
                    "hughes_drill": 0.15,
                    "mogollon_drill": 0.05,
                    "kennedy_longterm": 0.05
                },
                "rep_floor_params": {
                    "cash_treasury_m": 53.07,
                    "stressed_resource_per_oz": 0.60,
                    "permitting_infra_premium_m": 10.0,
                    "conservatism_scalar": 0.85
                },
                "cash_burn": {
                    "monthly_burn_rate": 750000,
                    "warning_threshold_months": 24
                },
                "metallurgical_recovery": {
                    "belmont_tailings": {"silver": 0.89, "gold": 0.95},
                    "red_mountain": {"silver": 0.85, "gold": 0.94},
                    "hughes": {"silver": 0.87, "gold": 0.95},
                    "mogollon": {"silver": 0.78, "gold": 0.92},
                    "kennedy": {"silver": 0.75, "gold": 0.90}
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

    async def fetch_bvs_data(self):
        try:
            real_yield = 1.8
            try:
                api_key = os.environ.get("FRED_API_KEY", "c99ae6c798904c0eb0762eba0507916a")
                url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFII10&api_key={api_key}&file_type=json&sort_order=desc&limit=5"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        data = await resp.json()
                        real_yield = next((float(obs['value']) for obs in data['observations'] if obs['value'] != '.'), 1.8)
            except:
                pass

            copper = gold = 4.2
            try:
                cu = yf.Ticker("HG=F").history(period="5d")
                au = yf.Ticker("GC=F").history(period="5d")
                if not cu.empty:
                    copper = float(cu['Close'].iloc[-1])
                if not au.empty:
                    gold = float(au['Close'].iloc[-1])
            except:
                pass

            return {
                "real_yield": real_yield,
                "copper": copper,
                "gold": gold
            }
        except Exception as e:
            print(f"BVS data fetch error: {e}")
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

            def norm(val, low, high):
                return max(0, min(100, (val - low) / (high - low) * 100))

            liq_score = (norm(dxy - 100, -5, 8) * 0.4 +
                         norm(ted, 0.1, 0.9) * 0.3 +
                         norm(real_yield, 0.5, 3.5) * 0.3)

            yield_score = (norm(y30 - y10, -0.5, 1.5) * 0.5 +
                           norm(y10, 3.0, 5.5) * 0.5)

            vol_score = (norm(vix, 12, 35) * 0.5 +
                         norm(spreads, 2, 7) * 0.5)

            cu_au_ratio = copper / gold if gold > 0 else 0.0018
            comm_score = (norm(cu_au_ratio, 0.0014, 0.0022) * 0.6 +
                          norm(spot_ag / 30, 0.8, 1.4) * 0.4)

            bvs = (liq_score * 0.40) + (yield_score * 0.25) + (vol_score * 0.20) + (comm_score * 0.15)
            return round(max(0, min(100, bvs)), 1)

        except Exception as e:
            print(f"BVS calculation error: {e}")
            return 45.0

    async def fetch_macro_data(self):
        api_key = os.environ.get("FRED_API_KEY", "c99ae6c798904c0eb0762eba0507916a")
        try:
            async with aiohttp.ClientSession() as session:
                urls = {
                    "10y": f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={api_key}&file_type=json&sort_order=desc&limit=7",
                    "30y": f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS30&api_key={api_key}&file_type=json&sort_order=desc&limit=7",
                    "spreads": f"https://api.stlouisfed.org/fred/series/observations?series_id=BAMLH0A0HYM2&api_key={api_key}&file_type=json&sort_order=desc&limit=7",
                    "ted": f"https://api.stlouisfed.org/fred/series/observations?series_id=TEDRATE&api_key={api_key}&file_type=json&sort_order=desc&limit=7",
                    "effr": f"https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&api_key={api_key}&file_type=json&sort_order=desc&limit=7",
                    "vix": f"https://api.stlouisfed.org/fred/series/observations?series_id=VIXCLS&api_key={api_key}&file_type=json&sort_order=desc&limit=7"
                }
                tasks = [session.get(url) for url in urls.values()]
                responses = await asyncio.gather(*tasks)
                data = [await res.json() for res in responses]
                return [next(float(obs['value']) for obs in d['observations'] if obs['value'] != '.') for d in data]
        except Exception as e:
            print(f"\n[!] Macro Fetch Error: {e}")
            return None

    async def evaluate_master_architecture(self, force_macro=False):
        # 1. Load Config
        try:
            with open(self.config_path, "r") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Config Load Error: {e}")
            return

        # 2. Load latest shares from CSV if needed
        if not self.shares or force_macro:
            self._load_shares_from_csv(force=True)

        # 3. Macro Data with full metrics population
        vix = 16.5
        if force_macro or (time.time() - self.last_macro_update > 90):
            res = await self.fetch_macro_data()
            if res and len(res) >= 6:
                y10, y30, spr, ted, eff, fetched_vix = res
                self.terminal_state["metrics"].update({
                    "10Y": {"value": y10, "status": "NORMAL"},
                    "30Y": {"value": y30, "status": "NORMAL"},
                    "Spreads": {"value": spr, "status": "NORMAL"},
                    "TED": {"value": ted, "status": "NORMAL"},
                    "EFFR": {"value": eff, "status": "NORMAL"},
                    "VIX": {"value": fetched_vix, "status": "NORMAL"}
                })
                vix = fetched_vix
                self.last_macro_update = time.time()

        # Force populate missing macro metrics (critical fix)
        self.terminal_state["metrics"].update({
            "WTI": {"value": 89.5, "status": "NORMAL"},
            "DXY": {"value": 99.0, "status": "NORMAL"},
            "Spot_Ag": {"value": 74.8, "status": "NORMAL"}
        })

        # 4. Price Data
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
                            if t == "AGA.V" and not hist.empty:
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

        # Update Spot_Ag from price data
        self.terminal_state["metrics"]["Spot_Ag"]["value"] = spot_ag

        # 5. Live Portfolio Value (CAD)
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

        # 6. Dynamic REP Floor
        rf = cfg["rep_floor_params"]
        cash_component = rf["cash_treasury_m"] * 1_000_000
        infra_component = rf["permitting_infra_premium_m"] * 1_000_000
        buckets = cfg.get("project_buckets_oz_AgEq", {})
        total_oz = sum(buckets.values())
        resource_component = total_oz * rf["stressed_resource_per_oz"]
        total_rep_value = cash_component + resource_component + infra_component
        rep_floor = (total_rep_value * rf["conservatism_scalar"]) / cfg["aga_shares_out"]

        # 7. Cash Runway
        monthly_burn = cfg["cash_burn"]["monthly_burn_rate"]
        cash_runway_months = cash_component / monthly_burn if monthly_burn > 0 else 999.0

        # 8. Project Tiering + Recovery
        recovery = cfg.get("metallurgical_recovery", {})
        is_iai_total = 0.0
        for proj, oz in buckets.items():
            rec_silver = recovery.get(proj, {}).get("silver", 0.85)
            is_iai_total += oz * spot_ag * cfg.get("discovery_multiple", 0.112) * rec_silver

        is_iai_per_share = (is_iai_total * cfg.get("conservatism_scalar", 0.88)) / cfg["aga_shares_out"]

        # 9. Exploration Upside
        exp = cfg.get("exploration_upside", {})
        exp_premium_total = (
            exp.get("expected_future_oz", 0) *
            spot_ag *
            exp.get("discovery_multiple", 0.052) *
            exp.get("probability_of_discovery", 0.25)
        )
        exp_per_share = exp_premium_total / cfg["aga_shares_out"] * exp.get("weight", 0.12)

        # 10. AGA Intrinsic
        rov = cfg.get("rov_default", 1.18)
        aga_intrinsic = (
            0.20 * rep_floor +
            0.40 * is_iai_per_share +
            0.25 * 0.65 +
            0.15 * rov +
            exp_per_share
        )

        # 11. PPI, EV, Implied Edge
        ppi = (0.60 * p_aga) + (0.15 * p_urc) + (0.15 * p_groy) + (0.10 * p_gmx)
        ev_blended = (
            0.60 * aga_intrinsic +
            0.15 * p_urc * 1.15 +
            0.15 * p_groy * 1.15 +
            0.10 * p_gmx * 1.20
        )
        u_implied = (ev_blended - ppi) / ppi if ppi > 0 else 0.0

        # 12. BVS
        try:
            bvs_data = await self.fetch_bvs_data()
            bvs_score = self.calculate_bvs(self.terminal_state["metrics"], spot_ag, bvs_data)
        except:
            bvs_score = 45.0

        # 13. Target Capital & Kelly
        if bvs_score < 40:
            multiplier = 1.00
        elif bvs_score < 65:
            multiplier = 0.85
        elif bvs_score < 80:
            multiplier = 0.55
        else:
            multiplier = 0.25

        friction = cfg.get("friction_drag", 0.0185)
        raw_target = max(live_portfolio_value * u_implied * (1 - friction), 0)
        e_target_capped = min(raw_target * multiplier, live_portfolio_value * 1.5)
        kelly_multiple = live_portfolio_value / e_target_capped if e_target_capped > 100 else 1.0

        # 14. Update Terminal State
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

        print(f"Tape -> Portfolio: ${live_portfolio_value:,.2f} | REP: ${rep_floor:.3f} | Runway: {cash_runway_months:.1f}mo | Intrinsic: ${aga_intrinsic:.3f} | Edge: {u_implied*100:.1f}% | BVS: {bvs_score:.1f}")
    async def _run_loop(self):
        while True:
            try:
                if not self.ib.isConnected():
                    await self.ib.connectAsync(self.host, self.port, clientId=self.client_id, readonly=True)
                    spear = Stock('AGA', 'SMART', 'CAD')
                    ballast = [Stock('GROY', 'SMART', 'USD'), Stock('GMX', 'SMART', 'CAD'), Stock('URC', 'SMART', 'CAD')]
                    self.ib.qualifyContracts(spear, *ballast)
                await self.evaluate_master_architecture()
            except Exception as e:
                print(f"\n[!] Engine Loop Error: {e}")
            await asyncio.sleep(5)

    def start_background_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        nest_asyncio.apply(loop)
        loop.run_until_complete(self._run_loop())


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
    engine_thread = threading.Thread(target=engine.start_background_thread, daemon=True)
    engine_thread.start()
    broadcaster_task = asyncio.create_task(websocket_broadcaster())
    yield
    broadcaster_task.cancel()

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