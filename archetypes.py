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


def pea_nav_ps(block: dict, ag: float, au: float, nav_label: str,
               shares: float, fx_usdcad: float) -> tuple:
    """Per-share PEA-NAV leg from a company-published after-tax NPV5% sensitivity grid.

    Bilinear interpolation over the (silver, gold) grid; linear edge-slope
    extrapolation outside the grid (flagged in meta — a silver bull tail can
    exceed the company's top published deck, and clamping would silently kill
    the bull's torque). Applies the scenario label's P/NAV multiple,
    permitting/development probability, capex-escalation scalar, and
    construction-financing dilution. Returns (value_per_share_CAD, meta).
    A zero/negative result returns 0.0 (never a negative leg).
    """
    meta: dict = {"nav_label": nav_label, "ag": round(ag, 2), "au": round(au, 2)}
    try:
        grid_ag = [float(x) for x in block["grid_ag"]]
        grid_au = [float(x) for x in block["grid_au"]]
        grid = [[float(v) for v in row] for row in block["npv_usd_m"]]
        assump = block.get(nav_label, {}) or {}
        p_nav = float(assump.get("p_nav", 0.0))
        permit = float(assump.get("permit_prob", 1.0))
        dilution = float(assump.get("dilution", 0.0))
        capex_esc = float(assump.get("capex_esc", 1.0))
    except (KeyError, TypeError, ValueError):
        meta["error"] = "malformed pea_nav block"
        return 0.0, meta

    def _frac(axis: list, x: float) -> tuple:
        n = len(axis)
        if x <= axis[0]:
            i0, f = 0, (x - axis[0]) / (axis[1] - axis[0])
        elif x >= axis[-1]:
            i0, f = n - 2, (x - axis[-2]) / (axis[-1] - axis[-2])
        else:
            i0 = next(i for i in range(n - 1) if axis[i] <= x <= axis[i + 1])
            f = (x - axis[i0]) / (axis[i0 + 1] - axis[i0])
        return i0, f

    try:
        ja, fa = _frac(grid_ag, ag)
        iu, fu = _frac(grid_au, au)
    except (ValueError, ZeroDivisionError, StopIteration):
        meta["error"] = "grid interpolation failed"
        return 0.0, meta
    extrapolated = not (0.0 <= fa <= 1.0 and 0.0 <= fu <= 1.0)
    g = grid
    npv = (g[iu][ja] * (1 - fa) * (1 - fu) + g[iu][ja + 1] * fa * (1 - fu)
           + g[iu + 1][ja] * (1 - fa) * fu + g[iu + 1][ja + 1] * fa * fu)
    meta.update({"npv_usd_m": round(npv, 1), "extrapolated_beyond_company_grid": extrapolated,
                 "p_nav": p_nav, "permit_prob": permit, "dilution": dilution,
                 "capex_esc": capex_esc, "fx_usdcad": fx_usdcad,
                 "source": block.get("_source", "")})
    if not (shares > 0 and npv > 0 and p_nav > 0):
        return 0.0, meta
    nav_cad_m = npv * fx_usdcad * p_nav * permit * capex_esc
    ps = nav_cad_m * 1e6 / (shares * (1.0 + dilution))
    meta["nav_cad_m"] = round(nav_cad_m, 1)
    return max(0.0, ps), meta


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
    "contracted_cyclical": ArchetypeDNA(
        code="VI", name="contracted_cyclical", regime_index=5, regime_tilt_leg="income",
        base_weights={"cost": 0.15, "market": 0.35, "income": 0.50},
        base_confidence={"cost": 0.75, "market": 0.80, "income": 0.75},
        tags=frozenset({"operating", "contracted", "asset_services", "cyclical", "dayrate"}),
        risk_factor_tags=frozenset({"oil_beta", "dayrate_cycle", "operating_leverage", "fleet_supply"})),
    # NOTE: contracted_cyclical.regime_index=5 exceeds the current 5-tuple
    # RegimeImpactVector. AssetArchetype.regime_alpha degrades to 0.0 on a short
    # vector, so the archetype ships regime-neutral until the macro engine emits
    # a 6th coefficient -- the tilt leg is declared now, the alpha arrives later.
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
    def scenario_band(self, data: dict[str, Any], comps: dict[str, Any], legs: dict[str, float],
                      confidences: dict[str, float], penalty: float,
                      regime_mult: float) -> Optional[dict[str, Any]]:
        """Base/bull/bear band + tornado for the commodity_cyclical archetype.

        A producer's torque is ENDOGENOUS — the market leg is spot-linked with
        spot_beta and the income leg capitalizes the margin with the self-funded
        growth term (margin^2) — so the band is a clean silver ±1sigma re-run of
        all three legs. Deliberately no peer-expansion overlay, no PM-cycle
        kicker, no discovery shift: those would double-count leverage the legs
        already price (the Phase 4a lesson). The bull therefore shows operating
        leverage + reinvestment compounding exactly as the legs price them, and
        the bear shows the margin compression symmetrically.

        The tornado isolates the three torque pieces: the silver lever is the full
        up-move WITH growth compounding and catalyst response (the total upside
        the vehicle captures), the self-funded-growth lever is the reinvestment
        engine's slice of the base intrinsic, and the project-catalysts lever is
        the restarts/expansions slice -- both slices additive in the leg, so exact
        through triangulation and the forensic penalty. Returns None when neither the market nor the
        income leg carries confidence (a cost-floor flatline is not a band).
        """
        if confidences.get("market", 0.0) <= 0 and confidences.get("income", 0.0) <= 0:
            return None
        sh = self.config.get("scenarios", {}) or {}
        sigma_mult = float(sh.get("spot_sigma_mult", 1.0))
        macro = data.get("macro") if isinstance(data.get("macro"), dict) else {}
        spot = _num(macro, "spot_ag")
        vol = _num(macro, "silver_vol", default=0.30)
        if not all(_finite(x) and x > 0 for x in (spot, vol)):
            return None
        spot_up = spot * (1.0 + sigma_mult * vol)
        spot_dn = spot * max(0.0, 1.0 - sigma_mult * vol)
        aisc = _num(data, "aisc", default=float("nan"))
        saved_breakdown = self._breakdown

        def _shocked(spot_f: float = 1.0) -> Optional[float]:
            d2 = dict(data)
            m2 = dict(macro)
            m2["spot_ag"] = spot * spot_f
            d2["macro"] = m2
            try:
                self._breakdown = {}
                inc_raw = self.calculate_income_basis(d2, NEUTRAL_REGIME)
                shocked = {
                    "cost": self.calculate_cost_basis(d2),
                    "market": self.calculate_market_basis(d2, comps),
                    # calculate_income_basis self-applies the regime tilt; run it
                    # neutral then re-apply the base run's tilt exactly (the leg
                    # is linear in regime_mult, so this reproduces the base
                    # regime basis at shocked spot with no vector inversion).
                    "income": inc_raw * regime_mult,
                }
            except Exception:
                return None
            finally:
                self._breakdown = saved_breakdown
            # income self-applies the regime tilt inside calculate_income_basis
            # (re-applied exactly above from the base run's multiplier);
            # the DNA tilt leg IS income, so no external tilt here (mirrors
            # valuation_summary: only cost/market tilt legs get the outer mult).
            blend, _ = self.triangulate(shocked, confidences)
            return blend * penalty

        try:
            base_v = _shocked()
            bull_v = _shocked(spot_up / spot)
            bear_v = _shocked(spot_dn / spot)
            if base_v is None or bull_v is None or bear_v is None:
                return None
            silver_up = _shocked(spot_up / spot)
            tornado: dict[str, Any] = {
                "silver": round(silver_up - base_v, 4) if silver_up is not None else None,
            }
            # Self-funded growth slice of the base, in final intrinsic units:
            # the leg is additive in the growth term, so this is exact through
            # the confidence-weighted triangulation and the forensic penalty.
            growth_cad = (saved_breakdown.get("income") or {}).get("growth_value_cad")
            if _finite(growth_cad) and growth_cad > 0:
                _, weights = self.triangulate(legs, confidences)
                tornado["self_funded_growth"] = round(
                    growth_cad * weights.get("income", 0.0) * penalty, 4)
            # Project-catalyst slice of the base, in final intrinsic units (same
            # additive-through-triangulation logic as the growth slice).
            cat_cad = (saved_breakdown.get("income") or {}).get("catalyst_value_cad")
            if _finite(cat_cad) and cat_cad > 0:
                _, weights = self.triangulate(legs, confidences)
                tornado["project_catalysts"] = round(
                    cat_cad * weights.get("income", 0.0) * penalty, 4)
        finally:
            self._breakdown = saved_breakdown
        return {"base": round(base_v, 4), "bull": round(bull_v, 4),
                "bear": round(max(0.0, bear_v), 4), "tornado": tornado,
                "shifts": {"spot_sigma_mult": sigma_mult, "silver_vol": round(vol, 4),
                           "spot_up": round(spot_up, 2), "spot_dn": round(spot_dn, 2),
                           "project_aisc_usd": round(aisc, 2) if _finite(aisc) else None,
                           "bull_margin": round(spot_up - aisc, 2) if _finite(aisc) else None,
                           "bear_margin": round(max(0.0, spot_dn - aisc), 2) if _finite(aisc) else None},
                "method": "commodity_cyclical scenario_band (silver ±1sigma leg re-run; "
                          "torque endogenous via spot_beta market leg + margin^2 self-funded "
                          "growth income leg; no exogenous expansion overlay)"}

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

    def supplementary_lenses(self, data: dict[str, Any], legs: dict[str, float],
                             confidences: dict[str, float], penalty: float,
                             regime_mult: float) -> dict[str, Any]:
        """Optional archetype-specific valuation lenses (informational ONLY).

        Lenses never move the legs, the blend, or the rating -- they sit beside
        the triangulated intrinsic so the operator can compare the model's
        through-cycle math against regime-dependent views (forward share count,
        market-implied multiples). Subclasses override; the default is empty."""
        return {}

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
            "lenses": self.supplementary_lenses(data, legs, confs, penalty, regime_mult),
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

    def _pea_nav(self) -> Optional[dict]:
        """Company-published PEA NPV sensitivity block, per-ticker only.

        A pre-PEA explorer has no economic study, so no block exists and the
        income leg stays 0 by design (the AGA-era shape). A PEA-stage name
        (BRC.V 2026-09-19) carries its NI 43-101 Table 22-5 grid here, and the
        income leg becomes the DCF anchor instead of a second comp multiple."""
        by_ticker = self.config.get("pea_nav_by_ticker") or {}
        hit = by_ticker.get(self.ticker) if isinstance(by_ticker, dict) else None
        return hit if isinstance(hit, dict) and hit else None

    def weights(self) -> dict[str, float]:
        """Per-ticker leg-weight override (BRC.V 2026-09-19): a PEA-stage name's
        central anchor is the published-NAV income leg, so it earns blend weight
        instead of the explorer default income=0. Falls back to DNA weights."""
        by_ticker = self.config.get("leg_weights_by_ticker") or {}
        hit = by_ticker.get(self.ticker) if isinstance(by_ticker, dict) else None
        if isinstance(hit, dict) and hit:
            return {k: float(v) for k, v in hit.items() if not str(k).startswith("_")}
        return super().weights()

    def _income_nav_ps(self, data: dict[str, Any], nav_label: str = "base") -> float:
        """PEA-NAV income leg per share at this payload's macro.

        Gold is not an engine macro field; derive it as spot_ag × gsr (the
        engine's own silver-outperformance gauge) — a constant-GSR pass-through,
        disclosed in the breakdown. Records the grid read into the breakdown
        for the base label only (shocked labels run inside scenario_band)."""
        block = self._pea_nav()
        if not block:
            return 0.0
        shares = self._shares(data)
        macro = data.get("macro") if isinstance(data.get("macro"), dict) else {}
        spot = _num(macro, "spot_ag")
        gsr = _num(macro, "gsr", default=70.0)
        if not (_finite(spot) and spot > 0 and _finite(gsr) and gsr > 0 and shares > 0):
            return 0.0
        fx = _num(block, "fx_usdcad", default=1.39)
        ps, meta = pea_nav_ps(block, spot, spot * gsr, nav_label, shares, fx)
        meta["gsr_used"] = round(gsr, 2)
        if nav_label == "base":
            self._breakdown["income"] = {"method": "PEA after-tax NPV5% grid x P/NAV "
                                                  "(company-published sensitivity)",
                                         "value_cad": round(ps, 4), **meta}
        return self.normalize_fx(ps, "CAD")

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
        v_mkt_ex_scale = 1.0
        nav_block = self._pea_nav()
        if nav_block:
            # The PEA-NAV income leg DCFs the mine-plan ounces — exclude them
            # from the peer-multiple leg so the same ounces are never priced
            # twice (multiple + NAV). The exploration sub-leg is untouched:
            # future ounces are not in the resource at all. With a single
            # project bucket this linear scale is exact (everything is linear
            # in ounces); the residual (incl. the NW Step Out ounces the PEA
            # excludes) keeps the peer multiple.
            total_raw = sum(float(oz) for oz in buckets.values())
            mine_plan = _num(nav_block, "mine_plan_oz_ageq", default=0.0)
            if total_raw > 0 and 0.0 < mine_plan < total_raw:
                v_mkt_ex_scale = (total_raw - mine_plan) / total_raw
        v_mkt_defined = v_mkt * v_mkt_ex_scale * conservatism / shares
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
                                     "peer_ev_oz": peer_ev, "option_premium": opt, "tq_by_project": tq_by_project,
                                     "pea_mine_plan_excluded_scale": round(v_mkt_ex_scale, 4)}
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

        The cost leg (REP floor) is scenario-invariant. For a pre-PEA explorer the
        income leg is 0 by design and only the market leg is re-shocked; for a
        PEA-stage name (BRC.V 2026-09-19) the income leg is the company-published
        after-tax NPV5% sensitivity grid read at shocked (silver, gold=Ag×GSR)
        prices, with scenario-specific P/NAV, permitting probability, dilution,
        and capex-escalation — the DCF anchor the market actually trades. The
        peer-multiple market leg excludes the PEA mine-plan ounces so no ounce
        is priced twice. The bull therefore prices the project's own
        operating-margin convexity, funded-drill exploration growth — for BRC.V,
        the 17,100m Tonopah program at a conservative 1.0 oz/m — and P/NAV
        re-rating toward the construction decision, never a generic multiple.
        Returns None when the market leg carries no confidence.
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
                     ry_d: float = 0.0, p_d: float = 0.0,
                     nav_label: str = "base") -> Optional[float]:
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
            try:
                inc = float(self._income_nav_ps(d2, nav_label))
            except Exception:
                inc = 0.0
            blend, _ = self.triangulate({"cost": legs.get("cost", 0.0), "market": mkt,
                                         "income": inc}, confidences)
            return blend * penalty

        try:
            self._breakdown = {}
            base_v = _shocked()
            bull_v = _shocked(spot_f=spot_up / spot, peer_f=bull_peer_f,
                              ry_d=-ry_bps / 100.0, p_d=dp, nav_label="bull")
            bear_v = _shocked(spot_f=spot_dn / spot, peer_f=bear_peer_f,
                              ry_d=ry_bps / 100.0, p_d=-dp, nav_label="bear")
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
        # Without a published economic study a pre-revenue explorer has no
        # recurring cash flow; the legitimate optionality lives in the market
        # leg (alpha_option tilts it there). WITH a PEA (BRC.V 2026-09-19) the
        # income leg becomes the company's own after-tax NPV5% sensitivity grid
        # read at live prices — the DCF anchor, not a second comp multiple.
        if not self._pea_nav():
            self._breakdown["income"] = {"method": "none (pre-revenue explorer)", "value_cad": 0.0}
            return 0.0
        return self._income_nav_ps(data, "base")

    def assess_confidence(self, leg: str, value: float, data: dict[str, Any], comps: dict[str, Any]) -> float:
        if leg == "income":
            # PEA-NAV leg: company-published, NI 43-101 — real signal, but a PEA
            # carries ±35-40% accuracy and the MRE is inferred-heavy, so below
            # the cost leg's treasury-grade confidence.
            return 0.70 if self._pea_nav() and _finite(value) and value > 0 else 0.0
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

    def _self_funded_growth(self) -> Optional[dict[str, Any]]:
        """Self-funded explorer/growth torque for producers.

        A producer that funds exploration from operating cash flow grows reserves at
        ZERO dilution (not equity-funded like a junior's drill program), so the growth
        accrues fully per share. Gated on sourced per-ticker config; None -> the income
        leg stays a static margin capitalization (inert, no fabrication).

        Economics (consistent with the base leg's implied reserve value): the base leg
        capitalizes the annual margin stream prod x m at Y years, which implies a reserve
        life ~Y and hence a per-ounce reserve value of ~m (one margin, realized when mined).
          annual reinvestment $  = r x prod x m
          risked new oz / yr    = r x prod x m x p / c
          growth value          = risked new oz x m = r x prod x m^2 x p / c
        Expressed as an uplift on the capitalization years: Y_eff = Y + (r x p / c) x m.
        The growth term scales as m^2, so torque itself is convex in the margin:
          torque = d/dm [prod x m x (Y + k x m) / S] = prod x (Y + 2 x k x m) / S,
        with k = r x p / c. At higher silver the reinvestment engine adds more ounces
        AND each ounce is worth more margin -- that compounding is the torque aspect.
        """
        block = self.config.get("self_funded_growth", {})
        if not isinstance(block, dict):
            return None
        g = block.get(self.ticker)
        if not isinstance(g, dict):
            return None
        try:
            r = float(g["reinvestment_rate"])
            c = float(g["discovery_cost_per_oz"])
            p = float(g["p_discovery"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (0.0 < r < 1.0 and c > 0.0 and 0.0 < p <= 1.0):
            return None
        return {"reinvestment_rate": r, "discovery_cost_per_oz": c, "p_discovery": p,
                "_source": str(g.get("_source", ""))}

    def _project_catalysts(self) -> list[dict[str, Any]]:
        """Project-catalyst bucket: restarts / expansions / new mines.

        A catalyst is a STEP-CHANGE in the production profile -- a new or
        restarted mine coming online at a future date -- which is economically
        distinct from the reserve-replacement engine (``_self_funded_growth``),
        which extends mine LIFE. Conflating them understates restarts (they add
        a whole mine's margin, not 0.2 years of it) and overstates infill
        drilling (it replaces ounces, it doesn't open mines).

        Transferable: per-ticker list under ``config["project_catalysts"][ticker]``;
        all code is archetype-level and frame-agnostic. Monetary inputs are in the
        name's native currency (same convention as ``aisc``); ounces and AISC are
        in FRAME-EQUIVALENT ounces (AgEq for silver-framed names) -- the operator
        does any cross-commodity conversion (e.g. GSR) when sourcing, so the
        engine carries no gold-price assumption. Consequence, documented: in
        shocked scenario runs the catalyst margin moves with the frame spot,
        i.e. AgEq framing implies a fixed cross-commodity ratio (no live gold
        feed exists to do better).

        Valuation (consistent with the income leg it augments -- a straight margin
        capitalization, no discount rate): each catalyst contributes
          p_execution x max(0, incr_oz x max(0, spot - catalyst_aisc)
                            x max(0, Y - delay_years) - capex_remaining),
        floored at zero (real-option treatment: an uneconomic restart is deferred,
        not built at a loss). p_execution absorbs timing/ramp/capex-overrun risk;
        no separate ramp profile (false precision at estimated inputs). The
        catalyst shares the income leg's capitalization horizon Y -- it is
        incremental production margin over the same window the market capitalizes.

        Malformed entries are skipped; a missing/empty list is a no-op (inert).
        """
        raw = (self.config.get("project_catalysts", {}) or {}).get(self.ticker)
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                continue
            oz = _num(e, "incremental_oz_per_yr", default=float("nan"))
            aisc = _num(e, "catalyst_aisc_per_oz", default=float("nan"))
            capex = _num(e, "capex_remaining", default=float("nan"))
            delay = _num(e, "delay_years", default=float("nan"))
            p = _num(e, "p_execution", default=float("nan"))
            if not (_finite(oz) and oz > 0 and _finite(aisc) and aisc >= 0
                    and _finite(capex) and capex >= 0 and _finite(delay) and delay >= 0
                    and _finite(p) and 0.0 < p <= 1.0):
                continue                      # degrade inert: skip, never fabricate
            out.append({"name": str(e.get("name", f"catalyst-{i}")), "oz": oz,
                        "aisc": aisc, "capex": capex, "delay": delay, "p": p,
                        "_source": str(e.get("_source", "")),
                        "_status": str(e.get("_status", ""))})
        return out

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        shares = _num(data, "shares_out", default=float("nan"))
        prod, aisc = _num(data, "annual_production_oz", default=float("nan")), _num(data, "aisc", default=float("nan"))
        p = self._ballast(data)
        spot_now = self._spot_now(data, p["commodity"])
        if not (_finite(prod) and _finite(aisc) and shares > 0 and spot_now > 0):
            raise SparseDataError("need annual_production_oz, aisc, shares, spot")
        years = float(self._tuning("margin_capitalization_years", 6.0))
        # Per-ticker override (operator-set reserve-life horizon; e.g. AG 10.0):
        # archetype_factory.commodity_cyclical.margin_capitalization_years_by_ticker.<TICKER>
        ticker_years = self._factory_cfg("commodity_cyclical", "margin_capitalization_years_by_ticker",
                                         self.ticker, default=None)
        if ticker_years is not None:
            years = float(ticker_years)
        regime_mult = self.regime_multiplier(regime_vector)              # alpha_cyclical tilt (once, here)
        margin = max(0.0, spot_now - aisc)
        ccy = self.native_currency(data)
        growth = self._self_funded_growth()
        k = growth_uplift_years = 0.0
        if growth is not None and margin > 0.0:
            # risked new ounces per dollar of reinvested margin, times the margin itself
            k = growth["reinvestment_rate"] * growth["p_discovery"] / growth["discovery_cost_per_oz"]
            growth_uplift_years = k * margin
        eff_years = years + growth_uplift_years
        # Project catalysts: step-changes in the production profile (restarts /
        # expansions). Incremental margin over the shared capitalization horizon,
        # risked by p_execution, floored at zero (real-option treatment).
        catalysts = self._project_catalysts()
        cat_total_native = 0.0
        cat_torque_oz = 0.0   # risked oz/yr actually contributing (floor-aware)
        cat_rows: list[dict[str, Any]] = []
        for c in catalysts:
            cat_margin = max(0.0, spot_now - c["aisc"])
            cat_horizon = max(0.0, years - c["delay"])
            gross = c["oz"] * cat_margin * cat_horizon - c["capex"]
            if gross > 0:
                net = gross * c["p"]
                cat_torque_oz += c["oz"] * cat_horizon * c["p"]
            else:
                net = 0.0     # floored: no value, no torque
            cat_total_native += net
            cat_rows.append({"name": c["name"],
                             "annual_margin_native": round(c["oz"] * cat_margin, 1),
                             "horizon_years": round(cat_horizon, 2),
                             "capex_native": c["capex"], "p_execution": c["p"],
                             "value_native": round(net, 1),
                             "_status": c["_status"]})
        v_native = ((prod * margin * eff_years + cat_total_native) / shares) * regime_mult
        v = self.normalize_fx(v_native, ccy)
        v_growth = self.normalize_fx((prod * margin * growth_uplift_years / shares) * regime_mult, ccy)
        v_catalyst = self.normalize_fx((cat_total_native / shares) * regime_mult, ccy)
        # Torque: income-leg $/share per $1/oz silver move (dm/dspot = 1; AISC cost
        # pass-through assumed 0 -- conservative, surfaced as an assumption).
        # Convex in the margin when self-funded growth is active (the 2*k*m term).
        # Catalysts add linear torque over their horizon (AgEq framing: fixed GSR);
        # floor-aware: a floored catalyst contributes no torque.
        torque_native = (prod * (years + 2.0 * growth_uplift_years)
                         + cat_torque_oz) / shares * regime_mult
        torque = self.normalize_fx(torque_native, ccy)
        elasticity = (torque * spot_now / v) if v > 0 else 0.0
        meta: dict[str, Any] = {"method": "spot-margin capitalization" + (" + self-funded growth" if growth else "") + (" + project catalysts" if cat_rows else ""),
                                "margin": round(margin, 4), "years": years,
                                "torque_ps_per_dollar_ag": round(torque, 4),
                                "torque_assumption": "dm/dspot=1 (no AISC cost pass-through)",
                                "torque_elasticity": round(elasticity, 4),
                                "regime_multiplier": round(regime_mult, 4), "value_cad": round(v, 4)}
        if growth is not None:
            meta.update({"growth_uplift_years": round(growth_uplift_years, 4),
                         "growth_value_cad": round(v_growth, 4),
                         "growth_inputs": {"reinvestment_rate": growth["reinvestment_rate"],
                                           "discovery_cost_per_oz": growth["discovery_cost_per_oz"],
                                           "p_discovery": growth["p_discovery"],
                                           "_source": growth["_source"]}})
        if cat_rows:
            meta.update({"catalyst_value_cad": round(v_catalyst, 4),
                         "catalysts": cat_rows})
        self._breakdown["income"] = meta
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


#  VI.  Contracted Cyclical — contracted day-rate asset services (TDW, DHT)
# =========================================================================== #
class ContractedCyclicalArchetype(AssetArchetype):
    """Contracted-asset services cyclicals: OSV owners, tanker owners. The cash
    flow is a contracted DAY-RATE margin on a physical fleet — not a spot
    commodity margin — so the commodity_cyclical spot-margin machinery does not
    apply (forcing day-rates through a spot formula is archetype-generic
    sloppiness this class exists to prevent).

    Cost   — fleet replacement-cost floor: (cost_units x value_per_unit -
             net_debt)/shares; book value/share fallback (flagged in breakdown).
             cost_units defaults to active_units (pro-forma hull count may
             exceed the rate-machinery fleet after an acquisition).
    Market — mid-cycle EV/EBITDA -> equity/share (P/Book fallback).
    Income — contracted backlog + repricing torque: annual cash = active_units x
             365 x utilization x (blended_rate - cash_opex/day) + acquired
             annual cash (e.g. an acquired fleet's guided cash stream, held
             flat), less cash G&A and maintenance capex, DISCOUNTED at the
             configured discount_rate over cap_years; torque quoted per $1k/day
             (industry convention) on the same discounted path.
             Regime tilt leg (alpha_contracted, currently neutral -- see DNA note).

    The repricing-rate path may carry a cycle_decay block: beyond the last
    guided trajectory year the rate fades exponentially toward a terminal
    mid-cycle rate (half-life in years) instead of holding flat forever.
    All three post-2026-09-20 features (discount_rate, cycle_decay,
    acquired_annual_cash_native, cost_units) are per-ticker CONFIG -- zero
    ticker-specific logic; each degrades inert when unsourced, preserving the
    legacy undiscounted flat-tail behavior.

    Inputs are per-ticker and frame-agnostic: day-rates and opex in the name's
    native currency; units are physical assets (vessels), never ounces. No
    ticker-specific branches. Missing inputs raise SparseDataError per leg --
    the engine degrades leg-by-leg, never fabricates.
    """

    DNA = ARCHETYPE_DNA["contracted_cyclical"]

    def _ccfg(self) -> dict[str, Any]:
        block = self.config.get("contracted_cyclical", {})
        if not isinstance(block, dict):
            return {}
        g = block.get(self.ticker)
        return g if isinstance(g, dict) else {}

    def _input(self, data: dict[str, Any], key: str, default: float = float("nan")) -> float:
        """Live data first, sourced per-ticker config as fallback. Both are
        operator-supplied; neither is estimated by the engine."""
        if _present(data, key):
            return _num(data, key, default=default)
        return _num(self._ccfg(), key, default=default)

    def _cap_years(self) -> float:
        return float(self._ccfg().get("cap_years",
                                     self._tuning("contracted_cap_years", 5.0)))

    def _discount_rate(self) -> float:
        """Hurdle rate for discounting the income-leg cash path. 0.0 (default)
        preserves the legacy straight-capitalization behavior."""
        r = _num(self._ccfg(), "discount_rate", default=0.0)
        return r if (_finite(r) and r >= 0.0) else 0.0

    def _cycle_decay(self) -> Optional[dict[str, Any]]:
        """Exponential fade of the repricing rate beyond sourced guidance.

        Config block ``cycle_decay``: {terminal_rate, half_life_years,
        start_years_ahead (default = last trajectory years_ahead), label,
        source, basis}. For t > start: rate(t) = terminal + (guided_at_start -
        terminal) x 0.5^((t - start)/half_life). Malformed/absent -> None
        (legacy flat tail)."""
        raw = self._ccfg().get("cycle_decay")
        if not isinstance(raw, dict):
            return None
        try:
            terminal = float(raw.get("terminal_rate"))
            hl = float(raw.get("half_life_years"))
        except (TypeError, ValueError):
            return None
        if not (_finite(terminal) and terminal >= 0 and _finite(hl) and hl > 0):
            return None
        traj = self._rate_trajectory()
        last_guided = max([p["years_ahead"] for p in traj], default=0)
        try:
            start = int(raw.get("start_years_ahead", last_guided))
        except (TypeError, ValueError):
            start = last_guided
        start = max(0, start)
        return {"terminal_rate": terminal, "half_life_years": hl,
                "start_years_ahead": start,
                "label": str(raw.get("label", "")),
                "source": str(raw.get("source", "")),
                "basis": str(raw.get("basis", ""))}

    def _acquired_cash(self) -> tuple[float, dict[str, str]]:
        """Annual cash stream from an acquired fleet (native currency), e.g. a
        guided gross-profit figure whose vessel-level dayrates are unsourced.
        Added to each cap-horizon year's cash before discounting; held flat
        (backlog rollover repricing unsourced). 0.0 default = absent."""
        v = _num(self._ccfg(), "acquired_annual_cash_native", default=0.0)
        if not (_finite(v) and v > 0):
            return 0.0, {}
        note = {"label": str(self._ccfg().get("acquired_annual_cash_label", "")),
                "source": str(self._ccfg().get("acquired_annual_cash_source", "")),
                "basis": str(self._ccfg().get("acquired_annual_cash_basis", ""))}
        return v, note

    def _cost_units(self, data: dict[str, Any]) -> float:
        """Hull count for the replacement-cost floor. Defaults to active_units;
        an acquirer may set cost_units to the pro-forma fleet while the
        rate-machinery fleet stays on sourced dayrate inputs."""
        cu = _num(self._ccfg(), "cost_units", default=float("nan"))
        if _finite(cu) and cu > 0:
            return cu
        return self._input(data, "active_units")

    def calculate_cost_basis(self, data: dict[str, Any]) -> float:
        ccy, shares = self.native_currency(data), self._input(data, "shares_out")
        units = self._cost_units(data)
        value_per_unit = self._input(data, "fleet_value_per_unit")
        net_debt = self._input(data, "net_debt", 0.0)
        if _finite(units) and units > 0 and _finite(value_per_unit) and value_per_unit > 0 and shares > 0:
            v = self.normalize_fx((units * value_per_unit - net_debt) / shares, ccy)
            self._breakdown["cost"] = {"method": "fleet replacement-cost floor",
                                       "active_units": units,
                                       "value_per_unit_native": round(value_per_unit, 1),
                                       "value_cad": round(v, 4)}
            return max(0.0, v)
        book_ps = self._input(data, "book_value_per_share")
        if _finite(book_ps):
            v = self.normalize_fx(book_ps, ccy)
            self._breakdown["cost"] = {"method": "book value / share (fleet value unsourced -- floor proxy)",
                                       "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need active_units+fleet_value_per_unit+shares or book_value_per_share")

    def _derived_mid_cycle_ebitda(self, data: dict[str, Any]) -> tuple[float, str]:
        """Derive mid-cycle EBITDA from the contracted book when unsourced.

        For a contracted fleet the term book IS observable through-cycle
        revenue: when contract coverage >= 50% the contracted rate anchors the
        mid-cycle rate (labeled as such); otherwise an explicit mid_cycle_rate
        input is required and the leg degrades. Returns (ebitda, basis_note).
        """
        units = self._input(data, "active_units")
        util = self._input(data, "utilization")
        opex = self._input(data, "cash_opex_per_day")
        coverage = self._input(data, "contract_coverage", default=0.0)
        mc_rate = self._input(data, "mid_cycle_rate")
        note = ""
        if not _finite(mc_rate):
            c_rate = self._input(data, "contracted_rate")
            if (_finite(coverage) and coverage >= 0.5 and _finite(c_rate) and c_rate > 0):
                mc_rate = c_rate
                note = (f"contracted-book anchor (coverage {coverage:.0%} >= 50%; "
                        "term book treated as through-cycle revenue)")
            else:
                return float("nan"), "unsourced (coverage < 50%, no mid_cycle_rate)"
        else:
            note = "explicit mid_cycle_rate input"
        if not all(_finite(x) for x in (units, util, opex)) or not (units > 0 and 0.0 < util <= 1.0):
            return float("nan"), "unsourced (fleet/opex inputs missing)"
        ebitda = units * 365.0 * util * max(0.0, mc_rate - opex)
        return ebitda, f"derived: {note}; mid_cycle_rate={mc_rate:,.0f}/day"

    def calculate_market_basis(self, data: dict[str, Any], comps: dict[str, Any]) -> float:
        ccy, shares = self.native_currency(data), self._input(data, "shares_out")
        mid_ebitda = self._input(data, "mid_cycle_ebitda")
        ebitda_basis = "explicit mid_cycle_ebitda input"
        if not _finite(mid_ebitda):
            mid_ebitda, ebitda_basis = self._derived_mid_cycle_ebitda(data)
        ev_mult = self._input(data, "ev_ebitda_mid")
        mult_basis = "mid-cycle multiple input"
        if not _finite(ev_mult):
            ev_mult = self._input(data, "ev_ebitda")
            mult_basis = "forward ev_ebitda on mid-cycle EBITDA (method mix -- flagged)"
        if not _finite(ev_mult):
            ev_mult = _num(comps, "ev_ebitda", default=float("nan"))
            mult_basis = "comp ev_ebitda (fallback)"
        net_debt = self._input(data, "net_debt", 0.0)
        if _finite(mid_ebitda) and mid_ebitda > 0 and _finite(ev_mult) and ev_mult > 0 and shares > 0:
            v = self.normalize_fx((mid_ebitda * ev_mult - net_debt) / shares, ccy)
            self._breakdown["market"] = {"method": "mid-cycle EV/EBITDA",
                                         "mid_cycle_ebitda_native": round(mid_ebitda, 1),
                                         "ebitda_basis": ebitda_basis,
                                         "ev_ebitda": round(ev_mult, 2),
                                         "multiple_basis": mult_basis,
                                         "value_cad": round(v, 4)}
            return max(0.0, v)
        pb = _num(comps, "p_book", default=float("nan"))
        book_ps = self._input(data, "book_value_per_share")
        if _finite(pb) and _finite(book_ps):
            v = self.normalize_fx(book_ps * pb, ccy)
            self._breakdown["market"] = {"method": "P/Book comp (fallback)", "p_book": pb,
                                         "value_cad": round(v, 4)}
            return max(0.0, v)
        raise SparseDataError("need mid_cycle_ebitda+ev_ebitda or p_book+book value")

    # ------------------------------------------------------------------ #
    #  High-demand upgrade (2026-09-19): sourced rate trajectory + capital-
    #  return lens + regime-implied lens. All three are per-ticker CONFIG --
    #  zero ticker-specific logic; each degrades inert when unsourced.
    # ------------------------------------------------------------------ #
    def _rate_trajectory(self) -> list[dict[str, Any]]:
        """Sourced forward day-rate deltas, e.g. [{"years_ahead": 1,
        "delta_per_day": 3500, "label": ..., "source": ..., "basis": "R"}].

        Deltas are CUMULATIVE $/day steps on the repricing (leading-edge) rate,
        applied from ``years_ahead`` onward. Malformed entries are skipped,
        never fabricated."""
        raw = self._ccfg().get("rate_trajectory") or []
        if not isinstance(raw, list):
            return []
        pts: list[dict[str, Any]] = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            try:
                ya = int(p.get("years_ahead"))
                d = float(p.get("delta_per_day"))
            except (TypeError, ValueError):
                continue
            if ya < 0 or not _finite(d):
                continue
            pts.append({"years_ahead": ya, "delta_per_day": d,
                        "label": str(p.get("label", "")),
                        "source": str(p.get("source", "")),
                        "basis": str(p.get("basis", ""))})
        pts.sort(key=lambda q: q["years_ahead"])
        return pts

    def _rate_path(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Yearly repricing-rate path over the cap horizon.

        Year 0 prices at the live leading-edge rate; each trajectory delta steps
        the path up from its ``years_ahead`` onward (cumulative). Beyond the last
        guided point the rate is HELD FLAT -- no extrapolation past sourced
        guidance, no cliff back to spot -- unless a ``cycle_decay`` block is
        configured, in which case the rate fades exponentially toward the
        terminal rate from ``start_years_ahead`` onward. A fractional final
        cap-year gets a pro-rata weight. Returns [{year, weight,
        repricing_rate}]."""
        le = self._input(data, "leading_edge_rate")
        years = self._cap_years()
        traj = self._rate_trajectory()
        decay = self._cycle_decay()
        n_full = int(years)
        frac = years - n_full
        path: list[dict[str, Any]] = []
        steps = n_full + (1 if frac > 1e-9 else 0)
        guided_at = None
        if decay:
            st = decay["start_years_ahead"]
            guided_at = le + sum(p["delta_per_day"] for p in traj
                                 if p["years_ahead"] <= st)
        for t in range(steps):
            w = frac if (t == n_full and frac > 1e-9) else 1.0
            rate = le + sum(p["delta_per_day"] for p in traj if p["years_ahead"] <= t)
            if decay and t > decay["start_years_ahead"] and guided_at is not None:
                rate = (decay["terminal_rate"] +
                        (guided_at - decay["terminal_rate"]) *
                        0.5 ** ((t - decay["start_years_ahead"]) /
                                decay["half_life_years"]))
            path.append({"year": t, "weight": round(w, 4),
                         "repricing_rate": round(rate, 1)})
        return path

    def _annual_cash(self, data: dict[str, Any],
                     repricing_rate: Optional[float] = None) -> tuple[float, dict[str, Any]]:
        """Annual contracted + repricing cash flow (native currency) and its parts.

        ``repricing_rate`` overrides the live leading-edge rate for the open-book
        slice -- the rate-trajectory path engine. ``None`` preserves the legacy
        flat leading-edge behavior."""
        units = self._input(data, "active_units")
        util = self._input(data, "utilization")
        opex = self._input(data, "cash_opex_per_day")
        c_rate = self._input(data, "contracted_rate")
        le_rate = self._input(data, "leading_edge_rate")
        coverage = self._input(data, "contract_coverage", default=0.0)
        r_rate = le_rate if repricing_rate is None else repricing_rate
        if not all(_finite(x) for x in (units, util, opex, c_rate, le_rate)):
            raise SparseDataError("need active_units, utilization, cash_opex_per_day, "
                                  "contracted_rate, leading_edge_rate")
        if not (_finite(r_rate) and r_rate >= 0):
            raise SparseDataError("repricing_rate out of range")
        if not (units > 0 and 0.0 < util <= 1.0 and 0.0 <= coverage <= 1.0):
            raise SparseDataError("active_units/utilization/contract_coverage out of range")
        m_contracted = max(0.0, c_rate - opex)
        m_repricing = max(0.0, r_rate - opex)
        vessel_days = units * 365.0 * util
        cash_contracted = vessel_days * coverage * m_contracted
        cash_repricing = vessel_days * (1.0 - coverage) * m_repricing
        blended_rate = coverage * c_rate + (1.0 - coverage) * r_rate
        # Corporate cash costs: vessel-gross cash overstates true FCF. Deduct
        # cash G&A and maintenance capex (dry-dock/surveys) when supplied --
        # both optional, default 0 (old vessel-gross behavior), native currency.
        gna = self._input(data, "annual_gna", default=0.0)
        gna = gna if _finite(gna) and gna > 0 else 0.0
        maint = self._input(data, "annual_maint_capex", default=0.0)
        maint = maint if _finite(maint) and maint > 0 else 0.0
        # Acquired-fleet cash stream (e.g. WSUT guided gross profit): vessel-level
        # dayrates unsourced, so it enters as a flat annual block beside the
        # dayrate machinery, before corporate deductions, each cap-horizon year.
        acq, acq_note = self._acquired_cash()
        annual_cash = cash_contracted + cash_repricing + acq - gna - maint
        parts = {
            "vessel_days": round(vessel_days, 1),
            "contracted_cash_native": round(cash_contracted, 1),
            "repricing_cash_native": round(cash_repricing, 1),
            "acquired_cash_native": round(acq, 1),
            "margin_contracted_day": round(m_contracted, 1),
            "margin_repricing_day": round(m_repricing, 1),
            "repricing_rate_day": round(r_rate, 1),
            "blended_rate_day": round(blended_rate, 1),
            "contract_coverage": round(coverage, 4),
            "annual_gna_native": round(gna, 1),
            "annual_maint_capex_native": round(maint, 1),
            "cash_basis": ("vessel-gross less cash G&A + maint capex" if (gna or maint)
                           else "vessel-gross (no corporate deductions supplied)"),
        }
        if acq_note.get("label") or acq_note.get("source"):
            parts["acquired_cash_note"] = ("held flat over cap horizon -- backlog "
                                           "rollover repricing unsourced")
            parts["acquired_cash_provenance"] = acq_note
        # Rate provenance: when the scheduled rate-hunt's overlay supplied the day-rates
        # (data/_dayrate_meta from engine._apply_dayrate_overlay), record which print
        # priced this leg so a stale or odd rate is traceable, never silent.
        drm = data.get("_dayrate_meta")
        if isinstance(drm, dict):
            parts["rate_asof"] = drm.get("asof")
            parts["rate_source"] = drm.get("source")
            parts["rate_stale_days"] = drm.get("stale_days")
            if drm.get("stale"):
                parts["rate_note"] = "STALE (>21d) — rate-hunt refresh overdue"
        return annual_cash, parts

    def calculate_income_basis(self, data: dict[str, Any], regime_vector: RegimeImpactVector) -> float:
        shares = self._input(data, "shares_out")
        if not (shares > 0):
            raise SparseDataError("need shares_out")
        annual_cash_y0, parts = self._annual_cash(data)   # validates inputs; year-0 parts
        years = self._cap_years()
        path = self._rate_path(data)
        traj = self._rate_trajectory()
        decay = self._cycle_decay()
        r = self._discount_rate()
        # Integrate DISCOUNTED yearly cash over the cap horizon along the rate
        # path. With no trajectory the path is flat at the leading edge; with
        # no discount_rate (0.0) this collapses to the legacy straight
        # capitalization. End-of-year discounting convention, labeled.
        year_rows: list[dict[str, Any]] = []
        total_cash = 0.0
        for row in path:
            cash_t, _ = self._annual_cash(data, repricing_rate=row["repricing_rate"])
            w = row["weight"]
            df = 1.0 / (1.0 + r) ** row["year"] if r > 0 else 1.0
            pv = cash_t * w * df
            total_cash += pv
            year_rows.append({"year": row["year"], "weight": w,
                              "repricing_rate_day": row["repricing_rate"],
                              "annual_cash_native": round(cash_t * w, 1),
                              "discount_factor": round(df, 4),
                              "pv_cash_native": round(pv, 1)})
        flat_cash = sum(annual_cash_y0 * row["weight"] *
                        (1.0 / (1.0 + r) ** row["year"] if r > 0 else 1.0)
                        for row in path)
        regime_mult = self.regime_multiplier(regime_vector)              # alpha_contracted tilt (once, here)
        ccy = self.native_currency(data)
        v_native = total_cash / shares * regime_mult
        v = self.normalize_fx(v_native, ccy)
        # Torque: $/share per $1k/day fleetwide rate move (industry convention),
        # on the same discounted path as the leg (r=0 -> legacy undiscounted).
        # Over the cap horizon the whole active fleet reprices (ultra-short
        # duration thesis); contract coverage only delays capture, it does not
        # change the fleetwide sensitivity -- surfaced as an assumption. The
        # acquired-cash stream is rate-insensitive and excluded from torque.
        units = self._input(data, "active_units")
        util = self._input(data, "utilization")
        disc_years = sum(row["weight"] *
                         (1.0 / (1.0 + r) ** row["year"] if r > 0 else 1.0)
                         for row in path)
        torque_1k_native = units * 365.0 * util * 1000.0 * disc_years / shares * regime_mult
        torque_1k = self.normalize_fx(torque_1k_native, ccy)
        elasticity = (torque_1k / 1000.0 * parts["blended_rate_day"] / v) if v > 0 else 0.0
        uplift_pct = ((total_cash / flat_cash - 1.0) * 100.0) if flat_cash > 0 else 0.0
        decay_info: dict[str, Any] = {"applied": bool(decay)}
        if decay:
            decay_info.update({
                "terminal_rate_day": decay["terminal_rate"],
                "half_life_years": decay["half_life_years"],
                "start_years_ahead": decay["start_years_ahead"],
                "label": decay["label"], "source": decay["source"],
                "basis": decay["basis"],
                "path_rates_day": [row["repricing_rate_day"] for row in year_rows]})
        self._breakdown["income"] = {
            "method": ("contracted backlog + rate-trajectory path capitalization"
                       if traj else
                       "contracted backlog + repricing torque capitalization"),
            **parts,
            "cap_years": years,
            "discount_rate": r,
            "discount_note": (f"end-of-year discounting at {r:.1%} over the cap horizon"
                              if r > 0 else
                              "no discount_rate configured -- straight capitalization (legacy)"),
            "cycle_decay": decay_info,
            "rate_path": year_rows,
            "rate_trajectory": {
                "applied": bool(traj),
                "points": [{"years_ahead": p["years_ahead"],
                            "delta_per_day": p["delta_per_day"],
                            "label": p["label"], "source": p["source"],
                            "basis": p["basis"]} for p in traj],
                "beyond_guidance": ("exponential fade toward terminal rate (cycle_decay)"
                                    if decay else
                                    "held flat at last guided rate -- no extrapolation "
                                    "beyond sourced guidance" if traj
                                    else "n/a (flat leading-edge path)"),
                "contracted_book_treatment": ("held at contracted_rate -- backlog roll-off "
                                              "schedule unsourced (conservative)"),
                "path_cash_total_native": round(total_cash, 1),
                "flat_cash_total_native": round(flat_cash, 1),
                "trajectory_uplift_pct": round(uplift_pct, 2),
            },
            "torque_ps_per_1k_day": round(torque_1k, 4),
            "torque_assumption": "full-fleet repricing over cap horizon (coverage = timing, not sensitivity)",
            "torque_elasticity": round(elasticity, 4),
            "regime_multiplier": round(regime_mult, 4),
            "value_cad": round(v, 4)}
        return max(0.0, v)

    def _forward_shares(self, data: dict[str, Any]) -> tuple[Optional[float], dict[str, Any]]:
        """Project the share count over the cap horizon under the configured
        capital-return policy.

        Buyback: ``authorization`` (native) funds retirements at the assumed
        repurchase price; without an explicit ``annual_pace`` the authorization
        is deployed evenly over the cap horizon (labeled [A]). Dividend/none:
        the count is unchanged. Returns (forward_shares | None, note dict) --
        None degrades the lens, never the legs."""
        cr = self._ccfg().get("capital_return") or {}
        if not isinstance(cr, dict):
            return None, {"status": "degraded", "reason": "capital_return not a dict"}
        policy = str(cr.get("policy", "none")).lower()
        shares = self._input(data, "shares_out")
        base = {"policy": policy, "label": str(cr.get("label", "")),
                "source": str(cr.get("source", ""))}
        if policy == "buyback":
            auth = _num(cr, "authorization", default=float("nan"))
            deployed = _num(cr, "deployed_to_date", default=0.0)
            deployed = deployed if _finite(deployed) and deployed > 0 else 0.0
            if not (_finite(auth) and auth > 0):
                return None, {**base, "status": "degraded",
                              "reason": "buyback policy without an authorization amount"}
            remaining = max(0.0, auth - deployed)
            if remaining <= 0:
                return shares, {**base, "note": "authorization fully deployed -- count unchanged"}
            years = self._cap_years()
            pace = _num(cr, "annual_pace", default=float("nan"))
            pace_note = ""
            if not (_finite(pace) and pace > 0):
                pace = remaining / years if years > 0 else remaining
                pace_note = (f"[A] no annual_pace supplied -- authorization deployed evenly "
                             f"over the {years:g}yr cap horizon")
            deploy = min(remaining, pace * years)
            basis = str(cr.get("price_basis", "market")).lower()
            px = float("nan")
            px_note = ""
            if basis == "market":
                px = _num(data, "price", default=float("nan"))
                px_note = "live market price from payload"
            if not (_finite(px) and px > 0):
                return None, {**base, "status": "degraded",
                              "reason": f"price_basis={basis} but no usable repurchase price in payload"}
            retired = deploy / px
            fwd = shares - retired
            if not (fwd > 0):
                return None, {**base, "status": "degraded",
                              "reason": "buyback would retire the entire float -- sanity fail"}
            return fwd, {**base, "status": "live",
                         "authorization_native": round(auth, 1),
                         "deployed_total_native": round(deploy, 1),
                         "repurchase_price": round(px, 2),
                         "repurchase_price_note": px_note,
                         "shares_current": round(shares, 1),
                         "shares_retired": round(retired, 1),
                         "shares_forward": round(fwd, 1),
                         "pace_note": pace_note}
        if policy == "dividend":
            return shares, {**base, "status": "live",
                            "note": "dividend policy -- share count unchanged; "
                                    "per-share payout in the dividend lens"}
        return None, {**base, "status": "degraded",
                      "reason": f"unknown policy '{policy}' (want buyback|dividend|none)"}

    def _capital_return_lens(self, data: dict[str, Any], legs: dict[str, float],
                             confidences: dict[str, float],
                             penalty: float) -> Optional[dict[str, Any]]:
        """Per-share values on the FORWARD share count, beside the base legs.

        Buyback: each leg's implied total equity value (leg x current shares,
        CAD) less the deployed cash -- which leaves the enterprise -- is split
        over fewer shares. Accretive iff repurchase price < intrinsic; at
        price > intrinsic the lens reads dilutive, and that is the honest
        answer. Dividend: the lens reports the per-share payout and yield
        instead of a share-count change."""
        cr = self._ccfg().get("capital_return") or {}
        if not isinstance(cr, dict):
            return None
        policy = str(cr.get("policy", "none")).lower()
        if policy == "none":
            return None
        ccy = self.native_currency(data)
        shares = self._input(data, "shares_out")
        fwd, note = self._forward_shares(data)
        if fwd is None:
            return {"status": "degraded", **note}
        if policy == "dividend":
            payout = _num(cr, "payout_ratio", default=float("nan"))
            if not (_finite(payout) and 0.0 < payout <= 1.0):
                return {"status": "degraded", **note,
                        "reason": "dividend policy needs 0 < payout_ratio <= 1"}
            path_total = None
            bd = self._breakdown.get("income") or {}
            rt = bd.get("rate_trajectory") or {}
            if _finite(rt.get("path_cash_total_native")):
                path_total = float(rt["path_cash_total_native"])
            if path_total is None:
                return {"status": "degraded", **note,
                        "reason": "income breakdown unavailable for payout base"}
            years = self._cap_years()
            div_ps_native = (path_total / years) * payout / shares if years > 0 else 0.0
            div_ps = self.normalize_fx(div_ps_native, ccy)
            px = _num(data, "price", default=float("nan"))
            lens = {**note, "annual_dividend_ps_cad": round(div_ps, 4),
                    "payout_ratio": round(payout, 4),
                    "payout_basis": "average annual path cash over the cap horizon"}
            if _finite(px) and px > 0:
                # Both legs FX-normalized identically, so the yield is unit-free
                # (assumes payload price in the name's native currency).
                lens["yield_on_price_pct"] = round(
                    self.normalize_fx(div_ps_native, ccy) /
                    self.normalize_fx(px, ccy) * 100.0, 2)
            return lens
        # buyback: re-cut every leg on the forward count
        deploy = _num(note, "deployed_total_native", default=0.0)
        deploy_cad = self.normalize_fx(deploy, ccy)
        fwd_legs: dict[str, float] = {}
        accrual: dict[str, float] = {}
        for k, leg_v in legs.items():
            total_cad = leg_v * shares
            fwd_v = (total_cad - deploy_cad) / fwd if fwd > 0 else 0.0
            fwd_legs[k] = fwd_v
            accrual[k] = fwd_v - leg_v
        blended_fwd, _w = self.triangulate(
            {k: max(0.0, v) for k, v in fwd_legs.items()}, confidences)
        blended, _ = self.triangulate(legs, confidences)
        return {**note,
                "per_share_forward_cad": {k: round(v, 4) for k, v in fwd_legs.items()},
                "accretion_vs_base_cad": {k: round(v, 4) for k, v in accrual.items()},
                "blended_forward_cad": round(blended_fwd, 4),
                "blended_forward_after_forensic_cad": round(blended_fwd * penalty, 4),
                "blended_base_cad": round(blended, 4),
                "reading": ("ACCRETIVE -- repurchase price below intrinsic; the buyback "
                            "concentrates per-share value" if blended_fwd > blended else
                            "DILUTIVE at the assumed repurchase price -- the buyback spends "
                            "$1 of enterprise cash for < $1 of intrinsic value")}

    def _regime_implied_lens(self, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        """'What the market might pay': forward EBITDA x regime multiple.

        The forward earnings base is the outer trajectory year's EBITDA proxy
        (vessel cash less G&A -- before maint capex, closer to reported
        EBITDA); with no trajectory it falls back to year-0. The regime
        multiple is an explicit per-ticker input (estimated, labeled) -- never
        derived from the live price, which would be circular. Per-share on the
        forward count; buyback-deployed cash raises forward net debt."""
        mult = self._input(data, "ev_ebitda_regime")
        if not (_finite(mult) and mult > 0):
            return None
        ccy = self.native_currency(data)
        shares = self._input(data, "shares_out")
        bd = self._breakdown.get("income") or {}
        path = bd.get("rate_path") or []
        if not path:
            return {"status": "degraded",
                    "reason": "income breakdown has no rate path (leg not run?)"}
        outer = path[-1]
        decayed = bool((bd.get("cycle_decay") or {}).get("applied"))
        maint = _num(bd, "annual_maint_capex_native", default=0.0)
        # EBITDA proxy: annual_cash = vessel cash - G&A - maint capex, so
        # annual_cash + maint = vessel cash - G&A ~= reported EBITDA.
        # (The stored row is weight-scaled; divide the weight back out.)
        ebitda_fwd = outer["annual_cash_native"] / outer["weight"] + maint \
            if outer["weight"] > 0 else 0.0
        fwd, sh_note = self._forward_shares(data)
        fwd_shares = fwd if (fwd is not None and fwd > 0) else shares
        cr = self._ccfg().get("capital_return") or {}
        deploy = 0.0
        if isinstance(cr, dict) and str(cr.get("policy", "")).lower() == "buyback" \
                and sh_note.get("status") == "live":
            deploy = _num(sh_note, "deployed_total_native", default=0.0)
        net_debt = self._input(data, "net_debt", 0.0)
        net_debt = net_debt if _finite(net_debt) else 0.0
        v_native_ps = (ebitda_fwd * mult - (net_debt + deploy)) / fwd_shares
        v_cad = self.normalize_fx(v_native_ps, ccy)
        lens: dict[str, Any] = {
            "status": "live",
            "method": "forward-EBITDA x regime multiple (market-implied lens, NOT a leg)",
            "ebitda_forward_native": round(ebitda_fwd, 1),
            "ebitda_basis": (f"outer trajectory year (year {outer['year']}, "
                             f"${outer['repricing_rate_day']:,.0f}/day repricing rate"
                             f"{', decayed' if decayed else ''})"
                             if (bd.get("rate_trajectory") or {}).get("applied")
                             else "year-0 (no trajectory configured)"),
            "ev_ebitda_regime": round(mult, 2),
            "multiple_note": str(self._ccfg().get("ev_ebitda_regime_note", "")),
            "forward_shares": round(fwd_shares, 1),
            "forward_net_debt_native": round(net_debt + deploy, 1),
            "value_per_share_cad": round(v_cad, 4),
            "value_per_share_native": round(v_native_ps, 4),
        }
        px = _num(data, "price", default=float("nan"))
        if _finite(px) and px > 0:
            lens["vs_live_price_pct"] = round((v_native_ps / px - 1.0) * 100.0, 2)
        return lens

    def supplementary_lenses(self, data: dict[str, Any], legs: dict[str, float],
                             confidences: dict[str, float], penalty: float,
                             regime_mult: float) -> dict[str, Any]:
        """High-demand lenses beside the triangulated intrinsic: the forward
        share-count cut of every leg (capital-return policy) and the
        market-implied value (forward EBITDA x regime multiple). Informational
        -- they never move the legs, the blend, or the rating."""
        out: dict[str, Any] = {}
        cr_lens = self._capital_return_lens(data, legs, confidences, penalty)
        if cr_lens:
            out["capital_return"] = cr_lens
        ri_lens = self._regime_implied_lens(data)
        if ri_lens:
            out["regime_implied"] = ri_lens
        return out

    def scenario_band(self, data: dict[str, Any], comps: dict[str, Any], legs: dict[str, float],
                      confidences: dict[str, float], penalty: float,
                      regime_mult: float) -> Optional[dict[str, Any]]:
        """Base/bull/bear band for the contracted_cyclical archetype.

        The torque variable is the DAY-RATE, not a commodity spot: bull/bear
        re-run the income leg at leading_edge_rate x (1 +/- rate_vol) with the
        contracted book held fixed (term contracts don't reprice on a rate
        shock -- the repricing slice absorbs it). Cost (fleet floor) and market
        (mid-cycle multiple) are structural and held fixed, mirroring the
        commodity_cyclical discipline of no exogenous expansion overlay.
        """
        if confidences.get("income", 0.0) <= 0:
            return None
        vol = float(self._ccfg().get("rate_vol", self._tuning("dayrate_vol", 0.30)))
        le = self._input(data, "leading_edge_rate")
        if not (_finite(le) and le > 0 and _finite(vol) and vol > 0):
            return None
        saved_breakdown = self._breakdown

        def _shocked(f: float = 1.0) -> Optional[float]:
            d2 = dict(data)
            d2["leading_edge_rate"] = le * f
            try:
                self._breakdown = {}
                inc_raw = self.calculate_income_basis(d2, NEUTRAL_REGIME)
                shocked = {"cost": legs.get("cost", 0.0), "market": legs.get("market", 0.0),
                           "income": inc_raw * regime_mult}
            except Exception:
                return None
            finally:
                self._breakdown = saved_breakdown
            blend, _ = self.triangulate(shocked, confidences)
            return blend * penalty

        try:
            base_v = _shocked()
            bull_v = _shocked(1.0 + vol)
            bear_v = _shocked(max(0.0, 1.0 - vol))
            if base_v is None or bull_v is None or bear_v is None:
                return None
            tornado = {"dayrate": round(bull_v - base_v, 4)}
        finally:
            self._breakdown = saved_breakdown
        return {"base": round(base_v, 4), "bull": round(bull_v, 4),
                "bear": round(max(0.0, bear_v), 4), "tornado": tornado,
                "shifts": {"rate_vol": round(vol, 4),
                           "leading_edge_up": round(le * (1.0 + vol), 1),
                           "leading_edge_dn": round(le * max(0.0, 1.0 - vol), 1)},
                "method": "contracted_cyclical scenario_band (leading-edge day-rate +/-1sigma "
                          "income-leg re-run; contracted book fixed; cost/market structural)"}

    def assess_confidence(self, leg: str, value: float, data: dict[str, Any],
                          comps: dict[str, Any]) -> float:
        base = super().assess_confidence(leg, value, data, comps)
        if leg == "cost" and "proxy" in self._breakdown.get("cost", {}).get("method", ""):
            return clamp(base * 0.6, 0.0, 1.0)                           # book fallback is a proxy floor
        return base

    def calculate_forensic_score(self, financials: dict[str, Any]) -> float:
        return _producer_sieve(self, financials, "contracted_cyclical")


# =========================================================================== #
# --------------------------------------------------------------------------- #
#  Registry maps
# --------------------------------------------------------------------------- #
ARCHETYPE_REGISTRY: dict[str, type[AssetArchetype]] = {
    "option_convexity": OptionConvexityArchetype,
    "capital_margin": CapitalMarginArchetype,
    "commodity_cyclical": CommodityCyclicalArchetype,
    "asset_light_yield": AssetLightYieldArchetype,
    "pure_macro_delta": PureMacroDeltaArchetype,
    "contracted_cyclical": ContractedCyclicalArchetype,
}

#: portfolio_metadata "type" -> archetype short-name (routing fallback)
ARCHETYPE_BY_TYPE: dict[str, str] = {
    "explorer": "option_convexity", "developer": "commodity_cyclical", "producer": "commodity_cyclical",
    "producing": "commodity_cyclical", "royalty": "asset_light_yield", "streamer": "asset_light_yield",
    "infrastructure": "capital_margin", "utility": "capital_margin", "defense": "capital_margin",
    "trust": "pure_macro_delta", "etf": "pure_macro_delta", "futures": "pure_macro_delta",
    "osv": "contracted_cyclical", "tanker": "contracted_cyclical",
    "offshore_services": "contracted_cyclical", "shipping": "contracted_cyclical",
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
