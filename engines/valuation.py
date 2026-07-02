"""ValuationEngine — mechanically moved out of engine.py (Arch 2 split); logic unchanged."""

from engines import util as _util               # noqa: F401 — installs the signal shield

import json

import numpy as np


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
