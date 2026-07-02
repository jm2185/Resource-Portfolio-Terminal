"""PeerEngine — mechanically moved out of engine.py (Arch 2 split); logic unchanged."""

from engines.util import (  # noqa: F401 — also installs the signal shield
    _save_to_cache, _load_from_cache, _robust_adv_shares,
)

import asyncio
import json

import yfinance as yf


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
