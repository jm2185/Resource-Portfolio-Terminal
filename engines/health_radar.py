"""HealthRadarEngine — mechanically moved out of engine.py (Arch 2 split); logic unchanged."""

from engines import util as _util               # noqa: F401 — installs the signal shield

import json


class HealthRadarEngine:
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

    def calculate_health_rating(self, jsf_score, mri_score, expected_shortfall_95, is_stale):
        cfg = self.get_config()
        radar_cfg = cfg.get("health_radar", {})
        
        forensics_mult = radar_cfg.get("forensics_multiplier", 1.25)
        macro_mult = radar_cfg.get("macro_multiplier", 1.5)
        stale_penalty = radar_cfg.get("stale_penalty", 2.0)
        es_cfg = radar_cfg.get("es_penalty", {
            "free_pct": -5.0, "ref_pct": -10.0, "ref_penalty": 1.0, "exponent": 1.5
        })

        score = 10.0
        
        # 1. Forensics penalty
        score -= (4.0 - jsf_score) * forensics_mult
        
        # 2. Macro penalty
        score -= (mri_score / 100.0) * macro_mult
        
        # 3. Pipeline cache penalty
        if is_stale:
            score -= stale_penalty
            
        # 4. Tail Risk expected shortfall penalty (continuous, convex, uncapped)
        # Penalty grows as a power of how far the daily 95% ES falls below the no-penalty band,
        # anchored so the documented reference point (ES = ref_pct -> ref_penalty) is preserved.
        # gamma > 1 makes deep tails hurt disproportionately more (no flat -1.0 saturation cap).
        free_mag = -es_cfg.get("free_pct", -5.0)
        ref_mag = -es_cfg.get("ref_pct", -10.0)
        gamma = es_cfg.get("exponent", 1.5)
        excess = max(0.0, (-expected_shortfall_95) - free_mag)
        ref_excess = max(1e-9, ref_mag - free_mag)
        k = es_cfg.get("ref_penalty", 1.0) / (ref_excess ** gamma)
        es_penalty = k * (excess ** gamma)

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
        kelly = val_data.get("Kelly_Multiple", 1.0)          # risk-adjusted target leverage f* (<= L_max)
        # Over/under-allocation vs the Kelly-optimal target (bounded, correctly-oriented). Falls back to
        # 1.0 (at-target) when absent so legacy/partial state payloads do not false-trigger a trim.
        alloc_ratio = val_data.get("allocation_ratio", 1.0)
        caution_ratio = self.get_config().get("v5_guardrails", {}).get("allocation_directive", {}).get("caution_ratio", 1.5)
        adv_cap = val_data.get("ADV_Cap_CAD", 0.0)
        adv_cap_pct = val_data.get("ADV_Cap_Percentage", 15.0)
        # Fail CONSERVATIVE if the intrinsic is missing: a stale non-zero default (was 4.18) would
        # scream "EXPLOIT SPEAR ARBITRAGE" at phantom upside. 0.0 -> negative spear upside -> no signal.
        aga_intrinsic = val_data.get("AGA_Intrinsic", 0.0)
        
        priorities = []

        # Priority 1: Valuation / Spear Arbitrage — gate on the spear's OWN intrinsic-vs-price upside
        # (recalibrated for the de-inflated valuation), not the structurally-lower blended portfolio edge.
        spear_upside = (aga_intrinsic / p_aga - 1.0) * 100 if p_aga > 0 else 0.0
        spear_arb_thresh = self.get_config().get("directive_thresholds", {}).get("spear_arbitrage_pct", 50.0)
        if spear_upside > spear_arb_thresh:
            priorities.append({
                "icon": "shopping_cart_outlined",
                "color": "green",
                "title": "EXPLOIT SPEAR ARBITRAGE",
                "desc": f"AGA.V market price (${p_aga:.2f}) is trading at a discount to triangulated Intrinsic (${aga_intrinsic:.2f}) with {spear_upside:.0f}% upside (blended portfolio edge {implied_edge:.0f}%)."
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
        if alloc_ratio > caution_ratio:
            priorities.append({
                "icon": "balance_outlined",
                "color": "orange",
                "title": "TRIM OVERALLOCATION DRAG",
                "desc": f"Book is holding {alloc_ratio:.2f}x the risk-adjusted Kelly target (f*={kelly:.2f}x of capital). Trim barbell assets back toward the target to reclaim risk budget."
            })
        else:
            priorities.append({
                "icon": "check_circle_outline",
                "color": "green",
                "title": "ALLOCATIONS WITHIN RISK BOUNDS",
                "desc": f"Deployment is within the Kelly band ({alloc_ratio:.2f}x target, f*={kelly:.2f}x of capital). No urgent trim directives active."
            })
            
        return priorities
