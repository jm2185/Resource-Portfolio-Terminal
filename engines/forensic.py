"""ForensicEngine — mechanically moved out of engine.py (Arch 2 split); logic unchanged."""

from engines import util as _util               # noqa: F401 — installs the signal shield

import asyncio
import json
import logging
import os
import threading
import time

import yfinance as yf


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
        
        # Runway-aware dilution (forensic honesty): a pre-revenue explorer funds itself BY issuing
        # equity, so raw QoQ share expansion mislabels a one-time strategic raise as decay. Net it
        # against the runway it bought — a step-up that leaves the treasury comfortably past the
        # runway bar is FUNDING (insulated); a raise that doesn't, or a catastrophic single-period
        # expansion, still fails. Config-tunable (dilution_runway_aware) + reversible; the manual
        # dilution_insulated waiver remains an additional escape hatch.
        import forensic_gates
        real_dilution_pass, dilution_reason, runway_insulated = forensic_gates.runway_aware_dilution_pass(
            dilution=dilution, runway_months=runway,
            max_qoq_dilution_pct=forensic_thresholds.get("max_qoq_dilution_pct", 2.0),
            runway_min_months=forensic_thresholds.get("runway_min_months", 18.0),
            enabled=forensic_thresholds.get("dilution_runway_aware", True),
            runway_comfort_mult=forensic_thresholds.get("dilution_runway_comfort_mult", 1.0),
            catastrophic_pct=forensic_thresholds.get("dilution_catastrophic_pct", 50.0))
        overrides = cfg.get("forensic_overrides", {}).get(ticker, {})
        dilution_override = self._override_active(overrides, "dilution_insulated", today, max_validity_days)
        dilution_pass = real_dilution_pass or dilution_override

        if dilution_pass:
            score += 1.0
            insulated = dilution_override and not real_dilution_pass    # manual waiver carried it
            if insulated:
                desc = "Dilution Insulated (manual waiver)"
            elif runway_insulated:
                desc = "Dilution funded runway — insulated"
            else:
                desc = "Dilution < 2% QoQ"
            details["dilution"] = {"pass": True, "value": dilution, "desc": f"{desc} ({dilution*100:.1f}%)",
                                   "overridden": insulated, "runway_insulated": runway_insulated,
                                   "reason": dilution_reason}
            if insulated:
                overrides_applied.append({"test": "dilution", "justification": overrides.get("justification", ""),
                                          "expiry": overrides.get("expiry", ""),
                                          "days_until_expiry": self._override_days_left(overrides, today),
                                          "requires_confirmation": True})
        else:
            details["dilution"] = {"pass": False, "value": dilution,
                                   "desc": f"Share count expanded ({dilution*100:.1f}%)",
                                   "overridden": False, "runway_insulated": False, "reason": dilution_reason}

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
