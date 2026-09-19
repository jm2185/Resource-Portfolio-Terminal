"""
CommodityEx Quant Monitor v5.3 — Phase 5: The Polymorphic Archetype Factory
===========================================================================
A multi-sector thematic investment OS. Assets are routed strictly by CASH-FLOW
LIFECYCLE (not GICS sector) into one of five archetypes, each valued through the
same three-leg triangulation (Cost / Market / Income, all CAD post-FX) behind a
clean abstract base class and a fail-fast, metadata-driven registry.

CrowdEx heritage carried forward:
  * metadata-driven archetype DNA (the old STOCK_CLASSES registry idea);
  * tag- and score-threshold routing in the PolymorphicRouter;
  * advanced pre-revenue scoring primitives (runway, cash-burn acceleration,
    dilution velocity);
  * an insider-sentiment / conviction overlay (a SIZING signal, kept out of the
    intrinsic to avoid double-counting); and
  * risk-factor tagging that seeds future cross-archetype correlation sizing.

Design discipline (from Phase 4): NO double-counting. Each economic source enters
exactly one leg, and the discretionary macro overlay (the Regime Impact Vector) is
applied ONCE, to a single designated leg per archetype.

Pure-Python and dependency-free (no numpy / yfinance / engine import) so it is
importable and testable anywhere; the shared primitives faithfully mirror the
audited `ValuationEngine` math, cross-referenced at each call site. Backend only.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, ClassVar, Optional, Tuple

# --------------------------------------------------------------------------- #
#  Regime Impact Vector — order maps 1:1 to the five archetypes (I … V)
# --------------------------------------------------------------------------- #
RegimeImpactVector = Tuple[float, float, float, float, float]
# index 0  alpha_option    -> I.   Option Convexity     (pre-revenue / binary)
# index 1  alpha_margin     -> II.  Capital Margin        (capital-intensive op.)
# index 2  alpha_cyclical   -> III. Commodity Cyclical    (spot-margin business)
# index 3  alpha_yield      -> IV.  Asset-Light Yield     (recurring cash flow)
# index 4  alpha_delta      -> V.   Pure Macro Delta      (passive commodity)
REGIME_ORDER: Tuple[str, ...] = (
    "alpha_option", "alpha_margin", "alpha_cyclical", "alpha_yield", "alpha_delta")
NEUTRAL_REGIME: RegimeImpactVector = (0.0, 0.0, 0.0, 0.0, 0.0)

BASE_CURRENCY: str = "CAD"

__all__ = [
    "RegimeImpactVector", "REGIME_ORDER", "NEUTRAL_REGIME",
    "TickerNotRegisteredError", "SparseDataError", "ArchetypeConfigError",
    "ArchetypeDNA", "ARCHETYPE_DNA", "AssetArchetype",
    "SubArchetypeDNA", "SUBARCHETYPE_DNA", "subarchetype_dna", "subarchetypes_for",
    "compose_leg_weights",
    "OptionConvexityArchetype", "CapitalMarginArchetype", "CommodityCyclicalArchetype",
    "AssetLightYieldArchetype", "PureMacroDeltaArchetype",
    "ARCHETYPE_REGISTRY", "ARCHETYPE_BY_TYPE", "PolymorphicRouter",
    "build_default_router", "load_config",
    "technical_quality", "option_premium", "capital_discount_factor", "spot_linked_fair_value",
]


# --------------------------------------------------------------------------- #
#  Exceptions
# --------------------------------------------------------------------------- #
class TickerNotRegisteredError(KeyError):
    """Raised by PolymorphicRouter when a ticker resolves to no archetype via any
    route (ticker map, tag rule, or score rule). Fail-fast — never a silent 0."""


class SparseDataError(ValueError):
    """Raised inside a leg when its required inputs are absent. Caught by
    valuation_summary, which zeroes that leg's confidence and lets the
    confidence-tilted blend renormalize over the surviving legs."""


class ArchetypeConfigError(ValueError):
    """Raised for a structurally invalid archetype / router configuration."""


# --------------------------------------------------------------------------- #
#  Numeric helpers (pure-Python replicas of the engine primitives)
# --------------------------------------------------------------------------- #
def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp ``x`` to ``[lo, hi]`` (bounds tolerated in any order)."""
    if lo > hi:
        lo, hi = hi, lo
    return max(lo, min(hi, x))


def _finite(x: Any) -> bool:
    """True iff ``x`` is a real, finite number."""
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _num(source: dict, *keys: str, default: float = 0.0) -> float:
    """Graceful nested numeric getter — returns ``default`` on any missing or
    non-finite path. The backbone of the module's graceful degradation."""
    cur: Any = source
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return float(cur) if _finite(cur) else default


def _present(source: dict, *keys: str) -> bool:
    """True iff the nested path exists and resolves to a finite number."""
    cur: Any = source
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return False
        cur = cur[k]
    return _finite(cur)


def softplus(x: float, beta: float) -> float:
    """Numerically-stable softplus ``(1/beta)*ln(1+exp(beta*x))`` — smooth max(0,x).
    Mirrors ``ValuationEngine._softplus`` without numpy."""
    z = beta * x
    return (max(z, 0.0) + math.log1p(math.exp(-abs(z)))) / beta


def capital_discount_factor(cfg: dict, y30: float) -> float:
    """Smooth cost-of-capital discount on the 30Y yield. Faithful replica of
    ``ValuationEngine.calculate_capital_discount_factor`` (y30 ~ 4.99 -> ~0.8808)."""
    p = cfg.get("capital_discount_params", {
        "onset_y30": 4.0, "slope": 0.12, "floor": 0.40, "onset_beta": 8.0, "floor_beta": 25.0})
    excess = softplus(y30 - p["onset_y30"], p["onset_beta"])
    raw = 1.0 - p["slope"] * excess
    return p["floor"] + softplus(raw - p["floor"], p["floor_beta"])


def technical_quality(cfg: dict, project: str) -> dict:
    """Transparent, bounded Technical-Quality multiplier (grade / blended Ag+Au
    metallurgy / real Fraser jurisdiction / infrastructure / depth). Faithful
    replica of ``ValuationEngine.calculate_technical_quality``."""
    tqc = cfg.get("technical_quality", {})
    if not tqc.get("enabled", True):
        return {"tq": 1.0, "factors": {}}
    fcfg = tqc.get("factors", {})
    proj = tqc.get("projects", {}).get(project, {})

    def band(name: str, s: float) -> float:
        fc = fcfg.get(name, {})
        lo, hi = fc.get("lo", 1.0), fc.get("hi", 1.0)
        return lo + (hi - lo) * clamp(s, 0.0, 1.0)

    g = fcfg.get("grade", {})
    bench = g.get("benchmark_gpt_ageq", 250) or 250
    f_grade = band("grade", proj.get("grade_gpt_ageq", bench) / (2.0 * bench))
    m = fcfg.get("metallurgy", {})
    rec_blend = (proj.get("ageq_share_ag", 0.7) * proj.get("rec_ag", 0.85)
                 + proj.get("ageq_share_au", 0.3) * proj.get("rec_au", 0.92))
    f_met = band("metallurgy", (rec_blend - m.get("rec_lo", 0.70))
                 / max(1e-9, m.get("rec_hi", 0.95) - m.get("rec_lo", 0.70)))
    j = fcfg.get("jurisdiction", {})
    f_jur = band("jurisdiction", (proj.get("fraser", 75.0) - j.get("fraser_lo", 50))
                 / max(1e-9, j.get("fraser_hi", 95) - j.get("fraser_lo", 50)))
    f_inf = band("infrastructure", proj.get("infrastructure", 0.5))
    f_dep = band("depth", proj.get("depth", 0.5))
    tq_raw = f_grade * f_met * f_jur * f_inf * f_dep
    tq = clamp(tq_raw, tqc.get("tq_min", 0.55), tqc.get("tq_max", 1.70))
    return {"tq": round(tq, 4), "factors": {
        "grade": round(f_grade, 3), "metallurgy": round(f_met, 3), "jurisdiction": round(f_jur, 3),
        "infrastructure": round(f_inf, 3), "depth": round(f_dep, 3),
        "rec_blend": round(rec_blend, 3), "raw": round(tq_raw, 3)}}


def option_premium(cfg: dict, spot_ag: float, aisc: float, silver_vol: float,
                   real_yield: float, stage: str = "explorer",
                   peer_aisc: Optional[float] = None) -> dict:
    """Dimensionally-coherent option/convexity premium ``pi_opt`` (>= 0), built only
    from convexity NOT already in the comps. Faithful replica of
    ``engines/valuation.py::ValuationEngine.calculate_option_premium`` — including the
    weight renormalization when the relative-moneyness term is inactive and the
    comps_overlap_keep haircut on vol/carry."""
    oc = cfg.get("option_premium", {})
    if not oc.get("enabled", True):
        return {"pi_opt": 0.0, "vol_term": 0.0, "carry_term": 0.0, "moneyness_excess": 0.0,
                "stage_cap": 0.0, "moneyness_active": False,
                "weights_used": {"moneyness": 0.0, "vol": 0.0, "carry": 0.0}}
    w = oc.get("weights", {"moneyness": 0.40, "vol": 0.35, "carry": 0.25})
    w_money, w_vol, w_carry = w.get("moneyness", 0.40), w.get("vol", 0.35), w.get("carry", 0.25)
    sv = silver_vol if (silver_vol and silver_vol > 0) else 0.30
    overlap_keep = oc.get("comps_overlap_keep", 1.0)
    vol_term = min(oc.get("vol_cap", 0.40),
                   max(0.0, sv - oc.get("vol_floor", 0.20)) * oc.get("vol_k", 1.0)) * overlap_keep
    carry_term = min(oc.get("carry_cap", 0.50),
                     max(0.0, oc.get("carry_breakeven", 1.0) - real_yield) * oc.get("carry_k", 0.25)) * overlap_keep
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
            "weights_used": {"moneyness": round(w_money, 4), "vol": round(w_vol, 4),
                             "carry": round(w_carry, 4)}}


def peer_ev_margin_scaled(peer0: float, spot0: float, spot1: float, aisc: float) -> float:
    """Convex propagation of peer EV/oz under a silver move: peers re-rate with the
    operating MARGIN (spot − AISC), not 1:1 with spot. Faithful replica of
    ``engines/valuation.py::ValuationEngine.peer_ev_margin_scaled`` — the single source
    of truth for the AGA-standalone scenario surface and the cockpit What-If (kept as
    a local replica to avoid an engine->archetype import cycle). Floored so the margin
    can't collapse to ~0 or go negative on a deep drawdown. With aisc=0 it degrades
    gracefully to a linear spot ratio, exactly like the engine's staticmethod."""

    try:
        a = float(aisc or 0.0)
    except (TypeError, ValueError):
        a = 0.0
    flo = max(1.0, 0.10 * a)
    m0 = max(flo, float(spot0) - a)
    m1 = max(flo, float(spot1) - a)
    return peer0 * (m1 / m0) if m0 > 0 else peer0


