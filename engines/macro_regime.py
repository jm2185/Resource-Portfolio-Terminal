"""MacroRegimeEngine — mechanically moved out of engine.py (Arch 2 split); logic unchanged."""

from engines.util import (  # noqa: F401 — also installs the signal shield
    _save_to_cache, _load_from_cache, _save_to_disk_cache, _load_from_disk_cache, _percentile_rank,
)

import asyncio
import json

import numpy as np
import pandas as pd
import yfinance as yf


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
                        # Fail-FAST (2026-09-19): FRED's edge intermittently silent-drops this egress
                        # IP (proxy CONNECT succeeds, then zero bytes). Tight (connect, read) timeout
                        # so one blocked series can't stall the cycle; fallbacks below carry the read.
                        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(4, 6))
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
                
                # Fetch SOFR and DGS3MO with paired validation to prevent cross-cycle contamination.
                # Concurrent (2026-09-19): when FRED's edge silent-drops this egress IP, sequential
                # fetches serialize minutes of read-timeouts; concurrent fetch collapses the stall
                # to a single fail-fast timeout. FEDFUNDS is fetched once here and reused below.
                from concurrent.futures import ThreadPoolExecutor
                _SOFR_SENTINEL = -999.0
                _DGS3MO_SENTINEL = -999.0
                with ThreadPoolExecutor(max_workers=3) as ex:
                    _f_sofr = ex.submit(fetch_raw_fred, "SOFR", _SOFR_SENTINEL)
                    _f_3mo = ex.submit(fetch_raw_fred, "DGS3MO", _DGS3MO_SENTINEL)
                    _f_ff = ex.submit(fetch_raw_fred, "FEDFUNDS", 4.33)
                    sofr_val = _f_sofr.result()
                    dgs3mo_val = _f_3mo.result()
                    fed_funds = _f_ff.result()
                
                if sofr_val != _SOFR_SENTINEL and dgs3mo_val != _DGS3MO_SENTINEL:
                    # Both fetched successfully — compute live spread
                    sofr_spread = sofr_val - dgs3mo_val
                elif sofr_val != _SOFR_SENTINEL and dgs3mo_val == _DGS3MO_SENTINEL:
                    # SOFR live but DGS3MO failed — estimate DGS3MO from SOFR (typically within ±15bps)
                    dgs3mo_val = sofr_val - 0.05  # Conservative 5bps assumption
                    sofr_spread = sofr_val - dgs3mo_val
                    print(f"[!] SOFR Spread: DGS3MO fetch failed. Using SOFR-derived estimate ({dgs3mo_val:.2f}%)")
                elif sofr_val == _SOFR_SENTINEL and dgs3mo_val != _DGS3MO_SENTINEL:
                    # DGS3MO live but SOFR failed — estimate from Fed Funds (fetched above)
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
                
                # Concurrent (2026-09-19): same rationale as the SOFR/DGS3MO block above —
                # FEDFUNDS was already fetched once and is reused here (no duplicate fetch).
                with ThreadPoolExecutor(max_workers=4) as ex:
                    _f_dgs10 = ex.submit(fetch_raw_fred, "DGS10", 4.45)
                    _f_dgs30 = ex.submit(fetch_raw_fred, "DGS30", 4.98)
                    _f_hy = ex.submit(fetch_raw_fred, "BAMLH0A0HYM2", 2.72)
                    _f_vix = ex.submit(fetch_raw_fred, "VIXCLS", 15.74)
                    return [
                        _f_dgs10.result(), _f_dgs30.result(),
                        _f_hy.result(), sofr_spread,
                        fed_funds, _f_vix.result()
                    ]
            result = await asyncio.to_thread(openbb_fetch)
            # VIX FIX: FRED VIXCLS is a LAGGED daily CLOSE (the prior settle) — it reads ~yesterday's
            # volatility, not today's (the 18.4-displayed vs 16.4-live the operator caught). Prefer the
            # LIVE yfinance ^VIX the prices worker writes every cycle (to yf_live_macro); FRED VIXCLS
            # stays the fallback when yfinance is unavailable. (This live-merge previously ran ONLY in
            # the FRED-failure branch below — which is exactly why a healthy FRED pin read a day stale.)
            _yf_macro = _load_from_cache("yf_live_macro", {})
            try:
                _yf_vix = float(_yf_macro.get("vix"))
            except (TypeError, ValueError):
                _yf_vix = 0.0
            if _yf_vix > 0:
                result[5] = _yf_vix
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
                    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(4, 6))  # fail-fast: FRED edge intermittent silent-drop (2026-09-19)
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

            def _fred_series_indexed(series_id):
                # date-indexed variant: the funding spread joins two series with different
                # publication calendars — positional alignment would smear the spread.
                try:
                    import requests, io
                    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
                    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(4, 6))  # fail-fast: FRED edge intermittent silent-drop (2026-09-19)
                    if res.status_code == 200:
                        df = pd.read_csv(io.StringIO(res.text))
                        if not df.empty and series_id in df.columns:
                            date_col = df.columns[0]
                            df = df.replace('.', np.nan)
                            df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
                            df = df.dropna()
                            if len(df):
                                s = df.set_index(date_col)[series_id].astype(float)
                                return s.tail(lookback_years * 252 + 60)
                except Exception as e:
                    print(f"[!] mri_history FRED indexed fetch failed for {series_id}: {e}")
                return None

            # funding leg: SOFR − DTB3, joined on common dates. Feeds the dynamic percentile
            # bounds for the MRI's funding-stress driver (the static fallback band lives in
            # mri_weights.funding_norm).
            sofr = _fred_series_indexed("SOFR")
            dtb3 = _fred_series_indexed("DTB3")
            if sofr is not None and dtb3 is not None:
                try:
                    joined = pd.concat([sofr.rename('sofr'), dtb3.rename('dtb3')], axis=1).dropna()
                    spread = (joined['sofr'] - joined['dtb3']).dropna()
                    if len(spread):
                        out["funding"] = [float(v) for v in spread.tail(lookback_years * 252).values]
                except Exception as e:
                    print(f"[!] mri_history funding spread build failed: {e}")

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

    def calculate_mri(self, metrics, spot_ag, real_yield, copper, gold, dxy_mom=0.0, return_detail=False, history=None,
                      input_status=None, bear_steepener=None):
        try:
            dxy = float(metrics.get('DXY', {}).get('value', 100))
            ted = float(metrics.get('TED', {}).get('value', 0.3))
            vix = float(metrics.get('VIX', {}).get('value', 18))
            spreads = float(metrics.get('Spreads', {}).get('value', 3.5))
            y10 = float(metrics.get('10Y', {}).get('value', 4.2))
            y30 = float(metrics.get('30Y', {}).get('value', 4.4))
            cftc_net = float(metrics.get('CFTC_Silver_Net_Longs', {}).get('value', 35000.0))

            # Input HONESTY (2026-07-02 reassessment finding #3): the sub-inputs above fall to silent
            # plausible defaults when a metric is missing, and a present-but-STALE/BASELINE metric reads
            # as confidently as a LIVE one. Scan the source metrics so the regime read can carry its own
            # provenance — a metadata flag only; it does NOT change the MRI number (the workers' own
            # fail-closed status ladder decides what LIVE means). ``fabricated`` = metric absent (a
            # hardcoded default stood in); ``degraded`` = present but not LIVE.
            _mri_fab, _mri_deg = [], []
            for _mk in ('DXY', 'TED', 'VIX', 'Spreads', '10Y', '30Y', 'CFTC_Silver_Net_Longs'):
                _m = metrics.get(_mk)
                if not isinstance(_m, dict) or _m.get('value') is None:
                    _mri_fab.append(_mk)
                elif str(_m.get('status', '')).upper() not in ('LIVE', ''):
                    _mri_deg.append(_mk)
            # The POSITIONAL inputs (silver / real_yield / copper / gold) are bare floats with no
            # status of their own, so the scan above never saw them — a cold-start fabricated
            # real_yield flowed into the liquidity block with no flag at all (2026-07-08
            # reassessment: the honesty hole was exactly the width of the commodity/real-yield
            # legs). ``input_status`` lets the caller pass each leg's feed status; absent statuses
            # are skipped (this scan never guesses). Same vocabulary as the metric scan:
            # INITIAL_BASELINE = a fabricated default stood in; anything else non-LIVE = degraded.
            for _pk, _ps in (input_status or {}).items():
                if _ps is None:
                    continue
                _s = str(_ps).upper()
                if _s in ('LIVE', ''):
                    continue
                (_mri_fab if _s == 'INITIAL_BASELINE' else _mri_deg).append(str(_pk))

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

            # Config-driven weight map (2026-08-02 reweight): block and sub-driver weights live in
            # v5_config.mri_weights so the calibration flywheel / propose_param_change can reach the
            # most consequential parameter set in the regime layer (they were hardcoded — reasoned,
            # not tunable). In-code defaults mirror the shipped config. Defensive renormalization: a
            # hand-edited map that doesn't sum to 1 is rescaled, never trusted raw, so a bad edit
            # can't silently inflate or deflate the index.
            w_cfg = self.get_config().get("mri_weights", {}) or {}

            def _weights(group, defaults):
                raw = w_cfg.get(group) or {}
                out = {}
                for k, dflt in defaults.items():
                    try:
                        v = float(raw.get(k, dflt))
                        out[k] = v if v >= 0 else dflt
                    except (TypeError, ValueError):
                        out[k] = dflt
                total = sum(out.values())
                return {k: v / total for k, v in out.items()} if total > 0 else dict(defaults)

            bw = _weights("blocks", {"liquidity_fx": 0.33, "yield_curve": 0.14, "volatility": 0.27,
                                     "commodity": 0.16, "sentiment": 0.10})
            lw = _weights("liquidity_fx", {"real_yield": 0.40, "dxy": 0.30, "dxy_mom": 0.17, "funding": 0.13})
            yw = _weights("yield_curve", {"curve": 0.50, "y10": 0.50})
            vw = _weights("volatility", {"vix": 0.50, "hy": 0.50})
            cw = _weights("commodity", {"silver": 0.60, "copper_gold": 0.40})

            # 1. Liquidity & FX Score — real yield carries the block (the dominant empirical driver
            # of non-yielding metals: the opportunity-cost channel), the dollar second (collinear
            # with rate differentials). The funding leg is the SOFR−DTB3 spread scored against a
            # SOFR-era band (mri_weights.funding_norm) — the old 0.1–0.9 band was calibrated to the
            # discontinued TED spread and pinned this driver near zero permanently — with dynamic
            # percentile bounds once fetch_mri_history seeds a "funding" series.
            fn = w_cfg.get("funding_norm") or {}
            try:
                fn_low, fn_high = float(fn.get("low", 0.0)), float(fn.get("high", 0.5))
            except (TypeError, ValueError):
                fn_low, fn_high = 0.0, 0.5
            if fn_high <= fn_low:
                fn_low, fn_high = 0.0, 0.5
            f_dxy = score("dxy", dxy, lambda: norm(dxy - 100, -5, 8))
            f_ted = score("funding", ted, lambda: norm(ted, fn_low, fn_high))
            f_ry = score("real_yield", real_yield, lambda: norm(real_yield, 0.5, 3.5))
            f_dxymom = norm(dxy_mom, -2.0, 2.0)
            liq_score = (f_dxy * lw["dxy"] + f_ted * lw["funding"] +
                         f_ry * lw["real_yield"] + f_dxymom * lw["dxy_mom"])

            # 2. Yield & Rate Curve Score — steepener-TYPE aware. Slope alone has no clean
            # metals-risk sign: a BEAR steepener (long end rising — term-premium/fiscal stress) is
            # the risk this leg exists to price, while a BULL steepener (front end falling — a
            # cutting cycle) is metals-supportive and must not read as risk. The caller passes the
            # SAME rates_dashboard.bear_steepener flag P2.1/P3/regime_lens read (one interpretation,
            # no divergence; one cycle lagged at worst — curve regimes persist for weeks). Unknown
            # (None: cold start / dashboard dark) keeps the legacy slope read rather than guessing.
            f_curve = norm(y30 - y10, -0.5, 1.5)
            if bear_steepener is False:
                f_curve = 50.0                    # steep-but-not-bear: no term-premium risk signal
            f_y10 = norm(y10, 3.0, 5.5)
            yield_score = f_curve * yw["curve"] + f_y10 * yw["y10"]

            # 3. Volatility & Systemic Stress Score
            f_vix = score("vix", vix, lambda: norm(vix, 12, 35))
            f_hy = score("hy_spread", spreads, lambda: norm(spreads, 2, 7))
            vol_score = f_vix * vw["vix"] + f_hy * vw["hy"]

            # 4. Physical Commodity Regimes (rolling percentile bounds; static fallback pre-seed).
            # Silver's own extension dominates the block (this is a silver book); copper/gold is the
            # secondary complex-heat read, NOT a growth vote — under the extension lens a hot base-
            # metals tape marks the complex extended, which is why its high reading adds risk here.
            cu_au_ratio = copper / gold if gold > 0 else 0.00136
            f_cuau = score("copper_gold", cu_au_ratio, lambda: norm(cu_au_ratio, 0.0010, 0.0018))
            f_ag = score("silver", spot_ag, lambda: norm(spot_ag, 50.0, 100.0))
            comm_score = f_cuau * cw["copper_gold"] + f_ag * cw["silver"]

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
            block_w = bw
            block_s = {"liquidity_fx": liq_score, "yield_curve": yield_score, "volatility": vol_score, "commodity": comm_score, "sentiment": sentiment_score}
            mri = round(max(0, min(100, sum(block_s[k] * block_w[k] for k in block_w))), 1)

            # Two axes, one composite: the composite conflates two orthogonal reads — MRI 60 can mean
            # "VIX 40 + HY blowing out" (crisis: derisk) or "silver at the 95th pct + CFTC crowded"
            # (bull extension: stop adding, let it run). Decompose so consumers can gate on the right
            # one: STRESS (macro/credit — sizer multiplier, health penalty, DEFENSIVE directive) vs
            # EXTENSION (trade heat/crowding — add-gates). Each axis is its member blocks' weighted
            # score renormalized to 0-100; the composite stays the headline dial.
            axes_cfg = w_cfg.get("axes") or {}
            axis_members = {
                "stress": [b for b in (axes_cfg.get("stress") or ["liquidity_fx", "yield_curve", "volatility"]) if b in block_w],
                "extension": [b for b in (axes_cfg.get("extension") or ["commodity", "sentiment"]) if b in block_w],
            }
            axes = {}
            for _axis, _members in axis_members.items():
                _tw = sum(block_w[b] for b in _members)
                axes[_axis] = round(sum(block_s[b] * block_w[b] for b in _members) / _tw, 1) if _tw > 0 else None

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
                # stress vs extension (see the axes comment above) — consumers gate on the axis that
                # matches their action, the composite stays the headline dial
                "axes": axes,
                "drivers": {
                    "dxy_level": round(f_dxy, 0), "sofr_spread": round(f_ted, 0), "real_yield": round(f_ry, 0),
                    # curve_10s30s: the leg computes 30Y−10Y (the old "curve_2s30s" key was a mislabel)
                    "dxy_momentum": round(f_dxymom, 0), "curve_10s30s": round(f_curve, 0), "y10": round(f_y10, 0),
                    "vix": round(f_vix, 0), "hy_spread": round(f_hy, 0), "copper_gold": round(f_cuau, 0),
                    "silver": round(f_ag, 0), "cftc_positioning": round(sentiment_score, 0)
                },
                # Phase 0: per-component bound mode (static vs dynamic rolling-percentile) + the live
                # percentile, so the cockpit can render e.g. "silver @ 92nd pct of 5y range".
                "bounds_basis": basis,
                "dynamic_active": [k for k, v in basis.items() if v.get("mode") == "dynamic"],
                # input provenance — the regime read is honest about what fed it
                "degraded": bool(_mri_fab or _mri_deg),
                "data_fabricated": bool(_mri_fab),
                "fabricated_inputs": _mri_fab,
                "degraded_inputs": _mri_deg,
            }
            return mri, detail
        except Exception as e:
            print(f"[!] MRI calculation error: {e}")
            # The neutral 45.0 is a fail-safe scalar (callers expect a float), but the DETAIL must not
            # look like a genuine read — flag it degraded/fabricated so the cockpit and any consumer can
            # tell a computed regime from a fallback one (2026-07-02 reassessment finding #3).
            return (45.0, {"mri": 45.0, "blocks": [], "top_driver": "n/a", "drivers": {},
                           "axes": {"stress": None, "extension": None},
                           "degraded": True, "data_fabricated": True, "fabricated_inputs": ["ALL"],
                           "error": str(e)}) if return_detail else 45.0
