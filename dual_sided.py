"""
dual_sided.py — the conventional-core valuation engine: price the TWO POLES of conventional equity
correctly, on one common schema (Phase 2 of docs/archive/DUAL_SIDED_TIV_BUILD_SPEC.md).

The resource engine's ``triangulate`` collapses cost/market/income into ONE blended number — which
mis-prices the two poles of conventional equity in OPPOSITE directions. The fix is two archetype-tuned
solvers, run on EVERY conventional name (not one-or-the-other), each emitting the SAME schema so a
premium monopoly and a deep-value turnaround can be weighed on one Conviction-Mode screen:

  • COMPOUNDER (reverse-DCF / expectations) — "what growth × duration is priced in, and is it real?"
    Inverts a 2-stage DCF to read the market-IMPLIED growth, then prices the ladder at a base-rate-
    anchored ACHIEVABLE growth. MoS lives in the durability of compounding; the failure mode is the
    TORPEDO (multiple compression on a growth miss), so the floor is the de-rated-multiple value. V in
    VALUE mode (fair-value-centric). [TMX.]

  • DEEP_VALUE (sum-of-the-parts + asset/FCF floor) — "what are the pieces worth, and where's the
    floor?" SOTP the segments at segment multiples; the floor is the conventional REP — NAV or a
    stressed-FCF capitalization. MoS lives in the entry DISCOUNT (so φ is real); the failure mode is
    the VALUE TRAP. V in ASYMMETRY mode (the discount is the convexity). [EEFT.]

This is the NEW SEAM the spec describes: for a conventional name the router does NOT pick one archetype
— this orchestrator runs BOTH and (Phase 3) reports the divergence spread. It REUSES the engine's math
(``asymmetry_rating.compute_asymmetry_rating`` for the rating/ladder/ribbon, the confidence-tilted
blend, ``valuation_ledger.method_spread``) — it never reimplements it. The regime tilt enters exactly
ONE leg (income), scalar — so NO change to the resource ``RegimeImpactVector`` tuple.

Fail-closed: missing segment splits ⇒ the deep-value solver runs on what it has, FLAGS the hole,
widens the band, lowers conviction — never a fake default. Base-rate probabilities are ASSERTED (n=0
realized) until CALIBRATION grades enough closed conventional theses (Phase 6). Pure stdlib; the lane
guard keeps the conventional core monitoring-only (no @scout, no per-name @council). No eval().
"""
from __future__ import annotations

from typing import Any, Optional

import asymmetry_rating
import conventional_sentinel
import narrative_integrity
import valuation_ledger

__all__ = ["DEFAULT_DUAL_SIDED_CONFIG", "DUAL_SIDED_GLOSSARY", "dual_sided_tooltip",
           "solve_compounder", "solve_deep_value", "reconcile", "value",
           "lane_of", "is_conventional", "guard_conventional", "CONVENTIONAL_BLOCKED"]

DEFAULT_DUAL_SIDED_CONFIG: dict[str, Any] = {
    "wacc_default": 0.09,            # discount rate when the name doesn't carry one
    "terminal_growth": 0.025,        # stage-2 perpetuity growth (≈ nominal GDP)
    "cap_years_default": 10,         # competitive-advantage period (stage-1 horizon)
    "trough_fcf_multiple": 12.0,     # the de-rated multiple a compounder torpedoes to → the floor
    "peer_fcf_multiple": 20.0,       # the market sanity leg when the name carries no peer multiple
    "regime_sensitivity": 0.5,       # income-leg tilt = clamp(1 + s·regime_alpha, lo, hi)
    "regime_mult_floor": 0.7, "regime_mult_ceiling": 1.3,   # tighter than the spear's 0.5–1.5 (ballast)
    "growth_solve_bounds": [-0.10, 0.40],   # bisection bounds for the implied-growth solve
    # confidence-tilted blend weights per lens (mirrors archetypes.ArchetypeDNA.base_weights)
    "compounder_weights": {"cost": 0.10, "market": 0.40, "income": 0.50},   # income(DCF)-led
    "deep_value_weights": {"cost": 0.25, "market": 0.55, "income": 0.20},   # market(SOTP)-led
    "deep_value_conservative_multiple": 10.0,   # whole-co FCF cap multiple (the income cross-check)
    "deep_value_stressed_multiple": 9.0,        # stressed-FCF cap → the floor when no NAV is given
    # the base-rate prior each swing variable rests on (seeded in Phase 6; until then → asserted)
    "compounder_base_rate": "compounder_growth_persistence",
    "deep_value_base_rate": "deep_value_discount_closes",
    # reconciliation (Phase 3 — the divergence spread)
    "converged_spread_pct": 12.0,   # |spread| ≤ this ⇒ the two lenses agree (converged)
    "phi_strong": 0.95,             # deep-value φ ≥ this (price at/below the asset floor) ⇒ floor protection leads
}