def pm_cycle_bull_kicker(macro: dict) -> tuple:
    """PM-cycle / technicals uplift for the BULL case's peer-multiple expansion.

    The bull is a forward upside case, so it is allowed to condition on the
    cycle: when the engine's own live gauges say precious metals are in a bull
    regime, the sector re-rating tail is fatter than the mechanical ±35%
    placeholder band (the config block itself calls that band a placeholder
    until a peer-EV history exists). The bear keeps the mechanical band, and
    the silver tails stay ±1σ (the convex margin scaling already makes them
    asymmetric). Bounded to [0, 0.50] — at most a 1.5x wider bull expansion.

    Gauges (all engine-native, all labeled in the output):
      - GSR < 75: the engine's own annotation reads this as silver
        outperforming / bullish momentum  -> +0.20
      - GSR < 65: deep silver leadership   -> +0.15
      - CFTC silver net longs > 20k: real participation, not just price -> +0.10
      - DXY momentum < 0: falling dollar is the classic PM technical tailwind
        -> +0.05 (small; momentum is noisy)
    Missing gauges degrade to 0 (no fabricated cycle)."""

    kick = 0.0
    why = {}
    gsr = macro.get("gsr")
    try:
        gsr = float(gsr) if gsr is not None else float("nan")
    except (TypeError, ValueError):
        gsr = float("nan")
    if gsr == gsr:  # finite
        if gsr < 75:
            kick += 0.20
            why["gsr_lt_75_silver_outperforming"] = round(gsr, 2)
        if gsr < 65:
            kick += 0.15
            why["gsr_lt_65_deep_leadership"] = round(gsr, 2)
    cftc = macro.get("cftc_silver_longs")
    try:
        cftc = float(cftc) if cftc is not None else float("nan")
    except (TypeError, ValueError):
        cftc = float("nan")
    if cftc == cftc and cftc > 20000:
        kick += 0.10
        why["cftc_longs_participation"] = int(cftc)
    dxy = macro.get("dxy_mom")
    try:
        dxy = float(dxy) if dxy is not None else float("nan")
    except (TypeError, ValueError):
        dxy = float("nan")
    if dxy == dxy and dxy < 0:
        kick += 0.05
        why["dxy_mom_negative_tailwind"] = round(dxy, 4)
    kick = max(0.0, min(0.50, kick))
    return kick, why


def spot_linked_fair_value(ref_price: float, base_mult: float, spot_now: float,
                           spot_ref: float, spot_beta: float, forensic_pen: float = 1.0) -> float:
    """Spot-linked fair value, DECOUPLED from the name's own share price. Faithful
    replica of ``ValuationEngine.calculate_ballast_fair_value``. ``spot_beta``
    encodes commodity leverage (~1.0 pure royalty, >1 operating)."""
    if ref_price <= 0 or spot_ref <= 0:
        return 0.0
    spot_factor = max(0.0, 1.0 + spot_beta * ((spot_now / spot_ref) - 1.0))
    return max(0.0, ref_price * base_mult * spot_factor * forensic_pen)


def _commodity_spot(data: dict, commodity) -> float:
    """Live spot for the name's underlying metal, RETURNED IN THE SAME FRAME as the configured
    ``spot_ref`` so the market-leg ratio (spot_now / spot_ref) stays unit-consistent.

    The ballast ``spot_ref`` anchors are silver-framed (~75), so ONLY silver can be live-linked
    without a unit mismatch. gold/uranium/diversified return ``spot_ref`` itself → a NEUTRAL spot
    factor (1.0): their commodity tailwind rides ``commodity_regime`` in the T-pillar, not the
    fair-value scaling. Mixing frames (gold ~4500 over a silver ~75 ``spot_ref``) would manufacture
    a ~60x phantom fair value — the cause of the spurious 5000% ballast upside. Once a name carries
    a properly metal-framed ``spot_ref`` in config, it can be live-linked here without distortion."""
    c = str(commodity or "silver").lower()
    if c == "silver":
        return _num(data, "macro", "spot_ag")
    return _num(data, "spot_ref", default=_num(data, "macro", "spot_ag"))


def load_config(config_path: str = "v5_config.json") -> dict:
    """Load a config dict from a JSON path (convenience for callers/tests)."""
    with open(config_path, "r") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
#  Metadata-driven archetype DNA (CrowdEx STOCK_CLASSES heritage)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ArchetypeDNA:
    """Declarative description of one archetype — the routing/blend "DNA".

    Metadata, not behaviour: the ABC reads its DNA for default leg weights,
    per-leg confidence priors, its RegimeImpactVector slot, the single leg the
    macro overlay tilts, the routing ``tags``, and the ``risk_factor_tags`` that
    seed cross-archetype correlation grouping."""
    code: str                                       # roman id "I".."V"
    name: str                                       # registry key
    regime_index: int                               # 0..4 slot in RegimeImpactVector
    regime_tilt_leg: str                            # "cost" | "market" | "income"
    base_weights: dict[str, float]
    base_confidence: dict[str, float]
    tags: frozenset[str]                            # tag-based routing keys
    risk_factor_tags: frozenset[str]                # correlation foundation
    score_band: Tuple[float, float] = (0.0, 4.0)    # score-threshold routing band


#: The five lifecycle archetypes, declared as metadata up front.
ARCHETYPE_DNA: dict[str, ArchetypeDNA] = {
    "option_convexity": ArchetypeDNA(
        code="I", name="option_convexity", regime_index=0, regime_tilt_leg="market",
        base_weights={"cost": 0.30, "market": 0.70, "income": 0.00},
        base_confidence={"cost": 0.90, "market": 0.85, "income": 0.20},
        tags=frozenset({"pre_revenue", "binary_outcome", "explorer", "discovery"}),
        risk_factor_tags=frozenset({"silver_beta", "discovery_event", "junior_liquidity"})),
    "capital_margin": ArchetypeDNA(
        code="II", name="capital_margin", regime_index=1, regime_tilt_leg="income",
        base_weights={"cost": 0.15, "market": 0.35, "income": 0.50},
        base_confidence={"cost": 0.80, "market": 0.75, "income": 0.80},
        tags=frozenset({"operating", "capital_intensive", "regulated", "defense", "infrastructure"}),
        risk_factor_tags=frozenset({"rates_duration", "regulated_margin", "industrial_demand"})),
    "commodity_cyclical": ArchetypeDNA(
        code="III", name="commodity_cyclical", regime_index=2, regime_tilt_leg="income",
        base_weights={"cost": 0.10, "market": 0.40, "income": 0.50},
        base_confidence={"cost": 0.70, "market": 0.80, "income": 0.75},
        tags=frozenset({"operating", "spot_margin", "producer", "developer"}),
        risk_factor_tags=frozenset({"silver_beta", "operating_leverage", "cost_curve"})),
    "asset_light_yield": ArchetypeDNA(
        code="IV", name="asset_light_yield", regime_index=3, regime_tilt_leg="income",
        base_weights={"cost": 0.05, "market": 0.25, "income": 0.70},
        base_confidence={"cost": 0.60, "market": 0.75, "income": 0.85},
        tags=frozenset({"recurring", "royalty", "streamer", "asset_light", "high_margin"}),
        risk_factor_tags=frozenset({"silver_beta", "rates_duration", "stream_credit"})),
    "pure_macro_delta": ArchetypeDNA(
        code="V", name="pure_macro_delta", regime_index=4, regime_tilt_leg="market",
        base_weights={"cost": 0.20, "market": 0.80, "income": 0.00},
        base_confidence={"cost": 0.80, "market": 0.95, "income": 0.30},
        tags=frozenset({"passive", "trust", "futures", "etp", "no_operations"}),
        risk_factor_tags=frozenset({"silver_beta", "spot_delta"})),
}


# --------------------------------------------------------------------------- #
#  Sub-archetype DNA — the 3rd taxonomy axis (finer sorting WITHIN a core archetype)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SubArchetypeDNA:
    """A finer label UNDER a core archetype — the third taxonomy axis (the first two being the
    valuation **archetype** and the **commodity**). It is a metadata OVERLAY, not a new valuation
    class: optional additive deltas to the parent's leg weights / confidence priors, plus extra
    risk-factor tags for correlation grouping.

    Empty deltas == IDENTITY: display + correlation only, valuation byte-for-byte unchanged. That is
    the deliberate safe default — each delta is a calibration decision, not a guess, so the overlay
    ships inert and the deltas get earned one at a time. ``parent`` must name a core ARCHETYPE_DNA."""
    name: str
    parent: str
    label: str
    weight_delta: dict = field(default_factory=dict)        # additive, on leg weights (identity={})
    confidence_delta: dict = field(default_factory=dict)    # additive, on confidence priors
    extra_risk_tags: frozenset = frozenset()                # union into correlation grouping (future)
    calibration: str = "identity (uncalibrated): display + correlation only"


#: Sub-archetypes per core. Names match asymmetry_rating.NICHE_TAGS (kept in sync via a test).
#: All deltas are EMPTY for now (identity) — the structure is live, the specialization is earned.
SUBARCHETYPE_DNA: dict[str, "SubArchetypeDNA"] = {
    # --- asset_light_yield: the royalty / holdco family the book lives in -------------------
    "nsr_royalty": SubArchetypeDNA(
        "nsr_royalty", "asset_light_yield", "NSR / gross-royalty (pure pass-through)",
        extra_risk_tags=frozenset({"royalty_stream_credit"})),
    "streamer": SubArchetypeDNA(
        "streamer", "asset_light_yield", "Metal streamer (carries more commodity beta than an NSR)",
        extra_risk_tags=frozenset({"royalty_stream_credit", "stream_commodity_beta"})),
    "royalty_generator_holdco": SubArchetypeDNA(
        "royalty_generator_holdco", "asset_light_yield",
        "Royalty generator / project-bank holdco (portfolio optionality — Globex-style)",
        extra_risk_tags=frozenset({"royalty_stream_credit", "portfolio_optionality"})),
    "mature_royalty": SubArchetypeDNA(
        "mature_royalty", "asset_light_yield", "Mature cash-yielding royalty",
        extra_risk_tags=frozenset({"royalty_stream_credit"})),
    # --- option_convexity: explorers / developers by de-risking stage -----------------------
    "grassroots": SubArchetypeDNA(
        "grassroots", "option_convexity", "Grassroots explorer (pre-resource)",
        extra_risk_tags=frozenset({"discovery_event"})),
    "delineation": SubArchetypeDNA(
        "delineation", "option_convexity", "Resource delineation / expansion drilling",
        extra_risk_tags=frozenset({"discovery_event"})),
    "pre_pea": SubArchetypeDNA(
        "pre_pea", "option_convexity", "Pre-PEA developer (resource defined, economics pending)",
        extra_risk_tags=frozenset({"discovery_event", "study_milestone"})),
    "pea_dev": SubArchetypeDNA(
        "pea_dev", "option_convexity", "PEA/PFS-stage developer (economics defined)",
        extra_risk_tags=frozenset({"study_milestone", "permitting"})),
    # --- commodity_cyclical: producers by cost / ramp position ------------------------------
    "near_term_dev": SubArchetypeDNA(
        "near_term_dev", "commodity_cyclical", "Near-term developer (financed / in construction)",
        extra_risk_tags=frozenset({"permitting", "financing"})),
    "ramp_up": SubArchetypeDNA(
        "ramp_up", "commodity_cyclical", "Ramp-up producer (commissioning / execution risk)",
        extra_risk_tags=frozenset({"operating_leverage", "execution"})),
    "marginal_producer": SubArchetypeDNA(
        "marginal_producer", "commodity_cyclical", "Marginal / high-cost producer (high spot leverage)",
        extra_risk_tags=frozenset({"operating_leverage", "cost_curve"})),
    "low_cost_producer": SubArchetypeDNA(
        "low_cost_producer", "commodity_cyclical", "Low-cost producer (durable margin)",
        extra_risk_tags=frozenset({"cost_curve"})),
    # --- pure_macro_delta: passive vehicles -------------------------------------------------
    "physical_trust": SubArchetypeDNA(
        "physical_trust", "pure_macro_delta", "Physical metal trust (NAV ~ spot)",
        extra_risk_tags=frozenset({"spot_delta"})),
    "futures_etp": SubArchetypeDNA(
        "futures_etp", "pure_macro_delta", "Futures / ETP (roll-yield exposed)",
        extra_risk_tags=frozenset({"spot_delta", "roll_yield"})),
    # --- capital_margin: capital-intensive operating ----------------------------------------
    "enricher": SubArchetypeDNA(
        "enricher", "capital_margin", "Conversion / enrichment (regulated capacity)",
        extra_risk_tags=frozenset({"regulated_margin"})),
    "infrastructure": SubArchetypeDNA(
        "infrastructure", "capital_margin", "Infrastructure / toll (rate-base)",
        extra_risk_tags=frozenset({"rates_duration", "regulated_margin"})),
}


