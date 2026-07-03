"""PortfolioSizer — mechanically moved out of engine.py (Arch 2 split); logic unchanged."""

from engines.util import (  # noqa: F401 — also installs the signal shield
    _resolve_barbell_weights, _robust_adv_shares,
)

from book_invariants import SPEAR_CEILING  # the 60% invariant, one shared source of truth
import asyncio
import json

import numpy as np
import pandas as pd
import yfinance as yf


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
        SPEAR_CEILING_STRUCTURAL = SPEAR_CEILING   # book_invariants: the one shared 60% source
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