DUAL_SIDED_GLOSSARY: dict[str, dict[str, str]] = {
    "compounder": {
        "what": "Reverse-DCF / expectations lens — the FCF growth × competitive-advantage-period the price embeds, vs. what's achievable.",
        "scale": "Implied growth ≤ base-rate-plausible = a fair-to-cheap franchise; implied growth above the base-rate ceiling = the market is paying for a runway few sustain.",
        "influence": "Prices the durable-compounder pole; MoS is the moat's durability, not a discount. Feeds the divergence spread (Phase 3).",
        "edge": "The failure mode is the TORPEDO — multiple compression on a growth miss — so the floor is the de-rated-multiple value, not an asset floor.",
    },
    "deep_value": {
        "what": "Sum-of-the-parts + asset/FCF floor lens — what the segments are worth and the floor beneath them.",
        "scale": "Price well below SOTP with a real floor = margin of safety in the entry discount; price at/above SOTP = the discount is spent.",
        "influence": "Prices the deep-value pole; φ (floor coverage) is real here. Feeds the divergence spread (Phase 3).",
        "edge": "The failure mode is the VALUE TRAP — the discount persists because a segment is structurally melting; the swing variable names that segment.",
    },
    "swing_variable": {
        "what": "The single load-bearing variable the thesis turns on (implied growth for a compounder; the load-bearing segment for a deep-value name), with its base rate.",
        "scale": "The base-rate probability is the outside-view anchor on whether the swing resolves favorably.",
        "influence": "The one number to underwrite; it is what CALIBRATION grades at close.",
        "edge": "ASSERTED PRIOR (n=0 realized) — a sourced engineering estimate, NOT a frequency the book has lived — until enough conventional theses close (Phase 6).",
    },
    "divergence_spread": {
        "what": "The gap between the compounder lens and the deep-value lens — which KIND of conventional bet this is.",
        "scale": "Wide + compounder-led = premium franchise (paying for durability); inverted + deep-value-led = mispricing (the parts are worth more than a melting-compounder price); tight = converged (both lenses agree).",
        "influence": "Picks the HEADLINE lens + directive flavour; never a sizing call.",
        "edge": "DISTINCT from method spread (cost/market/income agreement WITHIN one lens) — this is across the two LENSES.",
    },
}