def subarchetype_dna(name: Optional[str]) -> Optional["SubArchetypeDNA"]:
    """Resolve a sub-archetype overlay by name (None when absent/unknown — never raises)."""
    return SUBARCHETYPE_DNA.get(str(name or "")) if name else None


def subarchetypes_for(parent: Optional[str]) -> list["SubArchetypeDNA"]:
    """All sub-archetypes that specialize a given core archetype (empty when none)."""
    return [d for d in SUBARCHETYPE_DNA.values() if d.parent == parent]


def compose_leg_weights(core_weights: dict, sub: Optional["SubArchetypeDNA"]) -> dict:
    """Apply a sub-archetype's additive weight deltas to the parent leg weights, renormalized.
    IDENTITY (returns the core weights unchanged) when ``sub`` is None or carries no deltas — so an
    inert overlay can never move a valuation. Ready for the calibrated phase; unused in the blend
    until a delta is earned."""
    if sub is None or not sub.weight_delta:
        return dict(core_weights)
    merged = {k: max(0.0, float(core_weights.get(k, 0.0)) + float(sub.weight_delta.get(k, 0.0)))
              for k in core_weights}
    total = sum(merged.values())
    return {k: v / total for k, v in merged.items()} if total > 0 else dict(core_weights)


@dataclass
class _LegOutcome:
    """Internal carrier for one valuation leg (post-FX CAD value + confidence)."""
    value: float
    confidence: float
    warning: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Abstract base class