def dual_sided_tooltip(key: str) -> str:
    e = DUAL_SIDED_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_DUAL_SIDED_CONFIG)
    block = (config or {}).get("dual_sided", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _regime_mult(regime_alpha: Any, cfg: dict) -> float:
    """Scalar income-leg tilt, clamped — the conventional analog of ``archetypes.regime_multiplier``
    (one leg, no double-count), banded tighter because the core is ballast, not the convex spear."""
    a = _num(regime_alpha) or 0.0
    s = float(cfg["regime_sensitivity"])
    return _clamp(1.0 + s * a, float(cfg["regime_mult_floor"]), float(cfg["regime_mult_ceiling"]))


def _per_share(ev: Optional[float], net_debt: Any, shares: Any) -> Optional[float]:
    """Equity value per share from enterprise value: (EV − net_debt) / shares. ``net_debt`` is signed
    (negative = net cash). None on bad inputs."""
    ev_ = _num(ev)
    nd = _num(net_debt) or 0.0
    sh = _num(shares)
    if ev_ is None or sh is None or sh <= 0:
        return None
    return (ev_ - nd) / sh


def _forward_dcf(fcf: Any, g: float, wacc: float, cap: int, g_term: float) -> Optional[float]:
    """Enterprise value from a 2-stage DCF: FCF grows at ``g`` for ``cap`` years, then a Gordon
    terminal at ``g_term``. None when degenerate (wacc ≤ g_term). Pure."""
    f = _num(fcf)
    if f is None or wacc <= g_term:
        return None
    pv, cf = 0.0, f
    for t in range(1, int(cap) + 1):
        cf = cf * (1.0 + g)
        pv += cf / (1.0 + wacc) ** t
    tv = cf * (1.0 + g_term) / (wacc - g_term)
    pv += tv / (1.0 + wacc) ** int(cap)
    return pv


def _implied_growth(price: float, fcf: float, wacc: float, cap: int, g_term: float,
                    net_debt: Any, shares: Any, *, bounds: list) -> dict:
    """Reverse-DCF: the stage-1 growth the PRICE embeds — bisect ``g`` so the 2-stage DCF per share
    equals price (the per-share intrinsic is monotonic increasing in g). Returns the implied g and a
    flag when the price sits beyond the model's [lo,hi] window (cheaper than the floor of the band, or
    pricing growth above its ceiling). Pure."""
    lo, hi = float(bounds[0]), float(bounds[1])

    def ps(g):
        return _per_share(_forward_dcf(fcf, g, wacc, cap, g_term), net_debt, shares)

    f_lo, f_hi = ps(lo), ps(hi)
    if f_lo is None or f_hi is None:
        return {"implied_growth": None, "bounded": "n/a"}
    if price <= f_lo:
        return {"implied_growth": lo, "bounded": "below_floor"}     # cheaper than even the low-growth case
    if price >= f_hi:
        return {"implied_growth": hi, "bounded": "above_ceiling"}   # priced beyond the model's growth ceiling
    a, b = lo, hi
    for _ in range(60):                                             # bisection to convergence
        m = (a + b) / 2.0
        v = ps(m)
        if v is None:
            break
        if v < price:
            a = m
        else:
            b = m
    return {"implied_growth": round((a + b) / 2.0, 4), "bounded": "in_band"}


def _triangulate(legs: dict, base_weights: dict, confidences: dict) -> tuple:
    """Confidence-tilted blend wᵢ = (Wᵢ·cᵢ)/Σ(Wⱼ·cⱼ) over the legs that carry a value — mirrors
    ``archetypes.AssetArchetype.triangulate`` exactly (a missing leg renormalizes out). Returns
    (blended_value, weights). Pure."""
    vals = {k: _num(v) for k, v in (legs or {}).items()}
    vals = {k: v for k, v in vals.items() if v is not None}
    raw = {k: max(0.0, _num(base_weights.get(k)) or 0.0) * max(0.0, _num(confidences.get(k)) or 0.0)
           for k in vals}
    total = sum(raw.values())
    if total <= 0:
        return (None, {k: 0.0 for k in vals})
    weights = {k: raw[k] / total for k in vals}
    return (sum(weights[k] * vals[k] for k in vals), weights)


def _swing(name: str, value_str: str, base_rate_name: str, read: str) -> dict:
    """The single load-bearing variable + its base rate, looked up from ``base_rates`` when present
    (seeded Phase 6). ``asserted`` stays True until the prior has earned realized data — the n=0
    honesty the tooltips surface (§8.2 of the spec)."""
    br, prob, asserted = None, None, True
    try:
        import base_rates
        est = base_rates.estimate(base_rate_name)
        if est:
            mean = est.get("mean", est.get("median"))
            br = {"mean": mean, "ci90": est.get("ci90"), "confidence": est.get("confidence"),
                  "source": est.get("source")}
            prob = est.get("mean")                                  # Beta priors carry a probability mean
            asserted = (est.get("confidence") != "high")           # earned posteriors flip this off
    except Exception:
        pass
    return {"name": name, "value": value_str, "base_rate_name": base_rate_name,
            "base_rate": br, "probability": prob, "asserted": asserted, "read": read}


def _grade_narrative(payload: dict, lens: str, config: Optional[dict]) -> Optional[dict]:
    """Grade the name's turnaround narrative (NIS, Phase 5) when the payload carries ``narrative``
    claims; None otherwise. Pure passthrough to ``narrative_integrity.grade``."""
    claims = (payload or {}).get("narrative")
    if not claims:
        return None
    return narrative_integrity.grade(payload.get("ticker") or "", claims, archetype=lens, lens=lens,
                                     listing=payload.get("ticker") or "", config=config)


def _assemble(lens: str, payload: dict, *, floor, base, bull, bear, legs, weights, confidences,
              swing: dict, data_completeness: dict, data_quality: str, config: Optional[dict],
              nis: Optional[dict] = None) -> dict:
    """Run the ladder + legs through the ENGINE's ``compute_asymmetry_rating`` (the reuse seam) and
    fold its output into the shared dual-sided schema. The engine owns the rating math; this only
    marshals the lens-specific legs/ladder in and the spread-ready schema out."""
    asset = {
        "ticker": payload.get("ticker"), "archetype": lens,
        "price": _num(payload.get("price")), "floor": floor, "base": base, "bull": bull, "bear": bear,
        "mri": _num(payload.get("mri")), "regime_alpha": _num(payload.get("regime_alpha")),
        "forensic_score": _num(payload.get("forensic_score")) if payload.get("forensic_score") is not None else 3.5,
        "resource_quality": _num(payload.get("quality")),          # business-quality proxy 0..1 (NIS refines, Phase 5)
        "management_score": _num(payload.get("management_score")),
        "conviction": _num(payload.get("conviction")),
        "data_quality": data_quality,
        "legs": legs, "leg_weights": weights, "leg_confidence": confidences,
        "sector_tags": list(payload.get("sector_tags") or []),
    }
    if nis and nis.get("integrity_score") is not None:        # NIS feeds the Q MANAGEMENT term
        mp = narrative_integrity.nis_to_q(nis["integrity_score"]).get("management_proxy")
        if mp is not None:
            cur = asset.get("management_score")
            asset["management_score"] = round(mp if cur is None else 0.4 * cur + 0.6 * mp, 3)
    ar = asymmetry_rating.compute_asymmetry_rating(asset, config)
    V = (ar.get("pillars") or {}).get("V") or {}
    P = ar.get("pillars") or {}
    zone = conventional_sentinel.zone_of(asset.get("price"), ar.get("ladder"))
    out = {
        "lens": lens, "ticker": ar.get("ticker"), "archetype": lens, "available": True,
        "intrinsic": (ar.get("ladder") or {}).get("base"),
        "ladder": ar.get("ladder"), "zone": zone.get("zone"),
        "asymmetry": {"rho": V.get("rho"), "phi": V.get("floor_coverage"),
                      "upside_pct": V.get("upside_pct"),
                      "downside_to_floor_pct": V.get("downside_to_floor_pct"), "mode": V.get("mode")},
        "pillars": {k: (P.get(k) or {}).get("score") for k in ("T", "Q", "V")},
        "rating": ar.get("rating"), "band": ar.get("band"), "directive": ar.get("directive"),
        "confidence_ribbon": ar.get("confidence_ribbon"),
        "legs": {"values": legs, "weights": weights, "confidence": confidences},
        "method_spread": valuation_ledger.method_spread(legs, weights),
        "swing_variable": swing,
        "data_completeness": data_completeness,
        "glossary": {lens: dual_sided_tooltip(lens), "swing_variable": dual_sided_tooltip("swing_variable")},
    }
    if nis:                                                    # the graded turnaround narrative + the live risk locus
        out["narrative_integrity"] = {k: nis.get(k) for k in ("integrity_score", "risk_locus", "read")}
        out["narrative_flags"] = nis.get("flags") or []
    return out


def _unavailable(lens: str, payload: dict, reason: str) -> dict:
    return {"lens": lens, "ticker": payload.get("ticker"), "archetype": lens,
            "available": False, "reason": reason}


def solve_compounder(payload: dict, *, config: Optional[dict] = None) -> dict:
    """The reverse-DCF / expectations lens. Needs price, shares_out, fcf (FCF-to-firm), and a
    base-rate-anchored ``growth`` dict ``{p10,p50,p90}``; wacc / cap_years / multiples default from
    config. The ladder base is the confidence-tilted blend of the asset floor, the peer-multiple leg,
    and the DCF income leg (regime-tilted); bull/bear scale it by the p90/p10 growth DCF; the floor is
    the TORPEDO (de-rated-multiple) value. Returns the shared schema; ``available: False`` when the
    inputs can't support a DCF."""
    cfg = _cfg(config)
    price, shares = _num(payload.get("price")), _num(payload.get("shares_out"))
    fcf, net_debt = _num(payload.get("fcf")), payload.get("net_debt")
    if price is None or shares is None or shares <= 0 or fcf is None or fcf <= 0:
        return _unavailable("compounder", payload, "needs price, shares_out and positive FCF-to-firm")
    wacc = _num(payload.get("wacc")) or float(cfg["wacc_default"])
    cap = int(_num(payload.get("cap_years")) or cfg["cap_years_default"])
    g_term = _num(payload.get("terminal_growth"))
    g_term = g_term if g_term is not None else float(cfg["terminal_growth"])
    growth = payload.get("growth") or {}
    g50 = _num(growth.get("p50"))
    g10 = _num(growth.get("p10")) if growth.get("p10") is not None else (g50 - 0.03 if g50 is not None else None)
    g90 = _num(growth.get("p90")) if growth.get("p90") is not None else (g50 + 0.04 if g50 is not None else None)
    if g50 is None:
        return _unavailable("compounder", payload, "needs a base-rate growth dict {p10,p50,p90}")

    dcf50 = _per_share(_forward_dcf(fcf, g50, wacc, cap, g_term), net_debt, shares)
    dcf10 = _per_share(_forward_dcf(fcf, g10, wacc, cap, g_term), net_debt, shares)
    dcf90 = _per_share(_forward_dcf(fcf, g90, wacc, cap, g_term), net_debt, shares)
    peer_mult = _num(payload.get("peer_fcf_multiple")) or float(cfg["peer_fcf_multiple"])
    trough_mult = _num(payload.get("trough_fcf_multiple")) or float(cfg["trough_fcf_multiple"])
    market = _per_share(fcf * peer_mult, net_debt, shares)
    floor = _per_share(fcf * trough_mult, net_debt, shares)        # the torpedo: multiple compresses to trough
    nav = _num(payload.get("nav_per_share"))
    cost = nav if nav is not None else floor
    income = (dcf50 * _regime_mult(payload.get("regime_alpha"), cfg)) if dcf50 is not None else None

    legs = {"cost": cost, "market": market, "income": income}
    weights_base = dict(cfg["compounder_weights"])
    conf = {"cost": 0.5, "market": 0.7, "income": 0.85}
    conf.update(payload.get("leg_confidence") or {})
    base, w = _triangulate(legs, weights_base, conf)
    if base is None:
        return _unavailable("compounder", payload, "no valuation leg could be computed")
    # bull/bear scale the blended base by the growth-DCF ratio (keeps the spread tied to growth risk)
    bull = base * (dcf90 / dcf50) if (dcf90 and dcf50 and dcf50 > 0) else base * 1.4
    bear = base * (dcf10 / dcf50) if (dcf10 and dcf50 and dcf50 > 0) else base * 0.7

    impl = _implied_growth(price, fcf, wacc, cap, g_term, net_debt, shares, bounds=cfg["growth_solve_bounds"])
    ig = impl.get("implied_growth")
    over = (ig is not None and g90 is not None and ig > g90)
    val_str = (f"{ig:.0%}/yr × {cap}y implied vs ~{g50:.0%} base-rate-plausible"
               if ig is not None else f"implied growth n/a; base-rate ~{g50:.0%}")
    read = ("market prices growth ABOVE the base-rate ceiling — torpedo-exposed on a miss" if over
            else "priced within the base-rate growth band — the moat's durability is the watch")
    swing = _swing("priced-in FCF growth × CAP", val_str, cfg["compounder_base_rate"], read)
    swing["implied_growth"] = ig
    swing["implied_vs_ceiling"] = "above" if over else "within"

    out = _assemble("compounder", payload, floor=floor, base=base, bull=bull, bear=bear,
                    legs=legs, weights=w, confidences={k: conf[k] for k in legs},
                    swing=swing, data_completeness={"fallback_used": False},
                    data_quality=payload.get("data_quality") or "full", config=config,
                    nis=_grade_narrative(payload, "compounder", config))
    out["implied_growth"] = impl
    return out


def solve_deep_value(payload: dict, *, config: Optional[dict] = None) -> dict:
    """The sum-of-the-parts + floor lens. Best with ``segments`` (``[{name, value, multiple,
    bull_multiple?}]``) + a floor input (``nav_per_share`` or ``stressed_fcf``); FALLS CLOSED to a
    whole-company FCF cap when segments are absent — flagged (``fallback_used``), band widened, never a
    fake default. The ladder base is the blend of the floor (cost), the SOTP (market, lead) and the
    whole-co FCF cap (income); the floor is the conventional REP. Returns the shared schema."""
    cfg = _cfg(config)
    price, shares = _num(payload.get("price")), _num(payload.get("shares_out"))
    net_debt = payload.get("net_debt")
    if price is None or shares is None or shares <= 0:
        return _unavailable("deep_value", payload, "needs price and shares_out")
    segments = [s for s in (payload.get("segments") or []) if _num(s.get("value")) is not None]
    fcf = _num(payload.get("fcf"))
    fallback = False
    data_quality = payload.get("data_quality") or "full"

    if segments:
        sotp_ev = sum((_num(s.get("value")) or 0.0) * (_num(s.get("multiple")) or 0.0) for s in segments)
        bull_ev = sum((_num(s.get("value")) or 0.0) *
                      ((_num(s.get("bull_multiple")) or _num(s.get("multiple")) or 0.0)) for s in segments)
        sotp = _per_share(sotp_ev, net_debt, shares)
        bull = _per_share(bull_ev, net_debt, shares)
    else:
        # fail closed: no clean segment splits → whole-company FCF cap as a coarse SOTP proxy, FLAGGED
        if fcf is None or fcf <= 0:
            return _unavailable("deep_value", payload, "needs segments or whole-company FCF for the fallback")
        fallback = True
        data_quality = "degraded" if data_quality == "full" else "sparse"
        sotp = _per_share(fcf * float(cfg["deep_value_conservative_multiple"]), net_debt, shares)
        bull = (sotp * 1.4) if sotp is not None else None

    # the conventional REP floor: NAV, else a stressed-FCF capitalization
    nav = _num(payload.get("nav_per_share"))
    stressed_fcf = _num(payload.get("stressed_fcf"))
    stressed_ps = _per_share((stressed_fcf or 0.0) * float(cfg["deep_value_stressed_multiple"]),
                             net_debt, shares) if stressed_fcf is not None else None
    floor_candidates = [x for x in (nav, stressed_ps) if x is not None]
    floor = max(floor_candidates) if floor_candidates else (sotp * 0.6 if sotp is not None else None)
    income = (_per_share((fcf or 0.0) * float(cfg["deep_value_conservative_multiple"]), net_debt, shares)
              * _regime_mult(payload.get("regime_alpha"), cfg)) if fcf is not None else None

    legs = {"cost": floor, "market": sotp, "income": income}
    weights_base = dict(cfg["deep_value_weights"])
    conf = {"cost": 0.6, "market": (0.5 if fallback else 0.8), "income": 0.6}
    conf.update(payload.get("leg_confidence") or {})
    base, w = _triangulate(legs, weights_base, conf)
    if base is None:
        return _unavailable("deep_value", payload, "no valuation leg could be computed")
    bear = floor if floor is not None else base * 0.7

    # the load-bearing segment: the named swing, else the largest by contribution
    swing_name = payload.get("swing_segment")
    if not swing_name and segments:
        swing_name = max(segments, key=lambda s: (_num(s.get("value")) or 0.0) * (_num(s.get("multiple")) or 0.0)).get("name")
    disc = ((base / price - 1.0) * 100.0) if (base and price) else None
    val_str = (f"{swing_name}: the discount closes iff this segment holds/re-rates"
               if swing_name else "the SOTP discount closes vs. persists as a trap")
    read = ((f"{disc:+.0f}% to SOTP — " if disc is not None else "")
            + ("FALLBACK: no clean segment splits; band widened, conviction capped — supply via dual_sided.sotp_overrides"
               if fallback else "margin of safety is the entry discount; the value-trap risk sits in the swing segment"))
    swing = _swing("load-bearing segment", val_str, cfg["deep_value_base_rate"], read)
    swing["segment"] = swing_name

    return _assemble("deep_value", payload, floor=floor, base=base, bull=bull, bear=bear,
                     legs=legs, weights=w, confidences={k: conf[k] for k in legs},
                     swing=swing,
                     data_completeness={"fallback_used": fallback,
                                        "segments_supplied": [s.get("name") for s in segments] or None},
                     data_quality=data_quality, config=config,
                     nis=_grade_narrative(payload, "deep_value", config))


def _headline(schema: Optional[dict]) -> dict:
    s = schema or {}
    return {"lens": s.get("lens"), "rating": s.get("rating"), "band": s.get("band"),
            "directive": s.get("directive")}


def _ribbon_width(schema: Optional[dict]) -> float:
    r = (schema or {}).get("confidence_ribbon") or {}
    w = _num(r.get("rel_width"))
    if w is None:
        w = _num(r.get("plus_minus"))
    return w if w is not None else 1e9


def _swing_name(schema: Optional[dict]) -> str:
    sv = (schema or {}).get("swing_variable") or {}
    return sv.get("segment") or sv.get("name") or "the swing variable"


def reconcile(compounder: Optional[dict], deep_value: Optional[dict], price: Any,
              *, config: Optional[dict] = None) -> dict:
    """The DIVERGENCE SPREAD — the gap between the two lenses, which tells the operator which KIND of
    conventional bet this is. Three shapes (§5.2): ``premium-franchise`` (wide, compounder-led — paying
    for durability, e.g. TMX), ``mispricing-flag`` (inverted, deep-value-led — the parts are worth more
    than a melting-compounder price, e.g. EEFT), ``converged`` (tight — both lenses agree). Also picks
    the ``lead_lens`` that drives the headline directive: deep-value when φ is strong (price at/below
    the asset floor — floor protection dominates), else shape-driven; converged → the tighter ribbon.
    DISTINCT from method_spread (cross-method, within one lens). Pure."""
    cfg = _cfg(config)
    p = _num(price)
    ca, da = bool((compounder or {}).get("available")), bool((deep_value or {}).get("available"))
    ci = _num((compounder or {}).get("intrinsic"))
    di = _num((deep_value or {}).get("intrinsic"))
    if not (ca and da):
        if not (ca or da):
            return {"available": False, "shape": None, "read": "neither lens could be valued"}
        lead = "compounder" if ca else "deep_value"
        only = compounder if ca else deep_value
        return {"available": True, "shape": "single-lens", "leader": lead, "lead_lens": lead,
                "compounder_intrinsic": ci, "deep_value_intrinsic": di, "price": p, "spread_pct": None,
                "zone": only.get("zone"), "headline": _headline(only),
                "read": f"only the {lead} lens could be valued ({_num(only.get('intrinsic')):.2f} vs price {p})",
                "glossary": {"divergence_spread": dual_sided_tooltip("divergence_spread")}}

    med = (ci + di) / 2.0 if (ci is not None and di is not None) else None
    spread_pct = ((ci - di) / med * 100.0) if (med and med != 0) else None
    leader = "compounder" if (ci is not None and di is not None and ci >= di) else "deep_value"
    dv_phi = _num((deep_value.get("asymmetry") or {}).get("phi"))

    if spread_pct is not None and abs(spread_pct) <= float(cfg["converged_spread_pct"]):
        shape = "converged"
    elif leader == "compounder":
        shape = "premium-franchise"
    else:
        shape = "mispricing-flag"

    if dv_phi is not None and dv_phi >= float(cfg["phi_strong"]):
        lead = "deep_value"                                        # price at/below the asset floor — floor protection leads
    elif shape == "converged":
        lead = "compounder" if _ribbon_width(compounder) <= _ribbon_width(deep_value) else "deep_value"
    elif shape == "mispricing-flag":
        lead = "deep_value"
    else:
        lead = "compounder"

    reads = {
        "premium-franchise": (f"premium franchise — compounder {ci:.2f} ≫ deep-value {di:.2f}; MoS is the "
                              f"moat (durability), the watch is the torpedo"),
        "mispricing-flag": (f"mispricing flag — deep-value {di:.2f} > compounder {ci:.2f}; priced as a melting "
                            f"compounder, the parts are worth more (swing: {_swing_name(deep_value)})"),
        "converged": f"converged — both lenses agree (~{med:.2f}); the central estimate stands on a firm base",
    }
    return {"available": True, "shape": shape, "leader": leader, "lead_lens": lead,
            "compounder_intrinsic": ci, "deep_value_intrinsic": di, "price": p,
            "spread_pct": round(spread_pct, 1) if spread_pct is not None else None,
            "zone": (compounder if lead == "compounder" else deep_value).get("zone"),
            "headline": _headline(compounder if lead == "compounder" else deep_value),
            "read": reads[shape],
            "glossary": {"divergence_spread": dual_sided_tooltip("divergence_spread")}}


#: Inputs whose provenance is load-bearing for the valuation (PROVENANCE_REMEDIATION_PLAN.md P1.1).
PROVENANCE_LOAD_BEARING: tuple = ("price", "shares_out", "net_debt", "fcf", "stressed_fcf",
                                  "wacc", "growth", "nav_per_share")

#: Allowed provenance bases. "street" is a FIRST-CLASS visible category — an analyst target or
#: consensus-derived number may be carried, but it can never silently masquerade as a model
#: (the CEG bear-case lesson, 2026-08-12: a sell-side price target sat in `bear_case_usd` for a
#: week and was quoted as a modeled downside).
PROVENANCE_BASES: frozenset = frozenset({"filed", "derived", "modeled", "street"})


def provenance_flags(payload: dict) -> list:
    """Audit the underwriting payload's provenance sidecar (``payload['provenance']`` — a dict of
    ``{field: {source, as_of, confidence, basis}}``) against the load-bearing input list. Returns a
    flag per problem: ``unstamped:<field>`` (input present, no provenance record),
    ``street:<field>`` (input rests on street/consensus numbers — visible, loud, allowed),
    ``bad_basis:<field>`` (basis outside the vocabulary). Pure; empty list = clean."""
    prov = payload.get("provenance") or {}
    flags = []
    for f in PROVENANCE_LOAD_BEARING:
        if payload.get(f) is None:
            continue                                   # absent inputs are a completeness issue, not provenance
        rec = prov.get(f)
        if not isinstance(rec, dict) or not rec.get("source"):
            flags.append(f"unstamped:{f}")
            continue
        basis = str(rec.get("basis", "")).strip().lower()
        if basis == "street":
            flags.append(f"street:{f}")
        elif basis and basis not in PROVENANCE_BASES:
            flags.append(f"bad_basis:{f}")
    return flags


def value(payload: dict, *, config: Optional[dict] = None) -> dict:
    """Run BOTH lenses on a conventional name, reconcile them to the divergence spread, and return the
    full dual-sided read on the shared schema. ``reconciliation`` carries the shape (premium-franchise /
    mispricing-flag / converged), the lead lens, and the spread. Pure.

    Provenance guard (P1.1): the result always carries a ``provenance`` block — ``flags`` naming every
    load-bearing input that is unstamped or street-derived, and ``degraded`` when any flag exists. The
    valuation still runs (the desk's best state must stay usable), but a street/unstamped basis can
    never again be invisible on the face of the output."""
    comp = solve_compounder(payload, config=config)
    dv = solve_deep_value(payload, config=config)
    rec = reconcile(comp, dv, payload.get("price"), config=config)
    flags = provenance_flags(payload)
    return {"ticker": payload.get("ticker"), "price": _num(payload.get("price")),
            "compounder": comp, "deep_value": dv, "reconciliation": rec,
            "lens_available": {"compounder": comp.get("available", False),
                               "deep_value": dv.get("available", False)},
            "provenance": {"flags": flags, "degraded": bool(flags),
                           "read": ("clean — all load-bearing inputs stamped" if not flags else
                                    f"DEGRADED — {len(flags)} provenance flag(s): " + ", ".join(flags))}}


# ---------------------------------------------------------------------------------------------------
# Lane guard (§4.4) — the third invariant enforced: the conventional core is MONITORING-ONLY. The
# engine prices it (dual-sided), watches it (correlation + SENTINEL), but does NOT scout or convene a
# per-name council for it — no alpha where the engine has none. Pure; the agent/cockpit layer calls
# guard_conventional() before firing those flows.
# ---------------------------------------------------------------------------------------------------

#: flows the conventional lane is excluded from (discovery/deliberation — the engine's edge-seeking).
CONVENTIONAL_BLOCKED: frozenset = frozenset({"scout", "council", "discovery", "pipeline"})


def lane_of(ticker: str, portfolio_metadata: Optional[dict]) -> str:
    """The lane for a ticker from ``portfolio_metadata[ticker].lane`` (case/key tolerant). Defaults to
    ``"resource"`` — the satellite keeps the full FORGE stack unless explicitly tagged conventional."""
    md = portfolio_metadata or {}
    entry = md.get(ticker) or md.get(str(ticker).upper()) or {}
    return str((entry or {}).get("lane") or "resource").strip().lower()


def is_conventional(ticker: str, portfolio_metadata: Optional[dict]) -> bool:
    return "conv" in lane_of(ticker, portfolio_metadata)


def guard_conventional(ticker: str, action: str, portfolio_metadata: Optional[dict] = None) -> dict:
    """Gate a discovery/deliberation flow for a name. A conventional-lane name is REFUSED the
    edge-seeking flows (scout/council/discovery/pipeline) with a reason — monitoring only. Resource
    names (the default) pass everything. Returns ``{allowed, lane, action, reason}``. Pure."""
    lane = lane_of(ticker, portfolio_metadata)
    act = str(action or "").strip().lower()
    if "conv" in lane and act in CONVENTIONAL_BLOCKED:
        return {"allowed": False, "lane": "conventional", "action": act,
                "reason": (f"{ticker} is in the conventional lane — monitoring only (dual-sided valuation + "
                           f"correlation + SENTINEL). No {act}: the engine doesn't generate alpha where it "
                           f"has no edge (the third invariant). Use the resource satellite for discovery.")}
    return {"allowed": True, "lane": lane, "action": act}