# --------------------------------------------------------------------------- #
class AssetArchetype(ABC):
    """Abstract base for every cash-flow-lifecycle archetype.

    Subclasses bind ``DNA`` to one of ``ARCHETYPE_DNA`` and implement the four
    abstract methods. This base supplies the shared machinery: the FX hook
    (base = CAD), the Regime Impact Vector plumbing (each archetype tilts ONE leg,
    once), confidence-tilted triangulation, graceful degradation, the
    CrowdEx-heritage pre-revenue scoring primitives + conviction overlay, the
    correlation-seeding risk-factor exposure, and the standardized
    ``valuation_summary`` contract."""

    DNA: ClassVar[ArchetypeDNA]

    def __init__(self, ticker: str, config: Optional[dict[str, Any]] = None,
                 fx_rates: Optional[dict[str, float]] = None, *,
                 base_currency: str = BASE_CURRENCY) -> None:
        self.ticker: str = ticker
        self.config: dict[str, Any] = config or {}
        self.base_currency: str = base_currency.upper()
        self.fx_rates: dict[str, float] = {self.base_currency: 1.0}
        if fx_rates:
            self.fx_rates.update({k.upper(): float(v) for k, v in fx_rates.items()})
        self.fx_rates.setdefault(
            "USD", float(self.config.get("usd_to_cad", self._factory_cfg("usd_to_cad_fallback", default=1.38))))
        self._breakdown: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    #  Metadata / config accessors
    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        return self.DNA.name

    def _factory_cfg(self, *keys: str, default: Any = None) -> Any:
        """Read from the optional ``archetype_factory`` config block (falls back to
        ``default`` so the legacy config works untouched)."""
        cur: Any = self.config.get("archetype_factory", {})
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def _tuning(self, key: str, default: Any) -> Any:
        """Read a per-archetype tuning value from ``archetype_factory[name][key]``."""
        val = self._factory_cfg(self.name, key, default=None)
        return val if val is not None else default

    def weights(self) -> dict[str, float]:
        """Stage (base) Cost/Market/Income leg weights (config-overridable)."""
        override = self._factory_cfg("weights", self.name, default=None)
        return dict(override) if isinstance(override, dict) else dict(self.DNA.base_weights)

    def base_confidence(self) -> dict[str, float]:
        """Per-leg confidence priors c_i (config-overridable)."""
        override = self._factory_cfg("confidence", self.name, default=None)
        return dict(override) if isinstance(override, dict) else dict(self.DNA.base_confidence)

    def native_currency(self, data: dict[str, Any]) -> str:
        """Resolve the asset's native trading currency: explicit in the payload,
        else from ``ballast_valuation[ticker].currency`` in config, else base."""
        ccy = data.get("currency") or self.config.get("ballast_valuation", {}).get(self.ticker, {}).get("currency")
        return str(ccy).upper() if ccy else self.base_currency

    # ------------------------------------------------------------------ #
    #  Uniform FX normalization hook (base currency = CAD)
    # ------------------------------------------------------------------ #
    def normalize_fx(self, value: float, currency: Optional[str] = None) -> float:
        """Convert ``value`` in ``currency`` into ``base_currency`` (CAD). The single
        point every leg passes through. Unknown currency degrades to x1.0; a
        non-finite value returns 0.0."""
        if not _finite(value):
            return 0.0
        ccy = (currency or self.base_currency).upper()
        return float(value) if ccy == self.base_currency else float(value) * self.fx_rates.get(ccy, 1.0)

    # ------------------------------------------------------------------ #
    #  Regime Impact Vector plumbing (applied ONCE, to DNA.regime_tilt_leg)
    # ------------------------------------------------------------------ #
    def regime_alpha(self, regime_vector: Optional[RegimeImpactVector]) -> float:
        """This archetype's coefficient from the 5-tuple, clamped to [-1, 1]; a
        missing/short/malformed vector degrades to neutral 0.0."""
        if not regime_vector:
            return 0.0
        try:
            if len(regime_vector) <= self.DNA.regime_index:
                return 0.0
            return clamp(float(regime_vector[self.DNA.regime_index]), -1.0, 1.0)
        except (TypeError, ValueError):
            return 0.0

    def regime_multiplier(self, regime_vector: Optional[RegimeImpactVector]) -> float:
        """Bounded macro-asymmetry multiplier ``clamp(1 + sensitivity*alpha, lo, hi)``
        (Druckenmiller lean-into-asymmetry); defaults to the [0.5, 1.5] band."""
        s = float(self._tuning("regime_sensitivity",
                               self._factory_cfg("regime", "sensitivity_default", default=0.5)))
        lo = float(self._factory_cfg("regime", "mult_floor", default=0.5))
        hi = float(self._factory_cfg("regime", "mult_ceiling", default=1.5))
        return clamp(1.0 + s * self.regime_alpha(regime_vector), lo, hi)

    # ------------------------------------------------------------------ #
    #  CrowdEx-heritage pre-revenue scoring primitives (shared helpers)
    # ------------------------------------------------------------------ #
    @staticmethod
    def runway_months(cash: float, monthly_burn: float) -> float:
        """Months of cash runway at the current burn (inf-safe)."""
        return cash / monthly_burn if monthly_burn > 0 else float("inf")

    @staticmethod
    def cash_burn_acceleration(curr_burn: float, prev_burn: float, denominator: float) -> float:
        """QoQ change in burn normalized by a size proxy. >0 means burn is
        accelerating faster than the buffer it is measured against."""
        return (curr_burn - prev_burn) / denominator if denominator > 0 else 0.0

    @staticmethod
    def dilution_velocity(shares_now: float, shares_prior: float, periods_per_year: float = 4.0) -> float:
        """Annualized share-count growth (QoQ dilution velocity). >0 = dilution."""
        if shares_prior <= 0:
            return 0.0
        return ((shares_now - shares_prior) / shares_prior) * periods_per_year

    # ------------------------------------------------------------------ #
    #  Insider-sentiment / conviction overlay (CrowdEx heritage)
    # ------------------------------------------------------------------ #
    def calculate_conviction(self, signals: dict[str, float]) -> float:
        """Bounded conviction score in [0, 1] (0.5 = neutral) from insider /
        sentiment / catalyst signals. A SIZING overlay surfaced in
        ``valuation_summary`` — deliberately OUT of the blended intrinsic so it
        never double-counts with the forensic penalty or the regime overlay.
        Subclasses may refine the weighting."""
        if not signals:
            return 0.5
        insider = clamp(signals.get("insider_net_buying", 0.0), -1.0, 1.0)
        catalyst = clamp(signals.get("catalyst_momentum", 0.0), -1.0, 1.0)
        flow = clamp(signals.get("institutional_flow", 0.0), -1.0, 1.0)
        short_pen = clamp(signals.get("short_interest_pressure", 0.0), 0.0, 1.0)
        raw = 0.5 + 0.5 * (0.40 * insider + 0.30 * catalyst + 0.20 * flow - 0.20 * short_pen)
        return clamp(raw, 0.0, 1.0)

    # ------------------------------------------------------------------ #
    #  Correlation foundation (cross-archetype sizing, future)
    # ------------------------------------------------------------------ #
    def risk_factor_exposure(self) -> dict[str, float]:
        """Loadings on shared risk factors (equal weight over ``DNA.risk_factor_tags``).
        Seeds a future cross-archetype correlation matrix so the sizer can net
        exposures across the whole book."""
        tags = self.DNA.risk_factor_tags
        if not tags:
            return {}
        w = round(1.0 / len(tags), 4)
        return {t: w for t in sorted(tags)}

    # ------------------------------------------------------------------ #
    #  Forensic penalty mapping + sieve scaffold
    # ------------------------------------------------------------------ #
    def forensic_penalty(self, score: float) -> float:
        """Map a 0–4 forensic score to a [0.70, 1.0] haircut (0.70 + 0.30*score/4)."""
        return clamp(0.70 + 0.30 * (clamp(score, 0.0, 4.0) / 4.0), 0.70, 1.0)

    def _sieve(self, tests: list[Tuple[str, Optional[bool]]]) -> Tuple[float, dict[str, str]]:
        """Score named pass/fail tests onto 0–4. ``None`` = indeterminate (missing
        data): excluded, score rescaled; all-indeterminate -> neutral default."""
        detail = {n: ("pass" if p else "fail" if p is not None else "n/a") for n, p in tests}
        determinate = [p for _, p in tests if p is not None]
        if not determinate:
            return clamp(float(self._factory_cfg("forensic_neutral_default", default=2.5)), 0.0, 4.0), detail
        return 4.0 * sum(1 for p in determinate if p) / len(determinate), detail

    # ------------------------------------------------------------------ #
    #  Abstract legs — subclasses MUST implement (all return CAD floats)
    # ------------------------------------------------------------------ #
    @abstractmethod
    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        """Cost / floor leg in CAD (replacement, NAV floor, treasury)."""

    @abstractmethod
    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        """Market / comparables leg in CAD (peer multiples, spot-linked value)."""

    @abstractmethod
    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        """Income / DCF leg in CAD. Income-tilted archetypes apply the macro overlay
        here; market/cost-tilted archetypes have it applied centrally."""

    @abstractmethod
    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        """Forensic sieve on a 0.0–4.0 scale (higher = cleaner)."""

    # ------------------------------------------------------------------ #
    #  Scenario band (optional; attached as ``scenarios`` when provided)
    # ------------------------------------------------------------------ #
    def scenario_band(self, data: dict[str, Any], comps: dict[str, Any], legs: dict[str, float],
                      confidences: dict[str, float], penalty: float,
                      regime_mult: float) -> Optional[dict[str, Any]]:
        """Optional base/bull/bear band. The base class provides none; archetypes with
        genuine scenario economics (e.g. option_convexity) override. When non-None,
        ``valuation_summary`` attaches it as ``scenarios`` and the engine wires
        base/bull/bear from it (replacing the old AGA.V-only ``is_spear`` gate)."""
        return None

    # ------------------------------------------------------------------ #
    #  Per-leg confidence (overridable) + safe-leg wrapper (graceful)
    # ------------------------------------------------------------------ #
    def assess_confidence(self, leg: str, value: float, data: dict[str, Any],
                          comps: dict[str, Any]) -> float:
        """Confidence c_i for a computed leg; 0 when not finite-positive (so it
        renormalizes out of the blend). Subclasses sharpen this."""
        if not _finite(value) or value <= 0.0:
            return 0.0
        return clamp(self.base_confidence().get(leg, 0.5), 0.0, 1.0)

    def _safe_leg(self, leg: str, fn: Callable[..., float], *args: Any) -> _LegOutcome:
        """Run a leg, converting SparseDataError (or any error) into a
        zero-confidence outcome + warning so one missing leg never crashes."""
        try:
            value = float(fn(*args))
            if not _finite(value):
                raise SparseDataError(f"{leg} leg returned a non-finite value")
        except SparseDataError as exc:
            return _LegOutcome(0.0, 0.0, warning=f"{leg}: {exc}")
        except Exception as exc:  # never let a leg take down the blend
            return _LegOutcome(0.0, 0.0, warning=f"{leg}: unexpected error: {exc}")
        comps = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
        conf = self.assess_confidence(leg, value, args[0] if args else {}, comps)
        return _LegOutcome(value, clamp(conf, 0.0, 1.0), detail=dict(self._breakdown.get(leg, {})))

    # ------------------------------------------------------------------ #
    #  Confidence-tilted triangulation
    # ------------------------------------------------------------------ #
    def triangulate(self, legs: dict[str, float], confidences: dict[str, float]
                    ) -> Tuple[float, dict[str, float]]:
        """Blend legs with confidence-tilted weights w_i = (W_i*c_i)/Σ(W_j*c_j)."""
        base_w = self.weights()
        raw = {k: max(0.0, base_w.get(k, 0.0)) * max(0.0, confidences.get(k, 0.0)) for k in legs}
        total = sum(raw.values())
        if total <= 0.0:
            return 0.0, {k: 0.0 for k in legs}
        weights = {k: raw[k] / total for k in legs}
        return sum(weights[k] * legs[k] for k in legs), weights

    # ------------------------------------------------------------------ #
    #  Standardized orchestration
    # ------------------------------------------------------------------ #
    def valuation_summary(self, data: dict[str, Any], comps: Optional[dict[str, Any]] = None,
                          regime_vector: Optional[RegimeImpactVector] = None,
                          financials: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Run the three legs + forensic sieve + conviction overlay and return the
        standardized dict (blended intrinsic, forensic penalty, component
        breakdown, plus regime/conviction/risk-factor context). The macro overlay
        is applied ONCE to ``DNA.regime_tilt_leg``; the forensic penalty multiplies
        the blended intrinsic (one transparent application), never an individual leg.
        Conviction is reported but kept OUT of the intrinsic (it is a sizing input)."""
        comps = comps if comps is not None else data.get("comps", {})
        regime_vector = tuple(regime_vector) if regime_vector else NEUTRAL_REGIME  # type: ignore[assignment]
        if financials is None:
            financials = data.get("financials", {})
        self._breakdown = {}

        cost = self._safe_leg("cost", self.calculate_cost_basis, data)
        market = self._safe_leg("market", self.calculate_market_basis, data, comps)
        income = self._safe_leg("income", self.calculate_income_basis, data, regime_vector)

        legs = {"cost": cost.value, "market": market.value, "income": income.value}
        confs = {"cost": cost.confidence, "market": market.confidence, "income": income.confidence}

        regime_mult = self.regime_multiplier(regime_vector)
        tilt_leg = self.DNA.regime_tilt_leg
        if tilt_leg in ("cost", "market"):                       # income-tilted legs self-apply (no double-tilt)
            legs[tilt_leg] = legs[tilt_leg] * regime_mult

        blended, weights = self.triangulate(legs, confs)
        forensic_score = clamp(float(self.calculate_forensic_score(financials)), 0.0, 4.0)
        penalty = self.forensic_penalty(forensic_score)
        conviction = self.calculate_conviction(data.get("conviction_signals", {}))
        band = self.scenario_band(data, comps, legs, confs, penalty, regime_mult)

        base_w = self.weights()
        expected = [k for k in legs if base_w.get(k, 0.0) > 0.0]
        live = sum(1 for k in expected if confs.get(k, 0.0) > 0.0)
        quality = "full" if (not expected or live == len(expected)) else "degraded" if live else "sparse"

        # 3rd taxonomy axis: surface the sub-archetype overlay + sector tags (metadata only — the
        # overlay deltas are identity, so the intrinsic above is unchanged). A parent-mismatch is a
        # config smell (e.g. a "streamer" tag on an explorer), so flag it without crashing.
        sub = subarchetype_dna(data.get("subarchetype"))
        warnings = [o.warning for o in (cost, market, income) if o.warning]
        if sub is not None and sub.parent != self.name:
            warnings.append(f"subarchetype '{sub.name}' expects parent '{sub.parent}', "
                            f"but {self.ticker} routed to '{self.name}'")

        out = {
            "ticker": self.ticker, "archetype": self.name, "archetype_code": self.DNA.code,
            "base_currency": self.base_currency, "native_currency": self.native_currency(data),
            "regime_index": self.DNA.regime_index,
            "regime_alpha": round(self.regime_alpha(regime_vector), 4),
            "regime_multiplier": round(regime_mult, 4), "regime_tilt_leg": tilt_leg,
            "legs": {k: round(v, 4) for k, v in legs.items()},
            "base_weights": {k: round(v, 3) for k, v in base_w.items()},
            "confidence": {k: round(v, 3) for k, v in confs.items()},
            "weights": {k: round(v, 3) for k, v in weights.items()},
            "blended_intrinsic": round(blended, 4),
            "forensic_score": round(forensic_score, 3), "forensic_penalty": round(penalty, 4),
            "intrinsic_after_forensic": round(blended * penalty, 4),
            "conviction": round(conviction, 4),
            "tags": sorted(self.DNA.tags), "risk_factor_exposure": self.risk_factor_exposure(),
            "subarchetype": sub.name if sub else None,
            "subarchetype_label": sub.label if sub else None,
            "subarchetype_parent": sub.parent if sub else None,
            "sector_tags": [str(t) for t in (data.get("sector_tags") or [])],
            "component_breakdown": {"cost": cost.detail, "market": market.detail,
                                    "income": income.detail, "forensic": self._breakdown.get("forensic", {})},
            "data_quality": quality,
            "warnings": warnings,
        }
        if isinstance(band, dict) and band:
            out["scenarios"] = band
        return out

    def __repr__(self) -> str:
        return f"<{type(self).__name__} ticker={self.ticker!r} archetype={self.name!r}>"


# =========================================================================== #
#  I.  Option Convexity — pre-revenue / binary-outcome (AGA.V explorer)
# =========================================================================== #
class OptionConvexityArchetype(AssetArchetype):
    """Pre-revenue explorers whose value is dominated by optionality on a discovery
    / commodity outcome (the Phase 4a triangulated spear, generalized).

    Cost   — REP floor (treasury + stressed in-situ resource + infra).
    Market — quality-graded defined ounces × peer EV/oz × capital discount, plus a
             once-risked exploration sub-leg, lifted by (1+pi_opt); the regime tilt
             leg (alpha_option amplifies/fades the convexity).
    Income — 0 (no recurring cash flow); folded into the market leg by design.
    """

    DNA = ARCHETYPE_DNA["option_convexity"]

    def _shares(self, data: dict[str, Any]) -> float:
        return _num(data, "shares_out", default=self.config.get("aga_shares_out", 0.0))

    def _capital_discount(self, data: dict[str, Any]) -> float:
        if _present(data, "macro", "capital_discount"):
            return _num(data, "macro", "capital_discount")
        if _present(data, "macro", "y30"):
            return capital_discount_factor(self.config, _num(data, "macro", "y30"))
        return 0.88

    def _rep_floor_params(self) -> dict:
        """REP floor params, per-ticker first (BRC.V 2026-09-19), else the global block."""
        by_ticker = self.config.get("rep_floor_params_by_ticker") or {}
        hit = by_ticker.get(self.ticker) if isinstance(by_ticker, dict) else None
        return hit if isinstance(hit, dict) else (self.config.get("rep_floor_params") or {})

    def _exploration_upside(self) -> dict:
        """Exploration upside params, per-ticker first (BRC.V 2026-09-19), else global.

        The global ``exploration_upside`` was calibrated to AGA.V's Red Mountain drill
        program (75M oz) — without this a promoted name would silently price AGA's
        exploration growth as its own."""
        by_ticker = self.config.get("exploration_upside_by_ticker") or {}
        hit = by_ticker.get(self.ticker) if isinstance(by_ticker, dict) else None
        if isinstance(hit, dict) and hit:
            return hit
        return self.config.get("exploration_upside", {}) or {}

    def _project_buckets(self) -> dict:
        """Project ounce buckets, per-ticker first (BRC.V 2026-09-19), else the global map.

        The global ``project_buckets_oz_AgEq`` still carries AGA.V's exited project mix —
        without this a newly promoted option-convexity name would silently value AGA's
        ounces as its own."""
        by_ticker = self.config.get("project_buckets_by_ticker") or {}
        hit = by_ticker.get(self.ticker) if isinstance(by_ticker, dict) else None
        if isinstance(hit, dict) and hit:
            return hit
        return self.config.get("project_buckets_oz_AgEq", {}) or {}

    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        shares = self._shares(data)
        rf = self._rep_floor_params()
        buckets = self._project_buckets()
        if not rf or not buckets or shares <= 0:
            raise SparseDataError("missing rep_floor_params / project buckets / shares")
        target_mi = self.config.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
        eff_oz = sum(oz * (target_mi.get(p, 0.50) + (1.0 - target_mi.get(p, 0.50)) * 0.50)
                     for p, oz in buckets.items())                # symmetric inferred haircut
        total = (rf["cash_treasury_m"] * 1e6 + eff_oz * rf["stressed_resource_per_oz"]
                 + rf["permitting_infra_premium_m"] * 1e6)
        rep = self.normalize_fx(total * rf["conservatism_scalar"] / shares, self.native_currency(data))
        self._breakdown["cost"] = {"method": "REP floor", "effective_oz": round(eff_oz, 0), "value_cad": round(rep, 4)}
        return rep

    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        shares = self._shares(data)
        peer_ev = _num(comps, "peer_ev_oz", default=0.0)
        buckets = self._project_buckets()
        if peer_ev <= 0 or not buckets or shares <= 0:
            raise SparseDataError("missing peer_ev_oz / buckets / shares")
        cap_disc = self._capital_discount(data)
        conservatism = self.config.get("conservatism_scalar", 0.88)
        target_mi = self.config.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
        v_mkt = sum_eff = sum_quality = 0.0
        tq_by_project: dict[str, Any] = {}
        for proj, oz in buckets.items():
            eff = oz * (target_mi.get(proj, 0.50) + (1.0 - target_mi.get(proj, 0.50)) * 0.50)
            tqd = technical_quality(self.config, proj)
            tq_by_project[proj] = tqd
            v_mkt += eff * tqd["tq"] * peer_ev * cap_disc
            sum_eff += eff
            sum_quality += eff * tqd["tq"]
        v_mkt_defined = v_mkt * conservatism / shares
        exp = self._exploration_upside()
        p_disc = _num(data, "p_discovery", default=exp.get("probability_of_discovery", 0.25))
        tq_expl = min(1.0, (sum_quality / sum_eff) if sum_eff > 0 else 1.0)     # undiscovered earns no premium
        # Audit F1 (2026-06-10): the exploration leg must carry the SAME cost-of-capital haircut
        # (cap_disc) as the defined-ounce market leg above (line ~769) — both value project ounces,
        # so omitting it here let the replica's exploration term run ~14% richer than the engine's
        # authoritative path (engine.py calculate_spear_intrinsic applies capital_discount_factor).
        # Parity guarded by tests/test_archetypes (engine-vs-replica v_expl).
        v_expl = (exp.get("expected_future_oz", 0) * p_disc * peer_ev * tq_expl
                  * exp.get("weight", 0.12) * cap_disc * conservatism) / shares
        industry_aisc = self.config.get("dynamic_discovery_v5", {}).get("estimated_industry_aisc_2026", 24.5)
        opt = option_premium(self.config, _num(data, "macro", "spot_ag"),
                             _num(data, "aisc", default=industry_aisc),
                             _num(data, "macro", "silver_vol", default=0.30),
                             _num(data, "macro", "real_yield", default=2.0), stage="explorer",
                             peer_aisc=industry_aisc)
        market = self.normalize_fx((v_mkt_defined + v_expl) * (1.0 + opt["pi_opt"]), self.native_currency(data))
        self._breakdown["market"] = {"method": "quality-graded comps + exploration x (1+pi_opt)",
                                     "v_mkt_defined": round(v_mkt_defined, 4), "v_exploration": round(v_expl, 4),
                                     "peer_ev_oz": peer_ev, "option_premium": opt, "tq_by_project": tq_by_project}
        return market

    def scenario_band(self, data: dict[str, Any], comps: dict[str, Any], legs: dict[str, float],
                      confidences: dict[str, float], penalty: float,
                      regime_mult: float) -> Optional[dict[str, Any]]:
        """Base/bull/bear band + one-at-a-time tornado for the option-convexity archetype.

        Reverse-engineers the AGA-standalone scenario shift set — silver ±1σ realized
        vol, peer EV/oz ±35%, real yield ±50 bps, discovery probability ±0.10 — through
        THIS archetype's own market leg (not the legacy valuation engine), with the two
        pieces the first replica missed now wired in:

        1. CONVEX operating-margin scaling of peer EV/oz under silver moves
           (``peer_ev_margin_scaled`` — the AGA-standalone surface's signature wire:
           peers re-rate with (spot − project AISC), not 1:1 with spot). The bull's
           peer factor is margin_up × (1 + peer_pct); the bear's is
           margin_dn × (1 − peer_pct); the tornado's silver lever carries the
           margin-scaled peer move, exactly like the legacy tornado.
        2. PM-CYCLE / TECHNICALS conditioning of the BULL's sector re-rating
           (``pm_cycle_bull_kicker``): when the engine's own live gauges read a PM
           bull regime (GSR < 75 silver outperformance, CFTC participation, soft
           dollar), the bull's peer-multiple expansion widens up to 1.5x the
           mechanical band. The bear keeps the mechanical band.

        The cost leg (REP floor) is scenario-invariant and income is 0 by design, so
        only the market leg is re-shocked; the bull therefore prices the project's own
        operating-margin convexity plus funded-drill exploration growth — for BRC.V,
        the 17,100m Tonopah program at a conservative 1.0 oz/m — never a generic
        multiple. Returns None when the market leg carries no confidence.
        """
        if not _finite(legs.get("market", 0.0)) or confidences.get("market", 0.0) <= 0:
            return None
        sh = self.config.get("scenarios", {}) or {}
        sigma_mult = float(sh.get("spot_sigma_mult", 1.0))
        peer_pct = float(sh.get("peer_ev_pct", 0.35))
        ry_bps = float(sh.get("real_yield_shift_bps", 50.0))
        dp = float(sh.get("p_discovery_shift", 0.10))
        macro = data.get("macro") if isinstance(data.get("macro"), dict) else {}
        spot = _num(macro, "spot_ag")
        vol = _num(macro, "silver_vol", default=0.30)
        ry = _num(macro, "real_yield", default=2.0)
        peer_ev = _num(comps, "peer_ev_oz")
        p0 = _num(data, "p_discovery",
                  default=self._exploration_upside().get("probability_of_discovery", 0.25))
        if not all(_finite(x) and x > 0 for x in (spot, vol, peer_ev)) or not _finite(ry):
            return None
        # Project's own AISC — the SAME source the market leg's relative-moneyness
        # term uses (data["aisc"]; 0 -> the margin scaler degrades to a linear spot
        # ratio, exactly like the engine's staticmethod).
        proj_aisc = _num(data, "aisc", default=0.0)
        spot_up = spot * (1.0 + sigma_mult * vol)
        spot_dn = spot * max(0.0, 1.0 - sigma_mult * vol)
        margin_up = peer_ev_margin_scaled(1.0, spot, spot_up, proj_aisc)
        margin_dn = peer_ev_margin_scaled(1.0, spot, spot_dn, proj_aisc)
        kick, kick_why = pm_cycle_bull_kicker(macro)
        bull_peer_f = margin_up * (1.0 + peer_pct * (1.0 + kick))
        bear_peer_f = margin_dn * (1.0 - peer_pct)
        tilt = self.DNA.regime_tilt_leg
        saved_breakdown = self._breakdown

        def _shocked(spot_f: float = 1.0, peer_f: float = 1.0,
                     ry_d: float = 0.0, p_d: float = 0.0) -> Optional[float]:
            d2 = dict(data)
            m2 = dict(macro)
            m2["spot_ag"] = spot * spot_f
            m2["real_yield"] = ry + ry_d
            d2["macro"] = m2
            # Legacy-faithful discovery caps: bull min(0.95, ...), bear max(0.0, ...).
            d2["p_discovery"] = min(0.95, max(0.0, p0 + p_d))
            c2 = dict(comps or {})
            c2["peer_ev_oz"] = peer_ev * peer_f
            try:
                mkt = float(self.calculate_market_basis(d2, c2))
            except Exception:
                return None
            if tilt == "market":
                mkt *= regime_mult
            blend, _ = self.triangulate({"cost": legs.get("cost", 0.0), "market": mkt,
                                         "income": 0.0}, confidences)
            return blend * penalty

        try:
            self._breakdown = {}
            base_v = _shocked()
            bull_v = _shocked(spot_f=spot_up / spot, peer_f=bull_peer_f,
                              ry_d=-ry_bps / 100.0, p_d=dp)
            bear_v = _shocked(spot_f=spot_dn / spot, peer_f=bear_peer_f,
                              ry_d=ry_bps / 100.0, p_d=-dp)
            if base_v is None or bull_v is None or bear_v is None:
                return None
            # Tornado, one-at-a-time upside contributions. The silver lever carries
            # the margin-scaled peer move (legacy-faithful: silver's bar includes
            # peers re-rating with the operating margin); the peer-multiple lever is
            # the INDEPENDENT sector re-rating at base spot.
            silver_up = _shocked(spot_f=spot_up / spot, peer_f=margin_up)
            peer_up = _shocked(peer_f=1.0 + peer_pct)
            ry_up = _shocked(ry_d=-ry_bps / 100.0)
            pd_up = _shocked(p_d=dp)
            tornado: dict[str, Any] = {}
            for name, v in (("silver", silver_up), ("peer_ev_oz", peer_up),
                            ("real_yield", ry_up), ("p_discovery", pd_up)):
                tornado[name] = round(v - base_v, 4) if v is not None else None
        finally:
            self._breakdown = saved_breakdown
        return {"base": round(base_v, 4), "bull": round(bull_v, 4),
                "bear": round(max(0.0, bear_v), 4), "tornado": tornado,
                "shifts": {"spot_sigma_mult": sigma_mult, "silver_vol": round(vol, 4),
                           "spot_up": round(spot_up, 2), "spot_dn": round(spot_dn, 2),
                           "project_aisc_usd": round(proj_aisc, 2),
                           "peer_margin_up": round(margin_up, 4),
                           "peer_margin_dn": round(margin_dn, 4),
                           "bull_peer_factor": round(bull_peer_f, 4),
                           "bear_peer_factor": round(bear_peer_f, 4),
                           "peer_ev_pct": peer_pct,
                           "cycle_kicker": round(kick, 4), "cycle_reasons": kick_why,
                           "gsr": macro.get("gsr"),
                           "real_yield_shift_bps": ry_bps,
                           "p_discovery_shift": dp, "p_discovery_base": round(p0, 4)},
                "method": "option_convexity scenario_band (AGA-standalone shift set: convex "
                          "operating-margin peer scaling + PM-cycle-conditioned bull rerating, "
                          "archetype-native market-leg rerun)"}

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        # A pre-revenue explorer has no recurring cash flow; the legitimate
        # optionality lives in the market leg (alpha_option tilts it there).
        self._breakdown["income"] = {"method": "none (pre-revenue explorer)", "value_cad": 0.0}
        return 0.0

    def assess_confidence(self, leg: str, value: float, data: dict[str, Any], comps: dict[str, Any]) -> float:
        if leg == "income":
            return 0.0
        base = super().assess_confidence(leg, value, data, comps)
        if leg == "market":                                       # Inferred-heavy ounces => less confident
            tm = self.config.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
            avg_mi = (sum(tm.values()) / len(tm)) if tm else 0.5
            return clamp(base * (0.6 + 0.4 * avg_mi), 0.0, 1.0)
        return base

    def calculate_conviction(self, signals: dict[str, float]) -> float:
        # A binary explorer is catalyst- and insider-driven: lean on those signals.
        if not signals:
            return 0.5
        insider = clamp(signals.get("insider_net_buying", 0.0), -1.0, 1.0)
        catalyst = clamp(signals.get("catalyst_momentum", 0.0), -1.0, 1.0)
        short_pen = clamp(signals.get("short_interest_pressure", 0.0), 0.0, 1.0)
        return clamp(0.5 + 0.5 * (0.45 * catalyst + 0.40 * insider - 0.15 * short_pen), 0.0, 1.0)

    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        f = financials or {}
        tests: list[Tuple[str, Optional[bool]]] = []
        cash, burn = _num(f, "cash", default=float("nan")), _num(f, "monthly_burn", default=float("nan"))
        tests.append(("runway", (self.runway_months(cash, burn) >= 18.0) if (_finite(cash) and burn > 0) else None))
        if _present(f, "curr_burn") and _present(f, "prev_burn"):
            ev = _num(f, "enterprise_value", default=float("nan"))
            if _finite(ev) and ev > 0:
                tests.append(("cba", self.cash_burn_acceleration(_num(f, "curr_burn"), _num(f, "prev_burn"),
                                                                 max(5e6, ev)) <= 0.03))
            else:
                denom = _num(f, "cash", default=float("nan"))
                tests.append(("cba", (self.cash_burn_acceleration(_num(f, "curr_burn"), _num(f, "prev_burn"),
                                                                  denom) <= 0.15) if (_finite(denom) and denom > 0) else None))
        else:
            tests.append(("cba", None))
        s0, s1 = _num(f, "shares_t0", default=float("nan")), _num(f, "shares_t1", default=float("nan"))
        tests.append(("dilution_velocity", (self.dilution_velocity(s0, s1) < 0.08)
                      if (_finite(s0) and _finite(s1) and s1 > 0) else None))   # <8%/yr (~2% QoQ)
        sga = _num(f, "sga_expense", default=float("nan"))
        tests.append(("sga_drag", (sga / (burn * 3.0) < 0.30) if (_finite(sga) and _finite(burn) and burn > 0) else None))
        score, detail = self._sieve(tests)
        self._breakdown["forensic"] = {"sieve": "explorer (pre-revenue)", "tests": detail, "score": round(score, 3)}
        return score


# =========================================================================== #
#  II.  Capital Margin — capital-intensive operating (regulated infra / defense)
# =========================================================================== #
class CapitalMarginArchetype(AssetArchetype):
    """Capital-intensive operating businesses earning a spread on a large invested
    capital base — regulated infrastructure, utilities, and (via the defense
    toggle) prime contractors with regulated-margin, low-cyclicality cash flows.

    Cost   — (invested_capital − net_debt)/shares, or book value/share.
    Market — EV/EBITDA comp (P/Book fallback).
    Income — earnings-power value FCF/(wacc−g); the defense/regulated toggle widens
             the moat (lower effective discount). Regime tilt leg (alpha_margin).
    """

    DNA = ARCHETYPE_DNA["capital_margin"]

    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        ccy, shares = self.native_currency(data), _num(data, "shares_out", default=float("nan"))
        if _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share"), ccy)
            self._breakdown["cost"] = {"method": "book value / share", "value_cad": round(v, 4)}
            return v
        if _present(data, "invested_capital") and shares > 0:
            v = self.normalize_fx((_num(data, "invested_capital") - _num(data, "net_debt")) / shares, ccy)
            self._breakdown["cost"] = {"method": "(invested_capital - net_debt)/shares", "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need book_value_per_share or invested_capital+shares")

    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        ccy, shares = self.native_currency(data), _num(data, "shares_out", default=float("nan"))
        ev_ebitda, ebitda = _num(comps, "ev_ebitda", default=float("nan")), _num(data, "ebitda", default=float("nan"))
        if _finite(ev_ebitda) and _finite(ebitda) and shares > 0:
            v = self.normalize_fx((ebitda * ev_ebitda - _num(data, "net_debt")) / shares, ccy)
            self._breakdown["market"] = {"method": "EV/EBITDA comp", "ev_ebitda": ev_ebitda, "value_cad": round(v, 4)}
            return max(0.0, v)
        pb = _num(comps, "p_book", default=float("nan"))
        if _finite(pb) and _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share") * pb, ccy)
            self._breakdown["market"] = {"method": "P/Book comp (fallback)", "p_book": pb, "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need ev_ebitda+ebitda or p_book+book value")

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        ccy, shares = self.native_currency(data), _num(data, "shares_out", default=float("nan"))
        fcf_ps = _num(data, "fcf_per_share", default=float("nan"))
        if not _finite(fcf_ps):
            fcf = _num(data, "free_cash_flow", default=float("nan"))
            fcf_ps = fcf / shares if (_finite(fcf) and shares > 0) else float("nan")
        if not _finite(fcf_ps):
            raise SparseDataError("need fcf_per_share or free_cash_flow+shares")
        wacc, g = float(self._tuning("wacc", 0.10)), float(self._tuning("terminal_growth", 0.02))
        if data.get("defense_or_regulated") or data.get("regulated"):    # wider moat -> lower discount
            wacc = max(g + 0.02, wacc - float(self._tuning("defense_moat_premium", 0.15)) * (wacc - g))
        regime_mult = self.regime_multiplier(regime_vector)              # alpha_margin tilt (once, here)
        v = self.normalize_fx((fcf_ps / max(0.04, wacc - g)) * regime_mult, ccy)
        self._breakdown["income"] = {"method": "earnings-power value FCF/(wacc-g)", "fcf_per_share": round(fcf_ps, 4),
                                     "wacc": round(wacc, 4), "regime_multiplier": round(regime_mult, 4),
                                     "value_cad": round(v, 4)}
        return max(0.0, v)

    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        return _producer_sieve(self, financials, "capital_margin")


# =========================================================================== #
#  III.  Commodity Cyclical — spot-price dominated margin business (GMX.TO)
# =========================================================================== #
class CommodityCyclicalArchetype(AssetArchetype):
    """Operating miners/developers whose margin is dominated by the spot price of
    the underlying commodity, with high operating leverage (spot_beta > 1).

    Cost   — stressed reserve NAV/share, book, or a conservative fraction of the
             spot-linked NAV (graceful fallback; the proxy floor is lower-confidence).
    Market — spot-linked fair value (operating beta), decoupled from share price.
    Income — spot-margin capitalization production × (spot − AISC) × years/shares.
             Regime tilt leg (alpha_cyclical).
    """

    DNA = ARCHETYPE_DNA["commodity_cyclical"]

    def _spot_now(self, data: dict[str, Any], commodity: str) -> float:
        return _commodity_spot(data, commodity)

    def _ballast(self, data: dict[str, Any]) -> dict[str, Any]:
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        return {
            "ref_price": _num(data, "ref_price", default=bv.get("ref_price", 0.0)),
            "base_mult": _num(data, "base_mult", default=bv.get("base_mult", 1.20)),
            "commodity": data.get("commodity", bv.get("commodity", "silver")),
            "spot_ref": _num(data, "spot_ref", default=bv.get("spot_ref", 0.0)),
            "spot_beta": _num(data, "spot_beta",
                              default=bv.get("spot_beta", float(self._tuning("default_spot_beta", 1.35)))),
        }

    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        ccy = self.native_currency(data)
        if _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share"), ccy)
            self._breakdown["cost"] = {"method": "book value / share", "value_cad": round(v, 4)}
            return v
        if _present(data, "reserves_oz") and _present(data, "shares_out"):
            stressed = _num(data, "stressed_resource_per_oz", default=self.config.get("dynamic_discovery_v5", {})
                            .get("stressed_resource_baseline", 0.65))
            v = self.normalize_fx(_num(data, "reserves_oz") * stressed / _num(data, "shares_out"), ccy)
            self._breakdown["cost"] = {"method": "stressed reserve NAV/share", "value_cad": round(v, 4)}
            return v
        p = self._ballast(data)
        if p["ref_price"] > 0 and p["spot_ref"] > 0:
            frac = float(self._tuning("cost_floor_frac", 0.45))
            fv = spot_linked_fair_value(p["ref_price"], p["base_mult"], self._spot_now(data, p["commodity"]),
                                        p["spot_ref"], 1.0)
            v = self.normalize_fx(fv * frac, ccy)
            self._breakdown["cost"] = {"method": f"{frac:g}x spot-linked NAV floor (proxy)", "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need book value, reserves+shares, or ballast ref params")

    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        p = self._ballast(data)
        if p["ref_price"] <= 0 or p["spot_ref"] <= 0:
            raise SparseDataError("need ballast ref_price + spot_ref")
        spot_now = self._spot_now(data, p["commodity"])
        v = self.normalize_fx(spot_linked_fair_value(p["ref_price"], p["base_mult"], spot_now,
                                                      p["spot_ref"], p["spot_beta"]), self.native_currency(data))
        self._breakdown["market"] = {"method": "spot-linked fair value (operating beta)",
                                     "spot_beta": p["spot_beta"], "spot_now": round(spot_now, 4),
                                     "spot_ref": round(p["spot_ref"], 4), "commodity": p["commodity"],
                                     "value_cad": round(v, 4)}
        return v

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        shares = _num(data, "shares_out", default=float("nan"))
        prod, aisc = _num(data, "annual_production_oz", default=float("nan")), _num(data, "aisc", default=float("nan"))
        p = self._ballast(data)
        spot_now = self._spot_now(data, p["commodity"])
        if not (_finite(prod) and _finite(aisc) and shares > 0 and spot_now > 0):
            raise SparseDataError("need annual_production_oz, aisc, shares, spot")
        years = float(self._tuning("margin_capitalization_years", 6.0))
        regime_mult = self.regime_multiplier(regime_vector)              # alpha_cyclical tilt (once, here)
        v = self.normalize_fx((prod * max(0.0, spot_now - aisc) * years / shares) * regime_mult,
                              self.native_currency(data))
        self._breakdown["income"] = {"method": "spot-margin capitalization", "margin": round(max(0.0, spot_now - aisc), 4),
                                     "years": years, "regime_multiplier": round(regime_mult, 4), "value_cad": round(v, 4)}
        return max(0.0, v)

    def assess_confidence(self, leg: str, value: float, data: dict[str, Any], comps: dict[str, Any]) -> float:
        base = super().assess_confidence(leg, value, data, comps)
        if leg == "cost" and self._breakdown.get("cost", {}).get("method", "").endswith("(proxy)"):
            return clamp(base * 0.6, 0.0, 1.0)                           # a derived floor is less trustworthy
        return base

    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        return _producer_sieve(self, financials, "commodity_cyclical")


# =========================================================================== #
#  IV.  Asset-Light Yield — recurring high-margin cash flow (URC.TO, GROY)
# =========================================================================== #
class AssetLightYieldArchetype(AssetArchetype):
    """Royalty / streaming / asset-light businesses: high-margin, recurring,
    capital-light cash flows; the income (NAV) leg dominates. FX matters — GROY
    trades in USD and the FX hook normalizes every leg to CAD.

    Cost   — thin tangible floor (cash/book, or a small fraction of NAV).
    Market — P/NAV spot-linked value, spot_beta ~ 1 (pass-through).
    Income — risked perpetuity stream/NSR NAV cashflow × risk/(discount − growth).
             Regime tilt leg (alpha_yield: falling real yields lift NAV).
    """

    DNA = ARCHETYPE_DNA["asset_light_yield"]

    def _spot_now(self, data: dict[str, Any], commodity: str) -> float:
        return _commodity_spot(data, commodity)

    def _royalty_floor_cfg(self) -> dict:
        """Stressed-floor tuning (proposal-gated via config ``royalty_floor``). Stress the producing
        cash flow to a conservative commodity price and capitalize it at a higher 'floor' discount with
        NO growth — so the floor stays a hard, recoverable downside below the base NAV intrinsic."""
        rf = self.config.get("royalty_floor", {})
        return {"cashflow_stress": 0.65, "discount": 0.12,
                **(rf if isinstance(rf, dict) else {})}

    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        """Asset-light (royalty / streamer) FLOOR — the royalty analogue of the spear's REP floor:
        net liquid backing PLUS a stressed NPV of the *producing* royalty stream (additive — what is
        actually recoverable in a downside), NOT accounting book value. A royalty's interests are
        carried at historical cost, so book systematically UNDERSTATES the economic floor (it is why
        royalty names persistently trade well above book); book/cash/reference are kept only as a
        clearly-LABELLED degraded proxy when the asset-backing inputs aren't sourced — never the
        headline floor. Mirrors OptionConvexity's cash-treasury + stressed-in-ground-resource REP."""
        ccy = self.native_currency(data)
        shares = _num(data, "shares_out", default=float("nan"))

        # (1) net liquid backing per share — cash / working capital, net of debt (genuinely recoverable)
        nlb = float("nan")
        if _present(data, "net_liquid_assets_per_share"):
            nlb = _num(data, "net_liquid_assets_per_share", default=float("nan"))
        elif _present(data, "working_capital") and _finite(shares) and shares > 0:
            nlb = (_num(data, "working_capital", default=0.0)
                   - _num(data, "total_debt", default=0.0)) / shares
        elif _present(data, "cash_per_share"):
            nlb = _num(data, "cash_per_share", default=float("nan"))

        # (2) stressed NPV of the PRODUCING royalty stream — perpetuity at a stressed commodity price
        #     and a floor discount, NO growth (the royalty analogue of stressed in-ground ounces)
        rf = self._royalty_floor_cfg()
        cf_ps = _num(data, "annual_cashflow_per_share", default=float("nan"))
        if not _finite(cf_ps):
            cf = _num(data, "annual_cashflow", default=float("nan"))
            cf_ps = cf / shares if (_finite(cf) and _finite(shares) and shares > 0) else float("nan")
        stressed_nav = float("nan")
        if _finite(cf_ps) and cf_ps > 0:
            stressed_nav = (cf_ps * float(rf["cashflow_stress"])) / max(0.03, float(rf["discount"]))

        legs = [x for x in (nlb, stressed_nav) if _finite(x) and x > 0]
        if legs:
            v = self.normalize_fx(sum(legs), ccy)           # additive: liquid backing + stressed stream
            self._breakdown["cost"] = {
                "method": "net liquid backing + stressed royalty NAV (REP-equivalent)",
                "net_liquid_backing": round(nlb, 4) if _finite(nlb) else None,
                "stressed_royalty_nav": round(stressed_nav, 4) if _finite(stressed_nav) else None,
                "value_cad": round(v, 4)}
            return v

        # --- degraded proxies (LABELLED so the ribbon / dossier can flag them; never the headline) ---
        if _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share", default=float("nan")), ccy)
            self._breakdown["cost"] = {"method": "book value / share (DEGRADED proxy — asset-backing "
                                       "floor inputs not sourced)", "degraded_proxy": True,
                                       "value_cad": round(v, 4)}
            return v
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        ref = _num(data, "ref_price", default=bv.get("ref_price", 0.0))
        if ref > 0:
            frac = float(bv.get("cost_floor_frac", self._tuning("cost_floor_frac", 0.10)))
            v = self.normalize_fx(ref * frac, ccy)
            self._breakdown["cost"] = {"method": f"{frac:g}x reference (DEGRADED thin proxy)",
                                       "degraded_proxy": True, "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need net-liquid backing + royalty cash flow (the asset-backing floor), "
                              "or a book/cash/reference proxy")

    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        ref = _num(data, "ref_price", default=bv.get("ref_price", 0.0))
        spot_ref = _num(data, "spot_ref", default=bv.get("spot_ref", 0.0))
        if ref <= 0 or spot_ref <= 0:
            raise SparseDataError("need ref_price + spot_ref")
        commodity = data.get("commodity", bv.get("commodity", "silver"))
        base_mult = _num(data, "base_mult", default=bv.get("base_mult", 1.15))
        p_nav = _num(comps, "p_nav", default=float("nan"))
        mult = base_mult * p_nav if _finite(p_nav) else base_mult
        beta = _num(data, "spot_beta", default=bv.get("spot_beta", 1.0))   # royalty ~ pass-through
        spot_now = self._spot_now(data, commodity)
        v = self.normalize_fx(spot_linked_fair_value(ref, mult, spot_now, spot_ref, beta), self.native_currency(data))
        self._breakdown["market"] = {"method": "P/NAV spot-linked fair value", "mult": round(mult, 4),
                                     "spot_beta": beta, "spot_now": round(spot_now, 4),
                                     "spot_ref": round(spot_ref, 4), "commodity": commodity,
                                     "value_cad": round(v, 4)}
        return v

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        cf_ps = _num(data, "annual_cashflow_per_share", default=float("nan"))
        if not _finite(cf_ps):
            cf, sh = _num(data, "annual_cashflow", default=float("nan")), _num(data, "shares_out", default=float("nan"))
            cf_ps = cf / sh if (_finite(cf) and sh > 0) else float("nan")
        if not _finite(cf_ps):
            raise SparseDataError("need annual_cashflow_per_share or annual_cashflow+shares")
        discount = _num(data, "discount_rate", default=float(self._tuning("default_discount", 0.09)))
        growth = _num(data, "growth", default=float(self._tuning("default_growth", 0.02)))
        risk = _num(data, "risk", default=float(self._tuning("default_risk", 0.85)))
        regime_mult = self.regime_multiplier(regime_vector)              # alpha_yield tilt (once, here)
        v = self.normalize_fx((cf_ps * risk / max(0.03, discount - growth)) * regime_mult, self.native_currency(data))
        self._breakdown["income"] = {"method": "risked stream/NSR NAV (perpetuity)", "cashflow_per_share": round(cf_ps, 4),
                                     "discount": discount, "risk": risk, "regime_multiplier": round(regime_mult, 4),
                                     "value_cad": round(v, 4)}
        return max(0.0, v)

    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        return _producer_sieve(self, financials, "asset_light_yield")


# =========================================================================== #
#  V.  Pure Macro Delta — passive commodity vehicle, no operations (trusts/futures)
# =========================================================================== #
class PureMacroDeltaArchetype(AssetArchetype):
    """Passive vehicles that ARE the commodity exposure — physical trusts (PSLV),
    futures, ETPs with no operating business; value is ~1:1 with spot.

    Cost   — NAV anchor (per-unit holdings at the reference frame).
    Market — spot delta nav_ref × (spot/spot_ref) × delta. Regime tilt leg
             (alpha_delta: the pure directional bet).
    Income — negative carry (management/storage fee drag); informational (weight 0).
    """

    DNA = ARCHETYPE_DNA["pure_macro_delta"]

    def _spot_now(self, data: dict[str, Any], commodity: str) -> float:
        return _commodity_spot(data, commodity)

    def _nav_ref(self, data: dict[str, Any]) -> float:
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        return _num(data, "nav_per_unit", default=_num(data, "ref_price", default=bv.get("ref_price", 0.0)))

    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        nav = self._nav_ref(data)
        if nav <= 0:
            raise SparseDataError("need nav_per_unit / ref_price")
        v = self.normalize_fx(nav, self.native_currency(data))           # holdings are the hard floor
        self._breakdown["cost"] = {"method": "NAV anchor (holdings/unit)", "value_cad": round(v, 4)}
        return v

    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        nav = self._nav_ref(data)
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        commodity = data.get("commodity", bv.get("commodity", "silver"))
        spot_ref, spot_now = _num(data, "spot_ref", default=bv.get("spot_ref", 0.0)), self._spot_now(data, commodity)
        if nav <= 0 or spot_ref <= 0 or spot_now <= 0:
            raise SparseDataError("need nav, spot_ref, and live spot")
        delta = _num(data, "delta", default=1.0)                         # 1.0 for a 1x physical trust
        v = self.normalize_fx(nav * (spot_now / spot_ref) * delta, self.native_currency(data))
        self._breakdown["market"] = {"method": "spot delta (pass-through)", "nav_ref": round(nav, 4),
                                     "spot_now": round(spot_now, 4), "spot_ref": round(spot_ref, 4),
                                     "spot_beta": 1.0, "commodity": commodity, "delta": delta,
                                     "value_cad": round(v, 4)}
        return v

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        nav = self._nav_ref(data)
        if nav <= 0:
            raise SparseDataError("need nav to compute fee drag")
        fee = _num(data, "fee_drag_annual", default=float(self._tuning("fee_drag_annual", 0.004)))
        v = self.normalize_fx(-fee * nav, self.native_currency(data))    # negative carry, no operations
        self._breakdown["income"] = {"method": "negative carry (fee drag)", "fee": fee, "value_cad": round(v, 4)}
        return v

    def assess_confidence(self, leg: str, value: float, data: dict[str, Any], comps: dict[str, Any]) -> float:
        if leg == "income":                                              # real but tiny & negative; never zero-by-sign
            return clamp(self.base_confidence().get("income", 0.30), 0.0, 1.0) if _finite(value) else 0.0
        return super().assess_confidence(leg, value, data, comps)

    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        # A passive vehicle has no accruals; the relevant risks are tracking and fee load.
        f = financials or {}
        prem, fee, liq = (_num(f, "premium_to_nav", default=float("nan")),
                          _num(f, "expense_ratio", default=float("nan")), _num(f, "adv_usd", default=float("nan")))
        backing = f.get("physically_backed")
        tests: list[Tuple[str, Optional[bool]]] = [
            ("nav_tracking", abs(prem) <= 0.05 if _finite(prem) else None),
            ("low_fee", fee <= 0.0075 if _finite(fee) else None),
            ("liquidity", liq >= 1_000_000 if _finite(liq) else None),
            ("backing", bool(backing) if backing is not None else None)]
        score, detail = self._sieve(tests)
        self._breakdown["forensic"] = {"sieve": "passive_vehicle", "tests": detail, "score": round(score, 3)}
        return score


# --------------------------------------------------------------------------- #
#  Shared producer-style forensic sieve (Capital Margin / Cyclical / Yield)
# --------------------------------------------------------------------------- #
def _producer_sieve(arch: AssetArchetype, financials: dict[str, Any], sieve_name: str) -> float:
    """Sloan-accrual + leverage + dilution-velocity sieve for cash-flow producers
    (mirrors the producer branch of ``ForensicEngine.calculate_jsf_score``)."""
    f = financials or {}
    sloan_cfo, sloan_bs = _num(f, "sloan_cfo", default=float("nan")), _num(f, "sloan_bs", default=float("nan"))
    nd, ebitda = _num(f, "net_debt", default=float("nan")), _num(f, "ebitda", default=float("nan"))
    s0, s1 = _num(f, "shares_t0", default=float("nan")), _num(f, "shares_t1", default=float("nan"))
    tests: list[Tuple[str, Optional[bool]]] = [
        ("sloan_cfo", sloan_cfo < 0.05 if _finite(sloan_cfo) else None),
        ("sloan_bs", sloan_bs < 0.05 if _finite(sloan_bs) else None),
        ("leverage", (nd / ebitda < 3.0) if (_finite(nd) and _finite(ebitda) and ebitda > 0) else None),
        ("dilution_velocity", (arch.dilution_velocity(s0, s1) < 0.08) if (_finite(s0) and _finite(s1) and s1 > 0) else None)]
    score, detail = arch._sieve(tests)
    arch._breakdown["forensic"] = {"sieve": sieve_name, "tests": detail, "score": round(score, 3)}
    return score


# --------------------------------------------------------------------------- #
#  Registry maps
# --------------------------------------------------------------------------- #
ARCHETYPE_REGISTRY: dict[str, type[AssetArchetype]] = {
    "option_convexity": OptionConvexityArchetype,
    "capital_margin": CapitalMarginArchetype,
    "commodity_cyclical": CommodityCyclicalArchetype,
    "asset_light_yield": AssetLightYieldArchetype,
    "pure_macro_delta": PureMacroDeltaArchetype,
}

#: portfolio_metadata "type" -> archetype short-name (routing fallback)
ARCHETYPE_BY_TYPE: dict[str, str] = {
    "explorer": "option_convexity", "developer": "commodity_cyclical", "producer": "commodity_cyclical",
    "producing": "commodity_cyclical", "royalty": "asset_light_yield", "streamer": "asset_light_yield",
    "infrastructure": "capital_margin", "utility": "capital_margin", "defense": "capital_margin",
    "trust": "pure_macro_delta", "etf": "pure_macro_delta", "futures": "pure_macro_delta",
}


# --------------------------------------------------------------------------- #
#  PolymorphicRouter — metadata-driven; tag + score routing; lifecycle-versioned
# --------------------------------------------------------------------------- #
@dataclass(order=True)
class _LifecycleVersion:
    """One entry on a ticker's archetype timeline (``effective=None`` = inception)."""
    sort_key: Tuple[bool, date] = field(init=False, repr=False)
    effective: Optional[date]
    archetype: AssetArchetype = field(compare=False)
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        self.sort_key = (self.effective is not None, self.effective or date.min)


class PolymorphicRouter:
    """Metadata-driven ``ticker -> archetype`` registry with fail-fast lookup, tag-
    and score-threshold routing, and historical lifecycle versioning.

    Resolution precedence: (1) explicit ticker mapping (lifecycle-versioned),
    (2) tag rules (payload ``tags`` ∩ rule tag), (3) score-threshold rules (payload
    metric within band), else raise :class:`TickerNotRegisteredError`."""

    def __init__(self, config: Optional[dict[str, Any]] = None,
                 fx_rates: Optional[dict[str, float]] = None) -> None:
        self.config: dict[str, Any] = config or {}
        self.fx_rates: Optional[dict[str, float]] = fx_rates
        self._by_ticker: dict[str, list[_LifecycleVersion]] = {}
        self._class_registry: dict[str, type[AssetArchetype]] = {}
        self._tag_rules: list[tuple[int, str, str]] = []                 # (priority, tag, archetype_name)
        self._score_rules: list[tuple[int, str, float, float, str]] = []  # (priority, metric, lo, hi, name)

    # -- class plug-in & registration ----------------------------------- #
    def register_archetype_class(self, name: str, cls: type[AssetArchetype]) -> None:
        """Bind an archetype short-name to its concrete class so tag/score rules can
        instantiate it on demand."""
        if not (isinstance(cls, type) and issubclass(cls, AssetArchetype)):
            raise ArchetypeConfigError(f"{name!r} must map to an AssetArchetype subclass")
        self._class_registry[name] = cls

    def register_asset(self, ticker: str, archetype: AssetArchetype, *,
                       effective: Optional[date] = None, label: str = "") -> None:
        """Register (or version) an archetype instance for a ticker. A later
        ``effective`` date appends a lifecycle version; a duplicate date replaces."""
        if not isinstance(archetype, AssetArchetype):
            raise ArchetypeConfigError(f"register_asset expects an AssetArchetype, got {type(archetype).__name__}")
        versions = self._by_ticker.setdefault(ticker, [])
        for v in versions:
            if v.effective == effective:
                v.archetype, v.label = archetype, (label or v.label)
                break
        else:
            versions.append(_LifecycleVersion(effective=effective, archetype=archetype, label=label))
        versions.sort()

    def migrate_asset(self, ticker: str, archetype: AssetArchetype, effective: date, label: str = "") -> None:
        """Append a later lifecycle version (a lifecycle graduation). Ticker must exist."""
        if ticker not in self._by_ticker:
            raise TickerNotRegisteredError(f"{ticker!r} is not registered; call register_asset first")
        self.register_asset(ticker, archetype, effective=effective, label=label)

    def register_tag_rule(self, tag: str, archetype_name: str, *, priority: int = 0) -> None:
        """Route any asset carrying ``tag`` (in its payload ``tags``) to an archetype."""
        self._tag_rules.append((priority, tag, archetype_name))
        self._tag_rules.sort(key=lambda r: r[0], reverse=True)

    def register_score_rule(self, metric: str, low: float, high: float,
                            archetype_name: str, *, priority: int = 0) -> None:
        """Route by a payload metric falling within ``[low, high]`` (score-threshold)."""
        self._score_rules.append((priority, metric, low, high, archetype_name))
        self._score_rules.sort(key=lambda r: r[0], reverse=True)

    # -- resolution ----------------------------------------------------- #
    def _instantiate(self, name: str, ticker: str) -> AssetArchetype:
        cls = self._class_registry.get(name) or ARCHETYPE_REGISTRY.get(name)
        if cls is None:
            raise ArchetypeConfigError(f"archetype class {name!r} not registered (register_archetype_class)")
        return cls(ticker, self.config, fx_rates=self.fx_rates)

    def is_registered(self, ticker: str) -> bool:
        return bool(self._by_ticker.get(ticker))

    def resolve(self, ticker: str, data_payload: Optional[dict[str, Any]] = None, *,
                as_of: Optional[date] = None) -> AssetArchetype:
        """Resolve the archetype for a ticker via the precedence above; fail-fast
        with TickerNotRegisteredError if no route matches."""
        versions = self._by_ticker.get(ticker)
        if versions:
            if as_of is None:
                return versions[-1].archetype
            eligible = [v for v in versions if v.effective is None or v.effective <= as_of]
            return (eligible[-1] if eligible else versions[0]).archetype
        payload = data_payload or {}
        payload_tags = set(payload.get("tags", []))
        for _prio, tag, name in self._tag_rules:
            if tag in payload_tags:
                return self._instantiate(name, ticker)
        for _prio, metric, lo, hi, name in self._score_rules:
            if metric in payload and _finite(payload[metric]) and lo <= float(payload[metric]) <= hi:
                return self._instantiate(name, ticker)
        raise TickerNotRegisteredError(f"{ticker!r} resolves to no archetype (ticker map / tag / score rules)")

    # -- valuation ------------------------------------------------------ #
    def get_valuation(self, ticker: str, data_payload: dict[str, Any],
                      regime_vector: RegimeImpactVector, *, as_of: Optional[date] = None) -> dict[str, Any]:
        """Route ``ticker`` to its archetype and return the standardized summary.
        ``comps`` may be passed in ``data_payload['comps']``. Fail-fast on no route."""
        archetype = self.resolve(ticker, data_payload, as_of=as_of)
        summary = archetype.valuation_summary(
            data_payload, comps=data_payload.get("comps"), regime_vector=regime_vector,
            financials=data_payload.get("financials"))
        summary["as_of"] = as_of.isoformat() if as_of else "latest"
        summary["lifecycle_versions"] = len(self._by_ticker.get(ticker, []))
        return summary

    # -- introspection / correlation foundation ------------------------- #
    def lifecycle_history(self, ticker: str) -> list[dict[str, str]]:
        """Return the archetype timeline for a ticker (oldest first)."""
        versions = self._by_ticker.get(ticker)
        if not versions:
            raise TickerNotRegisteredError(f"{ticker!r} is not registered")
        return [{"effective": v.effective.isoformat() if v.effective else "inception",
                 "archetype": v.archetype.name, "label": v.label} for v in versions]

    def registered_tickers(self) -> list[str]:
        return sorted(self._by_ticker)

    def correlation_groups(self, *, as_of: Optional[date] = None) -> dict[str, list[str]]:
        """Group registered tickers by shared risk-factor tag — the seed for the
        future cross-archetype correlation / sizing layer."""
        groups: dict[str, list[str]] = {}
        for ticker in self._by_ticker:
            for factor in self.resolve(ticker, as_of=as_of).DNA.risk_factor_tags:
                groups.setdefault(factor, []).append(ticker)
        return {k: sorted(v) for k, v in sorted(groups.items())}


# --------------------------------------------------------------------------- #
#  Default router factory (wires the anchor 60/15/15/10 barbell)
# --------------------------------------------------------------------------- #
def build_default_router(config: Optional[dict[str, Any]] = None,
                         config_path: str = "v5_config.json",
                         fx_rates: Optional[dict[str, float]] = None) -> PolymorphicRouter:
    """Build a router pre-loaded with all five archetype classes, tag rules derived
    from ``archetype_routing`` (type -> archetype), and an explicit ticker
    registration for every name in ``portfolio_metadata`` — realizing the anchor
    60/15/15/10 barbell straight from config.

    Routing precedence per ticker: explicit ``portfolio_metadata[ticker].archetype``,
    else the ``archetype_routing`` map, else :data:`ARCHETYPE_BY_TYPE`. An unknown
    type is skipped explicitly (never guessed)."""
    if config is None:
        config = load_config(config_path)
    usd = config.get("usd_to_cad")
    fx = dict(fx_rates) if fx_rates else ({"USD": float(usd)} if usd else None)
    router = PolymorphicRouter(config, fx_rates=fx)
    for name, cls in ARCHETYPE_REGISTRY.items():
        router.register_archetype_class(name, cls)

    routing = {**ARCHETYPE_BY_TYPE, **config.get("archetype_routing", {})}
    for tag, name in routing.items():
        if isinstance(name, str) and name in ARCHETYPE_REGISTRY:        # skips the "_comment" key
            router.register_tag_rule(tag, name)

    for ticker, meta in config.get("portfolio_metadata", {}).items():
        if str(ticker).startswith("_") or not isinstance(meta, dict):
            continue                                   # skip config comments / non-dict entries
        name = meta.get("archetype") or routing.get(str(meta.get("type", "")).lower())
        if name is None:
            continue
        cls = ARCHETYPE_REGISTRY.get(name)
        if cls is None:
            raise ArchetypeConfigError(f"{ticker}: unknown archetype {name!r}")
        router.register_asset(ticker, cls(ticker, config, fx_rates=fx),
                              label=f"{meta.get('type', '?')}/{meta.get('stage', '?')}")
    return router
