"""
CommodityEx Quant Monitor — Phase 5: Polymorphic Archetype Factory
==================================================================

Evolves the backend from a single-sector silver monitor into a multi-sector
thematic investment OS. Assets are routed **strictly by cash-flow lifecycle**
(not GICS sector) into one of five archetypes, each of which values the asset
through the same three-leg triangulation (Cost / Market / Income) the Phase 4a
valuation already established for the AGA.V spear — now generalized behind a
clean abstract base class and a fail-fast registry.

Design goals (per the Phase 5 brief)
------------------------------------
* **Self-contained & pure-Python.** No numpy / yfinance / engine import. The
  module is importable and unit-testable in isolation, which keeps the factory
  modular and lets it run anywhere the live `engine.py` (heavy deps) cannot.
* **Config-grounded.** It reads the *same* ``v5_config.json`` structures the
  engine uses (project buckets, technical_quality, option_premium,
  ballast_valuation, …) so the two stay numerically consistent. The math here
  faithfully mirrors `ValuationEngine.calculate_rep_floor`,
  `calculate_technical_quality`, `calculate_option_premium`, and
  `calculate_ballast_fair_value`; cross-references are noted at each site.
* **No double-counting.** Each economic source enters exactly one leg, and the
  discretionary macro-asymmetry overlay (the Regime Impact Vector) is applied
  **once**, to a single designated leg per archetype.

The five archetypes (cash-flow lifecycle)
-----------------------------------------
=====================  ==========================================  ==============
Archetype              Lifecycle                                   Anchor example
=====================  ==========================================  ==============
I.   OptionConvexity   Pre-revenue / binary-outcome                AGA.V explorer
II.  CapitalMargin     Capital-intensive operating business        infra / defense
III. CommodityCyclical Spot-price dominated margin business        GMX.TO
IV.  AssetLightYield   High-margin recurring cash-flow business     URC.TO, GROY
V.   PureMacroDelta    Passive commodity vehicle, no operations    trusts / futures
=====================  ==========================================  ==============

Regime Impact Vector
--------------------
``RegimeImpactVector = (alpha_option, alpha_margin, alpha_cyclical, alpha_yield,
alpha_delta)`` — one discretionary macro-asymmetry coefficient per archetype, in
roughly ``[-1, +1]`` (clamped). Each archetype reads *its own* coefficient and
tilts exactly one leg, embodying the Druckenmiller "lean into asymmetry" view
without re-deriving the mechanical signals already inside the legs.
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

# --------------------------------------------------------------------------- #
#  Type aliases & public surface
# --------------------------------------------------------------------------- #

#: (alpha_option, alpha_margin, alpha_cyclical, alpha_yield, alpha_delta)
RegimeImpactVector = tuple[float, float, float, float, float]

REGIME_ORDER: tuple[str, ...] = (
    "alpha_option",    # 0 -> OptionConvexity
    "alpha_margin",    # 1 -> CapitalMargin
    "alpha_cyclical",  # 2 -> CommodityCyclical
    "alpha_yield",     # 3 -> AssetLightYield
    "alpha_delta",     # 4 -> PureMacroDelta
)

NEUTRAL_REGIME: RegimeImpactVector = (0.0, 0.0, 0.0, 0.0, 0.0)

BASE_CURRENCY_DEFAULT = "CAD"

__all__ = [
    "RegimeImpactVector",
    "REGIME_ORDER",
    "NEUTRAL_REGIME",
    "TickerNotRegisteredError",
    "SparseDataError",
    "ArchetypeConfigError",
    "AssetArchetype",
    "OptionConvexityArchetype",
    "CapitalMarginArchetype",
    "CommodityCyclicalArchetype",
    "AssetLightYieldArchetype",
    "PureMacroDeltaArchetype",
    "ARCHETYPE_REGISTRY",
    "ARCHETYPE_BY_TYPE",
    "PolymorphicRouter",
    "build_default_router",
    "load_config",
]


# --------------------------------------------------------------------------- #
#  Exceptions
# --------------------------------------------------------------------------- #

class TickerNotRegisteredError(KeyError):
    """Raised by :class:`PolymorphicRouter` when a valuation is requested for a
    ticker that was never registered. Fail-fast, explicit, never a silent 0."""


class SparseDataError(ValueError):
    """Raised inside a leg when the inputs required to compute it are missing.

    Callers never see this: :meth:`AssetArchetype.valuation_summary` catches it,
    assigns the leg zero confidence, and lets the confidence-tilted blend
    renormalize over the surviving legs (graceful degradation)."""


class ArchetypeConfigError(ValueError):
    """Raised for a structurally invalid archetype configuration (e.g. weights
    that cannot be normalized)."""


# --------------------------------------------------------------------------- #
#  Small numeric helpers (pure-Python replicas of the engine primitives)
# --------------------------------------------------------------------------- #

def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp ``x`` to ``[lo, hi]`` (lo/hi may be passed in any order)."""
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
    """Graceful nested numeric getter.

    ``_num(d, "a", "b", default=1.0)`` returns ``float(d["a"]["b"])`` when that
    path exists and is finite, otherwise ``default``. Never raises on missing or
    malformed data — the backbone of the module's graceful degradation."""
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
    """Numerically-stable softplus ``(1/beta)*ln(1 + exp(beta*x))`` — a smooth
    approximation of ``max(0, x)``. Mirrors ``ValuationEngine._softplus`` without
    numpy (``np.logaddexp(0, beta*x)/beta``)."""
    z = beta * x
    # log(1 + e^z) computed stably as max(z, 0) + log1p(e^-|z|)
    return (max(z, 0.0) + math.log1p(math.exp(-abs(z)))) / beta


def capital_discount_factor(cfg: dict, y30: float) -> float:
    """Smooth cost-of-capital discount on the 30Y yield.

    Faithful pure-Python replica of ``ValuationEngine.calculate_capital_discount_factor``.
    At the live operating point (y30 ~ 4.99) this returns ~0.8808, unchanged to 4dp."""
    p = cfg.get("capital_discount_params", {
        "onset_y30": 4.0, "slope": 0.12, "floor": 0.40, "onset_beta": 8.0, "floor_beta": 25.0
    })
    excess = softplus(y30 - p["onset_y30"], p["onset_beta"])
    raw = 1.0 - p["slope"] * excess
    return p["floor"] + softplus(raw - p["floor"], p["floor_beta"])


def technical_quality(cfg: dict, project: str) -> dict:
    """Transparent, bounded Technical-Quality multiplier so in-situ ounces are
    NOT fungible. Faithful replica of ``ValuationEngine.calculate_technical_quality``
    (grade / blended Ag+Au metallurgy / real Fraser jurisdiction / infrastructure
    / depth). Returns ``{"tq": float, "factors": {...}}``."""
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
    grade = proj.get("grade_gpt_ageq", bench)
    f_grade = band("grade", grade / (2.0 * bench))                 # grade == benchmark -> mid-band

    m = fcfg.get("metallurgy", {})
    a_ag = proj.get("ageq_share_ag", 0.7)
    a_au = proj.get("ageq_share_au", 0.3)
    rec_blend = a_ag * proj.get("rec_ag", 0.85) + a_au * proj.get("rec_au", 0.92)
    f_met = band("metallurgy", (rec_blend - m.get("rec_lo", 0.70))
                 / max(1e-9, m.get("rec_hi", 0.95) - m.get("rec_lo", 0.70)))

    j = fcfg.get("jurisdiction", {})
    fraser = proj.get("fraser", 75.0)
    f_jur = band("jurisdiction", (fraser - j.get("fraser_lo", 50))
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
    """Dimensionally-coherent option/convexity premium ``pi_opt`` (a fraction >= 0).

    Faithful replica of ``ValuationEngine.calculate_option_premium``: built only
    from convexity NOT already in the comps (realized vol, monetary carry, and a
    *relative* operating-leverage edge vs peer AISC), decaying by stage."""
    oc = cfg.get("option_premium", {})
    if not oc.get("enabled", True):
        return {"pi_opt": 0.0, "vol_term": 0.0, "carry_term": 0.0, "moneyness_excess": 0.0, "stage_cap": 0.0}
    w = oc.get("weights", {"moneyness": 0.40, "vol": 0.35, "carry": 0.25})
    sv = silver_vol if (silver_vol and silver_vol > 0) else 0.30
    vol_term = min(oc.get("vol_cap", 0.40), max(0.0, sv - oc.get("vol_floor", 0.20)) * oc.get("vol_k", 1.0))
    carry_term = min(oc.get("carry_cap", 0.50),
                     max(0.0, oc.get("carry_breakeven", 1.0) - real_yield) * oc.get("carry_k", 0.25))
    moneyness = max(0.0, (spot_ag - aisc) / aisc) if aisc > 0 else 0.0
    pa = peer_aisc if (peer_aisc and peer_aisc > 0) else aisc
    peer_moneyness = max(0.0, (spot_ag - pa) / pa) if pa > 0 else 0.0
    moneyness_excess = min(oc.get("moneyness_cap", 1.50), max(0.0, moneyness - peer_moneyness))
    stage_cap = oc.get("stage_optionality_cap", {}).get(stage, 0.5)
    pi_opt = stage_cap * (w.get("moneyness", 0.40) * moneyness_excess
                          + w.get("vol", 0.35) * vol_term
                          + w.get("carry", 0.25) * carry_term)
    return {"pi_opt": round(pi_opt, 4), "vol_term": round(vol_term, 4), "carry_term": round(carry_term, 4),
            "moneyness_excess": round(moneyness_excess, 4), "stage_cap": stage_cap}


def spot_linked_fair_value(ref_price: float, base_mult: float, spot_now: float,
                           spot_ref: float, spot_beta: float, forensic_pen: float = 1.0) -> float:
    """Spot-linked ballast fair value, DECOUPLED from the name's own share price.

    Faithful replica of ``ValuationEngine.calculate_ballast_fair_value``. Fair
    value is anchored to a fundamental reference and re-scaled by the LIVE
    commodity spot only, so a price pump cannot manufacture phantom upside.
    ``spot_beta`` encodes commodity leverage (~1.0 pure royalty, >1 operating)."""
    if ref_price <= 0 or spot_ref <= 0:
        return 0.0
    spot_factor = max(0.0, 1.0 + spot_beta * ((spot_now / spot_ref) - 1.0))
    return max(0.0, ref_price * base_mult * spot_factor * forensic_pen)


def load_config(config_path: str = "v5_config.json") -> dict:
    """Load a config dict from a JSON path (convenience for callers/tests)."""
    with open(config_path, "r") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
#  Abstract base class
# --------------------------------------------------------------------------- #

@dataclass
class _LegOutcome:
    """Internal carrier for one valuation leg: its CAD value, the confidence the
    archetype attaches to it, an optional warning, and a breakdown payload."""
    value: float
    confidence: float
    warning: Optional[str] = None
    detail: dict = field(default_factory=dict)


class AssetArchetype(ABC):
    """Abstract base for every cash-flow-lifecycle archetype.

    Subclasses implement the three valuation legs plus the forensic sieve; this
    base supplies the shared machinery every archetype needs:

    * a uniform **FX normalization hook** (everything resolves to ``base_currency``),
    * **graceful degradation** (a leg that cannot be computed drops out of the blend),
    * the **confidence-tilted triangulation** ``w_i = (W_i * c_i) / Σ_j(W_j * c_j)``,
    * the **Regime Impact Vector** plumbing (each archetype tilts one leg), and
    * the standardized :meth:`valuation_summary` orchestration.

    Required overrides
    ------------------
    ``calculate_cost_basis(data) -> float``
    ``calculate_market_basis(data, comps) -> float``
    ``calculate_income_basis(data, regime_vector) -> float``
    ``calculate_forensic_score(financials) -> float``  (0.0–4.0 scale)
    """

    # -- class-level identity / defaults (overridden per archetype) --------- #
    NAME: str = "abstract"
    ROMAN: str = ""
    REGIME_INDEX: int = 0                 # which alpha in the RegimeImpactVector
    REGIME_TILT_LEG: str = "income"       # the single leg the macro overlay tilts
    DEFAULT_WEIGHTS: dict[str, float] = {"cost": 0.30, "market": 0.40, "income": 0.30}
    DEFAULT_CONFIDENCE: dict[str, float] = {"cost": 0.80, "market": 0.80, "income": 0.80}

    def __init__(self, ticker: str, config: Optional[dict] = None,
                 fx_rates: Optional[dict[str, float]] = None, *,
                 base_currency: str = BASE_CURRENCY_DEFAULT):
        self.ticker = ticker
        self.config: dict = config or {}
        self.base_currency = base_currency.upper()
        # FX table: currency code -> units of base_currency per 1 unit of code.
        self.fx_rates: dict[str, float] = {self.base_currency: 1.0}
        if fx_rates:
            self.fx_rates.update({k.upper(): float(v) for k, v in fx_rates.items()})
        # Default USD->CAD if not supplied, so a USD name (e.g. GROY) still works.
        self.fx_rates.setdefault(
            "USD", float(self.config.get("usd_to_cad",
                         self._factory_cfg("usd_to_cad_fallback", default=1.38))))
        # transient breakdown accumulator, reset per valuation_summary() call
        self._breakdown: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    #  Config access helpers
    # ------------------------------------------------------------------ #
    def _factory_cfg(self, *keys: str, default: Any = None) -> Any:
        """Read from the optional ``archetype_factory`` config block, falling
        back to ``default`` so the module works with the legacy config intact."""
        cur: Any = self.config.get("archetype_factory", {})
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def weights(self) -> dict[str, float]:
        """Stage (base) leg weights for this archetype — config-overridable."""
        w = self._factory_cfg("weights", self.NAME, default=None)
        return dict(w) if isinstance(w, dict) else dict(self.DEFAULT_WEIGHTS)

    def base_confidence(self) -> dict[str, float]:
        """Per-leg base confidence ``c_i`` — config-overridable."""
        c = self._factory_cfg("confidence", self.NAME, default=None)
        return dict(c) if isinstance(c, dict) else dict(self.DEFAULT_CONFIDENCE)

    def _tuning(self, key: str, default: Any) -> Any:
        """Read a per-archetype tuning value from ``archetype_factory[NAME][key]``."""
        val = self._factory_cfg(self.NAME, key, default=None)
        return val if val is not None else default

    # ------------------------------------------------------------------ #
    #  FX normalization hook (base currency = CAD)
    # ------------------------------------------------------------------ #
    def normalize_fx(self, value: float, currency: Optional[str] = None) -> float:
        """Uniform FX hook: convert ``value`` in ``currency`` into ``base_currency``.

        Unknown currencies fall back to 1.0 (treated as already-base) so a missing
        FX quote degrades gracefully rather than raising. This is the single point
        through which *every* leg passes, guaranteeing the brief's invariant that
        all outputs are denominated in CAD."""
        if value is None or not _finite(value):
            return 0.0
        ccy = (currency or self.base_currency).upper()
        if ccy == self.base_currency:
            return float(value)
        return float(value) * self.fx_rates.get(ccy, 1.0)

    def native_currency(self, data: dict) -> str:
        """Resolve the asset's native trading currency: explicit in the payload,
        else from ``ballast_valuation[ticker].currency`` in config, else base."""
        ccy = data.get("currency")
        if not ccy:
            ccy = self.config.get("ballast_valuation", {}).get(self.ticker, {}).get("currency")
        return str(ccy).upper() if ccy else self.base_currency

    # ------------------------------------------------------------------ #
    #  Regime Impact Vector plumbing
    # ------------------------------------------------------------------ #
    def regime_alpha(self, regime_vector: Optional[tuple]) -> float:
        """Extract THIS archetype's coefficient from the 5-tuple, clamped to
        ``[-1, 1]``. A malformed/short/absent vector degrades to neutral 0.0."""
        if not regime_vector:
            return 0.0
        try:
            if len(regime_vector) <= self.REGIME_INDEX:
                return 0.0
            return clamp(float(regime_vector[self.REGIME_INDEX]), -1.0, 1.0)
        except (TypeError, ValueError):
            return 0.0

    def regime_multiplier(self, regime_vector: Optional[tuple]) -> float:
        """Bounded macro-asymmetry multiplier ``clamp(1 + sensitivity*alpha, lo, hi)``.

        This is the Druckenmiller "lean into asymmetry" knob: ``alpha > 0`` means
        the regime is a tailwind for this archetype's lifecycle (amplify its
        tilt leg), ``alpha < 0`` a headwind (fade it). Applied exactly once."""
        alpha = self.regime_alpha(regime_vector)
        s = float(self._factory_cfg("regime", "sensitivity_default", default=0.5))
        s = float(self._tuning("regime_sensitivity", s))
        lo = float(self._factory_cfg("regime", "mult_floor", default=0.5))
        hi = float(self._factory_cfg("regime", "mult_ceiling", default=1.5))
        return clamp(1.0 + s * alpha, lo, hi)

    # ------------------------------------------------------------------ #
    #  Forensic penalty mapping (shared)
    # ------------------------------------------------------------------ #
    def forensic_penalty(self, score: float) -> float:
        """Map a 0–4 forensic score to a multiplicative haircut in ``[0.70, 1.0]``
        (producer-style ``0.70 + 0.30*(score/4)``; cf. ENGINE_DESIGN §2.2)."""
        return clamp(0.70 + 0.30 * (clamp(score, 0.0, 4.0) / 4.0), 0.70, 1.0)

    def _sieve(self, tests: list[tuple[str, Optional[bool]]]) -> tuple[float, dict]:
        """Score a list of named pass/fail tests onto the 0–4 scale.

        ``None`` marks an *indeterminate* test (data missing); it is excluded and
        the score is rescaled over the determinate tests. With zero determinate
        tests, the configured neutral default is returned (graceful, non-punitive)."""
        detail = {n: ("pass" if p else "fail" if p is not None else "n/a") for n, p in tests}
        determinate = [p for _, p in tests if p is not None]
        if not determinate:
            neutral = float(self._factory_cfg("forensic_neutral_default", default=2.5))
            return clamp(neutral, 0.0, 4.0), detail
        passed = sum(1 for p in determinate if p)
        return 4.0 * passed / len(determinate), detail

    # ------------------------------------------------------------------ #
    #  Abstract legs (subclasses MUST implement) — all return CAD floats
    # ------------------------------------------------------------------ #
    @abstractmethod
    def calculate_cost_basis(self, data: dict) -> float:
        """Cost / floor leg in CAD (replacement, NAV floor, or treasury)."""

    @abstractmethod
    def calculate_market_basis(self, data: dict, comps: dict) -> float:
        """Market / comparables leg in CAD (peer multiples, spot-linked value)."""

    @abstractmethod
    def calculate_income_basis(self, data: dict, regime_vector: tuple) -> float:
        """Income / DCF leg in CAD. Archetypes whose ``REGIME_TILT_LEG == 'income'``
        apply the macro-asymmetry overlay here; others compute it un-tilted."""

    @abstractmethod
    def calculate_forensic_score(self, financials: dict) -> float:
        """Forensic sieve on a 0.0–4.0 scale (higher = cleaner)."""

    # ------------------------------------------------------------------ #
    #  Per-leg confidence (overridable; defaults read base_confidence())
    # ------------------------------------------------------------------ #
    def assess_confidence(self, leg: str, value: float, data: dict, comps: dict) -> float:
        """Confidence ``c_i`` the archetype attaches to a computed leg value.

        Default: the configured base confidence, zeroed when the leg value is not
        a finite positive number. Subclasses sharpen this (e.g. the market leg's
        confidence falls when comps are absent). Graceful degradation lives here:
        a zero-confidence leg is renormalized out of the blend."""
        if not _finite(value) or value <= 0.0:
            return 0.0
        return clamp(self.base_confidence().get(leg, 0.5), 0.0, 1.0)

    # ------------------------------------------------------------------ #
    #  Internal safe-leg wrapper (graceful degradation)
    # ------------------------------------------------------------------ #
    def _safe_leg(self, leg: str, fn, *args) -> _LegOutcome:
        """Run a leg, converting a :class:`SparseDataError` (or any unexpected
        error) into a zero-confidence outcome with a warning, so one missing leg
        never crashes the valuation."""
        try:
            value = float(fn(*args))
            if not _finite(value):
                raise SparseDataError(f"{leg} leg returned a non-finite value")
        except SparseDataError as exc:
            return _LegOutcome(0.0, 0.0, warning=f"{leg}: {exc}")
        except Exception as exc:  # defensive: never let a leg take down the blend
            return _LegOutcome(0.0, 0.0, warning=f"{leg}: unexpected error: {exc}")
        conf = self.assess_confidence(leg, value, args[0] if args else {},
                                      args[1] if len(args) > 1 and isinstance(args[1], dict) else {})
        detail = dict(self._breakdown.get(leg, {}))
        return _LegOutcome(value, clamp(conf, 0.0, 1.0), detail=detail)

    # ------------------------------------------------------------------ #
    #  Confidence-tilted triangulation
    # ------------------------------------------------------------------ #
    def triangulate(self, legs: dict[str, float], confidences: dict[str, float]
                    ) -> tuple[float, dict[str, float]]:
        """Blend the three legs with confidence-tilted weights
        ``w_i = (W_i * c_i) / Σ_j(W_j * c_j)`` (Phase 4a §2.2). Returns the
        blended intrinsic and the realized weights (which sum to 1, or all-zero
        when every leg has degraded to zero confidence)."""
        base_w = self.weights()
        raw = {k: max(0.0, base_w.get(k, 0.0)) * max(0.0, confidences.get(k, 0.0)) for k in legs}
        wsum = sum(raw.values())
        if wsum <= 0.0:
            return 0.0, {k: 0.0 for k in legs}
        weights = {k: raw[k] / wsum for k in legs}
        intrinsic = sum(weights[k] * legs[k] for k in legs)
        return intrinsic, weights

    # ------------------------------------------------------------------ #
    #  Standardized orchestration
    # ------------------------------------------------------------------ #
    def valuation_summary(self, data: dict, comps: Optional[dict] = None,
                          regime_vector: Optional[tuple] = None,
                          financials: Optional[dict] = None) -> dict:
        """Run all three legs + the forensic sieve and return the standardized dict.

        The macro-asymmetry overlay is applied exactly once, to this archetype's
        ``REGIME_TILT_LEG`` (income-tilted archetypes apply it inside
        :meth:`calculate_income_basis`; market/cost-tilted archetypes have it
        applied here, visibly). The forensic penalty multiplies the *blended*
        intrinsic (one transparent application), never an individual leg."""
        # Accept comps either as an explicit arg or embedded in the payload, so a
        # direct caller and the router behave identically.
        if comps is None:
            comps = data.get("comps", {})
        regime_vector = tuple(regime_vector) if regime_vector else NEUTRAL_REGIME
        if financials is None:
            financials = data.get("financials", {})
        self._breakdown = {}

        cost = self._safe_leg("cost", self.calculate_cost_basis, data)
        market = self._safe_leg("market", self.calculate_market_basis, data, comps)
        income = self._safe_leg("income", self.calculate_income_basis, data, regime_vector)

        legs = {"cost": cost.value, "market": market.value, "income": income.value}
        confs = {"cost": cost.confidence, "market": market.confidence, "income": income.confidence}

        # Macro overlay for archetypes whose tilt leg is NOT income (income-tilted
        # archetypes already applied it inside their income leg — no double-tilt).
        regime_mult = self.regime_multiplier(regime_vector)
        applied_to = self.REGIME_TILT_LEG
        if applied_to in ("cost", "market"):
            legs[applied_to] = legs[applied_to] * regime_mult

        blended, weights = self.triangulate(legs, confs)

        forensic_score = clamp(float(self.calculate_forensic_score(financials)), 0.0, 4.0)
        penalty = self.forensic_penalty(forensic_score)
        intrinsic_after_forensic = blended * penalty

        warnings = [o.warning for o in (cost, market, income) if o.warning]
        # Data quality judges only the legs this archetype EXPECTS to be live
        # (non-zero base weight). An explorer's income leg is zero by design, not
        # by sparsity, so its absence must not read as "degraded".
        base_w = self.weights()
        expected = [k for k in legs if base_w.get(k, 0.0) > 0.0]
        live_expected = sum(1 for k in expected if confs.get(k, 0.0) > 0.0)
        if not expected or live_expected == len(expected):
            data_quality = "full"
        elif live_expected >= 1:
            data_quality = "degraded"
        else:
            data_quality = "sparse"

        return {
            "ticker": self.ticker,
            "archetype": self.NAME,
            "archetype_roman": self.ROMAN,
            "base_currency": self.base_currency,
            "native_currency": self.native_currency(data),
            "regime_index": self.REGIME_INDEX,
            "regime_alpha": round(self.regime_alpha(regime_vector), 4),
            "regime_multiplier": round(regime_mult, 4),
            "regime_tilt_leg": applied_to,
            "legs": {k: round(v, 4) for k, v in legs.items()},
            "base_weights": {k: round(v, 3) for k, v in self.weights().items()},
            "confidence": {k: round(v, 3) for k, v in confs.items()},
            "weights": {k: round(v, 3) for k, v in weights.items()},
            "blended_intrinsic": round(blended, 4),
            "forensic_score": round(forensic_score, 3),
            "forensic_penalty": round(penalty, 4),
            "intrinsic_after_forensic": round(intrinsic_after_forensic, 4),
            "component_breakdown": {
                "cost": cost.detail, "market": market.detail, "income": income.detail,
                "forensic": self._breakdown.get("forensic", {}),
            },
            "data_quality": data_quality,
            "warnings": warnings,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} ticker={self.ticker!r} archetype={self.NAME!r}>"


# --------------------------------------------------------------------------- #
#  I.  Option Convexity — pre-revenue / binary-outcome (AGA.V explorer)
# --------------------------------------------------------------------------- #

class OptionConvexityArchetype(AssetArchetype):
    """Pre-revenue explorers whose value is dominated by optionality on a
    discovery / commodity outcome. Mirrors the Phase 4a triangulated spear.

    * **Cost**   — REP floor (treasury + stressed in-situ resource + infra), the
      hard floor that is hard to argue with.
    * **Market** — quality-graded *defined* ounces × peer EV/oz × capital
      discount, plus a once-risked exploration sub-leg, lifted by ``(1+pi_opt)``.
    * **Income** — 0 for a pure explorer (no recurring cash flow); optionality is
      carried in the market leg, so the regime tilt leg is **market**.
    """

    NAME = "option_convexity"
    ROMAN = "I"
    REGIME_INDEX = 0          # alpha_option
    REGIME_TILT_LEG = "market"
    DEFAULT_WEIGHTS = {"cost": 0.30, "market": 0.70, "income": 0.00}
    DEFAULT_CONFIDENCE = {"cost": 0.90, "market": 0.85, "income": 0.20}

    # -- macro/context helpers -------------------------------------------- #
    def _shares(self, data: dict) -> float:
        return _num(data, "shares_out", default=self.config.get("aga_shares_out", 0.0))

    def _capital_discount(self, data: dict) -> float:
        if _present(data, "macro", "capital_discount"):
            return _num(data, "macro", "capital_discount")
        if _present(data, "macro", "y30"):
            return capital_discount_factor(self.config, _num(data, "macro", "y30"))
        return _num(data, "macro", "capital_discount", default=0.88)

    # -- COST: REP floor (replica of ValuationEngine.calculate_rep_floor) -- #
    def calculate_cost_basis(self, data: dict) -> float:
        shares = self._shares(data)
        rf = self.config.get("rep_floor_params")
        buckets = self.config.get("project_buckets_oz_AgEq", {})
        if not rf or not buckets or shares <= 0:
            raise SparseDataError("missing rep_floor_params / project buckets / shares")
        cash = rf["cash_treasury_m"] * 1_000_000
        infra = rf["permitting_infra_premium_m"] * 1_000_000
        target_mi = self.config.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
        eff_oz = 0.0
        for proj, oz in buckets.items():
            mi = target_mi.get(proj, 0.50)
            eff_oz += oz * (mi * 1.0 + (1.0 - mi) * 0.50)        # symmetric inferred haircut
        resource = eff_oz * rf["stressed_resource_per_oz"]
        rep_cad = (cash + resource + infra) * rf["conservatism_scalar"] / shares
        # REP floor is denominated in CAD already (config is CAD); FX hook is a no-op here.
        rep_cad = self.normalize_fx(rep_cad, self.native_currency(data))
        self._breakdown["cost"] = {
            "method": "REP floor", "effective_oz": round(eff_oz, 0),
            "cash_m": rf["cash_treasury_m"], "infra_m": rf["permitting_infra_premium_m"],
            "stressed_per_oz": rf["stressed_resource_per_oz"], "value_cad": round(rep_cad, 4)}
        return rep_cad

    # -- MARKET: quality-graded comps + exploration, lifted by pi_opt ----- #
    def calculate_market_basis(self, data: dict, comps: dict) -> float:
        shares = self._shares(data)
        peer_ev = _num(comps, "peer_ev_oz", default=0.0)
        buckets = self.config.get("project_buckets_oz_AgEq", {})
        if peer_ev <= 0 or not buckets or shares <= 0:
            raise SparseDataError("missing peer_ev_oz / buckets / shares")
        cap_disc = self._capital_discount(data)
        conservatism = self.config.get("conservatism_scalar", 0.88)
        target_mi = self.config.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})

        v_mkt, sum_eff, sum_quality = 0.0, 0.0, 0.0
        tq_by_project = {}
        for proj, oz in buckets.items():
            mi = target_mi.get(proj, 0.50)
            eff_oz = oz * (mi * 1.0 + (1.0 - mi) * 0.50)
            tqd = technical_quality(self.config, proj)
            quality_oz = eff_oz * tqd["tq"]
            tq_by_project[proj] = tqd
            v_mkt += quality_oz * peer_ev * cap_disc
            sum_eff += eff_oz
            sum_quality += quality_oz
        v_mkt_defined = (v_mkt * conservatism) / shares

        # exploration sub-leg: future undiscovered ounces, risked ONCE
        exp = self.config.get("exploration_upside", {})
        p_disc = _num(data, "p_discovery", default=exp.get("probability_of_discovery", 0.25))
        avg_tq = (sum_quality / sum_eff) if sum_eff > 0 else 1.0
        tq_expl = min(1.0, avg_tq)                                # undiscovered ounces earn no premium
        v_expl = (exp.get("expected_future_oz", 0) * p_disc * peer_ev * tq_expl
                  * exp.get("weight", 0.12) * conservatism) / shares

        # option-convexity premium (NOT already in comps)
        spot_ag = _num(data, "macro", "spot_ag", default=0.0)
        aisc = _num(data, "aisc", default=self.config.get("dynamic_discovery_v5", {})
                    .get("estimated_industry_aisc_2026", 24.5))
        silver_vol = _num(data, "macro", "silver_vol", default=0.30)
        real_yield = _num(data, "macro", "real_yield", default=2.0)
        opt = option_premium(self.config, spot_ag, aisc, silver_vol, real_yield, stage="explorer")

        market_cad = (v_mkt_defined + v_expl) * (1.0 + opt["pi_opt"])
        market_cad = self.normalize_fx(market_cad, self.native_currency(data))
        self._breakdown["market"] = {
            "method": "quality-graded comps + exploration x (1+pi_opt)",
            "v_mkt_defined": round(v_mkt_defined, 4), "v_exploration": round(v_expl, 4),
            "peer_ev_oz": peer_ev, "capital_discount": round(cap_disc, 4),
            "avg_tq": round(avg_tq, 3), "option_premium": opt, "tq_by_project": tq_by_project}
        return market_cad

    # -- INCOME: 0 for a pure explorer ----------------------------------- #
    def calculate_income_basis(self, data: dict, regime_vector: tuple) -> float:
        # A pre-revenue explorer has no recurring cash flow. The legitimate
        # optionality lives in the market leg (1+pi_opt), tilted by alpha_option
        # there, so this leg is a documented zero (not a missing/sparse leg).
        self._breakdown["income"] = {"method": "none (pre-revenue explorer)", "value_cad": 0.0}
        return 0.0

    def assess_confidence(self, leg: str, value: float, data: dict, comps: dict) -> float:
        base = super().assess_confidence(leg, value, data, comps)
        if leg == "income":
            return 0.0                                           # explorer income leg always drops out
        if leg == "market":
            # confidence falls when comps are stale/low-count or ounces Inferred-heavy
            tm = self.config.get("dynamic_discovery_v5", {}).get("target_measured_indicated_pct", {})
            avg_mi = (sum(tm.values()) / len(tm)) if tm else 0.5
            return clamp(base * (0.6 + 0.4 * avg_mi), 0.0, 1.0)
        return base

    # -- FORENSIC: explorer sieve (runway / CBA / dilution / SG&A) -------- #
    def calculate_forensic_score(self, financials: dict) -> float:
        f = financials or {}
        tests: list[tuple[str, Optional[bool]]] = []
        # runway
        cash = _num(f, "cash", default=float("nan"))
        burn = _num(f, "monthly_burn", default=float("nan"))
        tests.append(("runway", (cash / burn >= 18.0) if (_finite(cash) and burn > 0) else None))
        # cash-burn acceleration (lower is better)
        if _present(f, "curr_burn") and _present(f, "prev_burn"):
            ev = _num(f, "enterprise_value", default=float("nan"))
            accel = _num(f, "curr_burn") - _num(f, "prev_burn")
            if _finite(ev) and ev > 0:
                tests.append(("cba", accel / max(5_000_000.0, ev) <= 0.03))
            else:
                denom = _num(f, "cash", default=float("nan"))
                tests.append(("cba", (accel / denom <= 0.15) if (_finite(denom) and denom > 0) else None))
        else:
            tests.append(("cba", None))
        # QoQ dilution (shares shrinking/flat is a pass)
        s0, s1 = _num(f, "shares_t0", default=float("nan")), _num(f, "shares_t1", default=float("nan"))
        if _finite(s0) and _finite(s1) and s1 > 0:
            tests.append(("dilution", max(0.0, (s0 - s1) / s1) < 0.02))
        else:
            tests.append(("dilution", None))
        # SG&A drag
        sga = _num(f, "sga_expense", default=float("nan"))
        if _finite(sga) and _finite(burn) and burn > 0:
            tests.append(("sga_drag", sga / (burn * 3.0) < 0.30))
        else:
            tests.append(("sga_drag", None))
        score, detail = self._sieve(tests)
        self._breakdown["forensic"] = {"sieve": "explorer", "tests": detail, "score": round(score, 3)}
        return score


# --------------------------------------------------------------------------- #
#  II.  Capital Margin — capital-intensive operating business (infra / defense)
# --------------------------------------------------------------------------- #

class CapitalMarginArchetype(AssetArchetype):
    """Capital-intensive operating businesses earning a spread on a large invested
    capital base — regulated infrastructure, utilities, and (via the defense
    toggle) prime contractors with regulated-margin, low-cyclicality cash flows.

    * **Cost**   — invested-capital / replacement floor: ``(invested_capital − net_debt)/shares``.
    * **Market** — EV/EBITDA comp: ``(EBITDA × ev_ebitda − net_debt)/shares``.
    * **Income** — earnings-power value ``FCF / (wacc − g)``; the **defense/regulated
      toggle** widens the moat (lower effective discount), and ``alpha_margin``
      tilts this rate-sensitive leg. Income is the regime tilt leg.
    """

    NAME = "capital_margin"
    ROMAN = "II"
    REGIME_INDEX = 1          # alpha_margin
    REGIME_TILT_LEG = "income"
    DEFAULT_WEIGHTS = {"cost": 0.15, "market": 0.35, "income": 0.50}
    DEFAULT_CONFIDENCE = {"cost": 0.80, "market": 0.75, "income": 0.80}

    def _shares(self, data: dict) -> float:
        return _num(data, "shares_out", default=float("nan"))

    def calculate_cost_basis(self, data: dict) -> float:
        shares = self._shares(data)
        ccy = self.native_currency(data)
        if _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share"), ccy)
            self._breakdown["cost"] = {"method": "book value / share", "value_cad": round(v, 4)}
            return v
        if _present(data, "invested_capital") and shares > 0:
            ic = _num(data, "invested_capital")
            nd = _num(data, "net_debt", default=0.0)
            v = self.normalize_fx((ic - nd) / shares, ccy)
            self._breakdown["cost"] = {"method": "(invested_capital - net_debt)/shares",
                                       "invested_capital": ic, "net_debt": nd, "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need book_value_per_share or invested_capital+shares")

    def calculate_market_basis(self, data: dict, comps: dict) -> float:
        shares = self._shares(data)
        ev_ebitda = _num(comps, "ev_ebitda", default=float("nan"))
        ebitda = _num(data, "ebitda", default=float("nan"))
        if _finite(ev_ebitda) and _finite(ebitda) and shares > 0:
            nd = _num(data, "net_debt", default=0.0)
            equity_ps = (ebitda * ev_ebitda - nd) / shares
            v = self.normalize_fx(equity_ps, self.native_currency(data))
            self._breakdown["market"] = {"method": "EV/EBITDA comp", "ev_ebitda": ev_ebitda,
                                         "ebitda": ebitda, "net_debt": nd, "value_cad": round(v, 4)}
            return max(0.0, v)
        # fallback: P/Book comp
        pb = _num(comps, "p_book", default=float("nan"))
        if _finite(pb) and _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share") * pb, self.native_currency(data))
            self._breakdown["market"] = {"method": "P/Book comp (fallback)", "p_book": pb, "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need ev_ebitda+ebitda or p_book+book value")

    def calculate_income_basis(self, data: dict, regime_vector: tuple) -> float:
        shares = self._shares(data)
        ccy = self.native_currency(data)
        fcf_ps = _num(data, "fcf_per_share", default=float("nan"))
        if not _finite(fcf_ps):
            fcf = _num(data, "free_cash_flow", default=float("nan"))
            if _finite(fcf) and shares > 0:
                fcf_ps = fcf / shares
        if not _finite(fcf_ps):
            raise SparseDataError("need fcf_per_share or free_cash_flow+shares")
        wacc = float(self._tuning("wacc", 0.10))
        g = float(self._tuning("terminal_growth", 0.02))
        # defense/regulated toggle: a wider moat -> lower effective discount rate
        moat = float(self._tuning("defense_moat_premium", 0.15))
        if data.get("defense_or_regulated") or data.get("regulated"):
            wacc = max(g + 0.02, wacc - moat * (wacc - g))
        denom = max(0.04, wacc - g)
        epv_ps = fcf_ps / denom
        regime_mult = self.regime_multiplier(regime_vector)      # alpha_margin tilt (applied here, once)
        v = self.normalize_fx(epv_ps * regime_mult, ccy)
        self._breakdown["income"] = {"method": "earnings-power value FCF/(wacc-g)",
                                     "fcf_per_share": round(fcf_ps, 4), "wacc": round(wacc, 4),
                                     "terminal_growth": g, "regime_multiplier": round(regime_mult, 4),
                                     "value_cad": round(v, 4)}
        return max(0.0, v)

    def calculate_forensic_score(self, financials: dict) -> float:
        return _producer_sieve(self, financials, sieve_name="capital_margin")


# --------------------------------------------------------------------------- #
#  III.  Commodity Cyclical — spot-price dominated margin business (GMX.TO)
# --------------------------------------------------------------------------- #

class CommodityCyclicalArchetype(AssetArchetype):
    """Operating miners/developers whose margin is dominated by the spot price of
    the underlying commodity. High operating leverage (``spot_beta > 1``).

    * **Cost**   — NAV/replacement floor on reserves at a stressed price (or book).
    * **Market** — spot-linked fair value ``ref × mult × spot_factor`` with
      ``spot_beta`` operating leverage (decoupled from the name's own price).
    * **Income** — margin DCF: ``production × (spot − AISC)`` capitalized, tilted
      by ``alpha_cyclical`` (the income leg is the regime tilt leg).
    """

    NAME = "commodity_cyclical"
    ROMAN = "III"
    REGIME_INDEX = 2          # alpha_cyclical
    REGIME_TILT_LEG = "income"
    DEFAULT_WEIGHTS = {"cost": 0.10, "market": 0.40, "income": 0.50}
    DEFAULT_CONFIDENCE = {"cost": 0.70, "market": 0.80, "income": 0.75}

    def _spot_now(self, data: dict, commodity: str) -> float:
        return _num(data, "macro", "gold", default=0.0) if commodity == "gold" \
            else _num(data, "macro", "spot_ag", default=0.0)

    def _ballast_params(self, data: dict) -> dict:
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        return {
            "ref_price": _num(data, "ref_price", default=bv.get("ref_price", 0.0)),
            "base_mult": _num(data, "base_mult", default=bv.get("base_mult", 1.20)),
            "commodity": data.get("commodity", bv.get("commodity", "silver")),
            "spot_ref": _num(data, "spot_ref", default=bv.get("spot_ref", 0.0)),
            "spot_beta": _num(data, "spot_beta",
                              default=bv.get("spot_beta", float(self._tuning("default_spot_beta", 1.35)))),
        }

    def calculate_cost_basis(self, data: dict) -> float:
        ccy = self.native_currency(data)
        # 1) explicit book value
        if _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share"), ccy)
            self._breakdown["cost"] = {"method": "book value / share", "value_cad": round(v, 4)}
            return v
        # 2) stressed reserve NAV per share
        if _present(data, "reserves_oz") and _present(data, "shares_out"):
            stressed = _num(data, "stressed_resource_per_oz",
                            default=self.config.get("dynamic_discovery_v5", {})
                            .get("stressed_resource_baseline", 0.65))
            v = self.normalize_fx(_num(data, "reserves_oz") * stressed / _num(data, "shares_out"), ccy)
            self._breakdown["cost"] = {"method": "stressed reserve NAV/share",
                                       "stressed_per_oz": stressed, "value_cad": round(v, 4)}
            return v
        # 3) conservative fraction of the spot-linked market basis (graceful floor)
        p = self._ballast_params(data)
        if p["ref_price"] > 0 and p["spot_ref"] > 0:
            frac = float(self._tuning("cost_floor_frac", 0.45))
            spot_now = self._spot_now(data, p["commodity"])
            fv = spot_linked_fair_value(p["ref_price"], p["base_mult"], spot_now, p["spot_ref"], 1.0)
            v = self.normalize_fx(fv * frac, ccy)
            self._breakdown["cost"] = {"method": f"{frac:g}x spot-linked NAV floor (proxy)", "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need book value, reserves+shares, or ballast ref params")

    def calculate_market_basis(self, data: dict, comps: dict) -> float:
        p = self._ballast_params(data)
        if p["ref_price"] <= 0 or p["spot_ref"] <= 0:
            raise SparseDataError("need ballast ref_price + spot_ref")
        spot_now = self._spot_now(data, p["commodity"])
        fv_native = spot_linked_fair_value(p["ref_price"], p["base_mult"], spot_now,
                                           p["spot_ref"], p["spot_beta"])
        v = self.normalize_fx(fv_native, self.native_currency(data))
        self._breakdown["market"] = {"method": "spot-linked fair value (operating beta)",
                                     **{k: round(p[k], 4) if isinstance(p[k], float) else p[k] for k in p},
                                     "spot_now": round(spot_now, 4), "value_cad": round(v, 4)}
        return v

    def calculate_income_basis(self, data: dict, regime_vector: tuple) -> float:
        shares = _num(data, "shares_out", default=float("nan"))
        prod = _num(data, "annual_production_oz", default=float("nan"))
        p = self._ballast_params(data)
        spot_now = self._spot_now(data, p["commodity"])
        aisc = _num(data, "aisc", default=float("nan"))
        if not (_finite(prod) and _finite(aisc) and shares > 0 and spot_now > 0):
            raise SparseDataError("need annual_production_oz, aisc, shares, spot")
        margin = max(0.0, spot_now - aisc)
        years = float(self._tuning("margin_capitalization_years", 6.0))
        annual_cf = prod * margin
        income_ps = annual_cf * years / shares                   # simple undiscounted capitalization
        regime_mult = self.regime_multiplier(regime_vector)      # alpha_cyclical tilt (applied here, once)
        v = self.normalize_fx(income_ps * regime_mult, self.native_currency(data))
        self._breakdown["income"] = {"method": "spot-margin capitalization",
                                     "margin": round(margin, 4), "years": years,
                                     "regime_multiplier": round(regime_mult, 4), "value_cad": round(v, 4)}
        return max(0.0, v)

    def assess_confidence(self, leg: str, value: float, data: dict, comps: dict) -> float:
        base = super().assess_confidence(leg, value, data, comps)
        if leg == "cost" and self._breakdown.get("cost", {}).get("method", "").endswith("(proxy)"):
            return clamp(base * 0.6, 0.0, 1.0)                   # derived floor is less trustworthy
        return base

    def calculate_forensic_score(self, financials: dict) -> float:
        return _producer_sieve(self, financials, sieve_name="commodity_cyclical")


# --------------------------------------------------------------------------- #
#  IV.  Asset-Light Yield — high-margin recurring cash flow (URC.TO, GROY)
# --------------------------------------------------------------------------- #

class AssetLightYieldArchetype(AssetArchetype):
    """Royalty / streaming / asset-light businesses: high-margin, recurring,
    capital-light cash flows. The income (NAV) leg dominates.

    * **Cost**   — minimal tangible floor (cash/book; a thin fraction of NAV).
    * **Market** — P/NAV spot-linked value with ``spot_beta ~ 1`` (pass-through).
    * **Income** — risked stream/NSR NAV: ``cashflow × risk / (discount − growth)``,
      tilted by ``alpha_yield`` (falling real yields lift NAV). Regime tilt leg.

    FX matters here: GROY trades in USD; the FX hook normalizes every leg to CAD.
    """

    NAME = "asset_light_yield"
    ROMAN = "IV"
    REGIME_INDEX = 3          # alpha_yield
    REGIME_TILT_LEG = "income"
    DEFAULT_WEIGHTS = {"cost": 0.05, "market": 0.25, "income": 0.70}
    DEFAULT_CONFIDENCE = {"cost": 0.60, "market": 0.75, "income": 0.85}

    def _spot_now(self, data: dict, commodity: str) -> float:
        return _num(data, "macro", "gold", default=0.0) if commodity == "gold" \
            else _num(data, "macro", "spot_ag", default=0.0)

    def calculate_cost_basis(self, data: dict) -> float:
        ccy = self.native_currency(data)
        if _present(data, "book_value_per_share"):
            v = self.normalize_fx(_num(data, "book_value_per_share"), ccy)
            self._breakdown["cost"] = {"method": "book value / share", "value_cad": round(v, 4)}
            return v
        if _present(data, "cash_per_share"):
            v = self.normalize_fx(_num(data, "cash_per_share"), ccy)
            self._breakdown["cost"] = {"method": "cash / share", "value_cad": round(v, 4)}
            return v
        # thin floor: a small fraction of the spot-linked market value
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        ref = _num(data, "ref_price", default=bv.get("ref_price", 0.0))
        if ref > 0:
            frac = float(self._tuning("cost_floor_frac", 0.10))
            v = self.normalize_fx(ref * frac, ccy)
            self._breakdown["cost"] = {"method": f"{frac:g}x reference (thin asset-light floor)", "value_cad": round(v, 4)}
            return v
        raise SparseDataError("need book/cash per share or reference price")

    def calculate_market_basis(self, data: dict, comps: dict) -> float:
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        ref = _num(data, "ref_price", default=bv.get("ref_price", 0.0))
        spot_ref = _num(data, "spot_ref", default=bv.get("spot_ref", 0.0))
        if ref <= 0 or spot_ref <= 0:
            raise SparseDataError("need ref_price + spot_ref")
        commodity = data.get("commodity", bv.get("commodity", "silver"))
        # P/NAV multiple from comps lifts the base royalty multiple if supplied
        base_mult = _num(data, "base_mult", default=bv.get("base_mult", 1.15))
        p_nav = _num(comps, "p_nav", default=float("nan"))
        mult = base_mult * p_nav if _finite(p_nav) else base_mult
        beta = _num(data, "spot_beta", default=bv.get("spot_beta", 1.0))   # royalty ~ pass-through
        spot_now = self._spot_now(data, commodity)
        fv_native = spot_linked_fair_value(ref, mult, spot_now, spot_ref, beta)
        v = self.normalize_fx(fv_native, self.native_currency(data))
        self._breakdown["market"] = {"method": "P/NAV spot-linked fair value", "ref_price": ref,
                                     "mult": round(mult, 4), "spot_beta": beta,
                                     "spot_now": round(spot_now, 4), "value_cad": round(v, 4)}
        return v

    def calculate_income_basis(self, data: dict, regime_vector: tuple) -> float:
        cf_ps = _num(data, "annual_cashflow_per_share", default=float("nan"))
        if not _finite(cf_ps):
            cf = _num(data, "annual_cashflow", default=float("nan"))
            sh = _num(data, "shares_out", default=float("nan"))
            if _finite(cf) and sh > 0:
                cf_ps = cf / sh
        if not _finite(cf_ps):
            raise SparseDataError("need annual_cashflow_per_share or annual_cashflow+shares")
        discount = _num(data, "discount_rate", default=float(self._tuning("default_discount", 0.09)))
        growth = _num(data, "growth", default=float(self._tuning("default_growth", 0.02)))
        risk = _num(data, "risk", default=float(self._tuning("default_risk", 0.85)))
        denom = max(0.03, discount - growth)
        nav_ps = cf_ps * risk / denom                            # risked perpetuity NAV
        regime_mult = self.regime_multiplier(regime_vector)      # alpha_yield tilt (applied here, once)
        v = self.normalize_fx(nav_ps * regime_mult, self.native_currency(data))
        self._breakdown["income"] = {"method": "risked stream/NSR NAV (perpetuity)",
                                     "cashflow_per_share": round(cf_ps, 4), "discount": discount,
                                     "growth": growth, "risk": risk,
                                     "regime_multiplier": round(regime_mult, 4), "value_cad": round(v, 4)}
        return max(0.0, v)

    def calculate_forensic_score(self, financials: dict) -> float:
        return _producer_sieve(self, financials, sieve_name="asset_light_yield")


# --------------------------------------------------------------------------- #
#  V.  Pure Macro Delta — passive commodity vehicle, no operations
# --------------------------------------------------------------------------- #

class PureMacroDeltaArchetype(AssetArchetype):
    """Passive vehicles that ARE the commodity exposure — physical trusts (PSLV),
    futures, and ETPs with no operating business. Value is ~1:1 with spot.

    * **Cost**   — NAV anchor: the per-unit holding value at the reference frame.
    * **Market** — spot delta: ``nav_ref × (spot_now/spot_ref)``, scaled by
      ``alpha_delta`` (the pure directional bet — the regime tilt leg is market).
    * **Income** — negative carry: management/storage fee drag (no operations).
    """

    NAME = "pure_macro_delta"
    ROMAN = "V"
    REGIME_INDEX = 4          # alpha_delta
    REGIME_TILT_LEG = "market"
    DEFAULT_WEIGHTS = {"cost": 0.20, "market": 0.80, "income": 0.00}
    DEFAULT_CONFIDENCE = {"cost": 0.80, "market": 0.95, "income": 0.30}

    def _spot_now(self, data: dict, commodity: str) -> float:
        return _num(data, "macro", "gold", default=0.0) if commodity == "gold" \
            else _num(data, "macro", "spot_ag", default=0.0)

    def _nav_ref(self, data: dict) -> float:
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        return _num(data, "nav_per_unit", default=_num(data, "ref_price", default=bv.get("ref_price", 0.0)))

    def calculate_cost_basis(self, data: dict) -> float:
        nav = self._nav_ref(data)
        if nav <= 0:
            raise SparseDataError("need nav_per_unit / ref_price")
        # The NAV anchor at the reference frame is the conservative floor; a trust
        # can trade to a discount but its holdings are the hard floor.
        v = self.normalize_fx(nav, self.native_currency(data))
        self._breakdown["cost"] = {"method": "NAV anchor (holdings/unit)", "value_cad": round(v, 4)}
        return v

    def calculate_market_basis(self, data: dict, comps: dict) -> float:
        nav = self._nav_ref(data)
        bv = self.config.get("ballast_valuation", {}).get(self.ticker, {})
        commodity = data.get("commodity", bv.get("commodity", "silver"))
        spot_ref = _num(data, "spot_ref", default=bv.get("spot_ref", 0.0))
        spot_now = self._spot_now(data, commodity)
        if nav <= 0 or spot_ref <= 0 or spot_now <= 0:
            raise SparseDataError("need nav, spot_ref, and live spot")
        delta = _num(data, "delta", default=1.0)                 # 1.0 for a 1x physical trust
        fair_native = nav * (spot_now / spot_ref) * delta
        v = self.normalize_fx(fair_native, self.native_currency(data))
        self._breakdown["market"] = {"method": "spot delta (pass-through)", "nav_ref": round(nav, 4),
                                     "spot_now": round(spot_now, 4), "spot_ref": spot_ref,
                                     "delta": delta, "value_cad": round(v, 4)}
        return v

    def calculate_income_basis(self, data: dict, regime_vector: tuple) -> float:
        # No operations -> the only "income" is the negative carry of holding the
        # vehicle (management / storage fee). Returned as a small negative drag.
        nav = self._nav_ref(data)
        if nav <= 0:
            raise SparseDataError("need nav to compute fee drag")
        fee = _num(data, "fee_drag_annual", default=float(self._tuning("fee_drag_annual", 0.004)))
        v = self.normalize_fx(-fee * nav, self.native_currency(data))
        self._breakdown["income"] = {"method": "negative carry (fee drag)", "fee": fee, "value_cad": round(v, 4)}
        return v

    def assess_confidence(self, leg: str, value: float, data: dict, comps: dict) -> float:
        if leg == "income":
            # the fee-drag leg is real but tiny & negative; keep low weight, never zero-by-sign
            return clamp(self.base_confidence().get("income", 0.30), 0.0, 1.0) if _finite(value) else 0.0
        return super().assess_confidence(leg, value, data, comps)

    def calculate_forensic_score(self, financials: dict) -> float:
        # A passive vehicle has no accruals to forensically examine; the relevant
        # risks are tracking quality and fee load. Default to a clean score with a
        # premium/discount-to-NAV and fee check when data is present.
        f = financials or {}
        tests: list[tuple[str, Optional[bool]]] = []
        prem = _num(f, "premium_to_nav", default=float("nan"))   # e.g. 0.02 = +2% premium
        tests.append(("nav_tracking", abs(prem) <= 0.05 if _finite(prem) else None))
        fee = _num(f, "expense_ratio", default=float("nan"))
        tests.append(("low_fee", fee <= 0.0075 if _finite(fee) else None))
        liq = _num(f, "adv_usd", default=float("nan"))
        tests.append(("liquidity", liq >= 1_000_000 if _finite(liq) else None))
        backing = f.get("physically_backed")
        tests.append(("backing", bool(backing) if backing is not None else None))
        score, detail = self._sieve(tests)
        self._breakdown["forensic"] = {"sieve": "passive_vehicle", "tests": detail, "score": round(score, 3)}
        return score


# --------------------------------------------------------------------------- #
#  Shared producer-style forensic sieve (Capital Margin / Cyclical / Yield)
# --------------------------------------------------------------------------- #

def _producer_sieve(arch: AssetArchetype, financials: dict, *, sieve_name: str) -> float:
    """Sloan-accrual + leverage + dilution sieve for cash-flow-producing names.

    Mirrors the producer branch of ``ForensicEngine.calculate_jsf_score`` (Sloan
    CFO / BS accruals), augmented with a leverage and a dilution gate, scored onto
    the 0–4 scale with graceful handling of missing inputs."""
    f = financials or {}
    tests: list[tuple[str, Optional[bool]]] = []
    sloan_cfo = _num(f, "sloan_cfo", default=float("nan"))
    tests.append(("sloan_cfo", sloan_cfo < 0.05 if _finite(sloan_cfo) else None))
    sloan_bs = _num(f, "sloan_bs", default=float("nan"))
    tests.append(("sloan_bs", sloan_bs < 0.05 if _finite(sloan_bs) else None))
    nd = _num(f, "net_debt", default=float("nan"))
    ebitda = _num(f, "ebitda", default=float("nan"))
    if _finite(nd) and _finite(ebitda) and ebitda > 0:
        tests.append(("leverage", nd / ebitda < 3.0))
    else:
        tests.append(("leverage", None))
    s0, s1 = _num(f, "shares_t0", default=float("nan")), _num(f, "shares_t1", default=float("nan"))
    if _finite(s0) and _finite(s1) and s1 > 0:
        tests.append(("dilution", max(0.0, (s0 - s1) / s1) < 0.02))
    else:
        tests.append(("dilution", None))
    score, detail = arch._sieve(tests)
    arch._breakdown["forensic"] = {"sieve": sieve_name, "tests": detail, "score": round(score, 3)}
    return score


# --------------------------------------------------------------------------- #
#  Registry maps & the polymorphic router
# --------------------------------------------------------------------------- #

#: archetype short-name -> class (the factory's product catalogue)
ARCHETYPE_REGISTRY: dict[str, type[AssetArchetype]] = {
    OptionConvexityArchetype.NAME: OptionConvexityArchetype,
    CapitalMarginArchetype.NAME: CapitalMarginArchetype,
    CommodityCyclicalArchetype.NAME: CommodityCyclicalArchetype,
    AssetLightYieldArchetype.NAME: AssetLightYieldArchetype,
    PureMacroDeltaArchetype.NAME: PureMacroDeltaArchetype,
}

#: portfolio_metadata "type" -> archetype short-name (routing fallback)
ARCHETYPE_BY_TYPE: dict[str, str] = {
    "explorer": OptionConvexityArchetype.NAME,
    "developer": CommodityCyclicalArchetype.NAME,
    "producer": CommodityCyclicalArchetype.NAME,
    "producing": CommodityCyclicalArchetype.NAME,
    "royalty": AssetLightYieldArchetype.NAME,
    "streamer": AssetLightYieldArchetype.NAME,
    "infrastructure": CapitalMarginArchetype.NAME,
    "utility": CapitalMarginArchetype.NAME,
    "defense": CapitalMarginArchetype.NAME,
    "trust": PureMacroDeltaArchetype.NAME,
    "etf": PureMacroDeltaArchetype.NAME,
    "futures": PureMacroDeltaArchetype.NAME,
}


@dataclass(order=True)
class _LifecycleVersion:
    """One entry on a ticker's archetype timeline. ``effective`` is the date the
    asset began trading under this archetype (``None`` = since inception)."""
    sort_key: tuple = field(init=False, repr=False)
    effective: Optional[date]
    archetype: AssetArchetype = field(compare=False)
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        # None sorts first (inception); real dates sort chronologically.
        self.sort_key = (self.effective is not None,
                         self.effective or date.min)


class PolymorphicRouter:
    """Registry mapping ``ticker -> archetype instance``, with fail-fast lookup
    and **historical lifecycle versioning**.

    An asset can be re-registered at a later effective date as it graduates
    across the lifecycle (e.g. AGA.V: Option Convexity while pre-revenue ->
    Commodity Cyclical once it builds and produces). :meth:`get_valuation`
    resolves the archetype in force as of a chosen date (default: the latest)."""

    def __init__(self, config: Optional[dict] = None):
        self.config: dict = config or {}
        self._registry: dict[str, list[_LifecycleVersion]] = {}

    # -- registration ----------------------------------------------------- #
    def register_asset(self, ticker: str, archetype: AssetArchetype, *,
                       effective: Optional[date] = None, label: str = "") -> None:
        """Register (or version) an archetype for a ticker.

        Calling again with a later ``effective`` date appends a new lifecycle
        version rather than overwriting, building the asset's archetype timeline.
        A duplicate ``effective`` date replaces that specific version in place."""
        if not isinstance(archetype, AssetArchetype):
            raise ArchetypeConfigError(
                f"register_asset expects an AssetArchetype, got {type(archetype).__name__}")
        versions = self._registry.setdefault(ticker, [])
        for v in versions:
            if v.effective == effective:
                v.archetype = archetype
                v.label = label or v.label
                break
        else:
            versions.append(_LifecycleVersion(effective=effective, archetype=archetype, label=label))
        versions.sort()

    def migrate_asset(self, ticker: str, archetype: AssetArchetype,
                      effective: date, label: str = "") -> None:
        """Convenience alias for registering a *later* lifecycle version (a
        lifecycle migration). Requires the ticker to already exist."""
        if ticker not in self._registry:
            raise TickerNotRegisteredError(
                f"{ticker!r} is not registered; call register_asset first")
        self.register_asset(ticker, archetype, effective=effective, label=label)

    # -- resolution ------------------------------------------------------- #
    def is_registered(self, ticker: str) -> bool:
        return ticker in self._registry and bool(self._registry[ticker])

    def resolve(self, ticker: str, as_of: Optional[date] = None) -> AssetArchetype:
        """Return the archetype in force for ``ticker`` as of ``as_of`` (default
        latest). Fail-fast with :class:`TickerNotRegisteredError` if unknown."""
        versions = self._registry.get(ticker)
        if not versions:
            raise TickerNotRegisteredError(
                f"{ticker!r} is not registered with the PolymorphicRouter")
        if as_of is None:
            return versions[-1].archetype
        eligible = [v for v in versions if v.effective is None or v.effective <= as_of]
        if not eligible:
            # as_of predates the first dated version -> use the earliest known.
            return versions[0].archetype
        return eligible[-1].archetype

    def lifecycle_history(self, ticker: str) -> list[dict]:
        """Return the archetype timeline for a ticker (oldest first)."""
        versions = self._registry.get(ticker)
        if not versions:
            raise TickerNotRegisteredError(
                f"{ticker!r} is not registered with the PolymorphicRouter")
        return [{"effective": v.effective.isoformat() if v.effective else "inception",
                 "archetype": v.archetype.NAME, "label": v.label} for v in versions]

    def registered_tickers(self) -> list[str]:
        return sorted(self._registry)

    # -- valuation -------------------------------------------------------- #
    def get_valuation(self, ticker: str, data_payload: dict,
                      regime_vector: Optional[tuple] = None,
                      *, comps: Optional[dict] = None,
                      as_of: Optional[date] = None) -> dict:
        """Route ``ticker`` to its archetype and return the standardized
        valuation summary. ``comps`` may be passed explicitly or embedded in
        ``data_payload['comps']``. Fail-fast on an unregistered ticker."""
        archetype = self.resolve(ticker, as_of=as_of)
        comps = comps if comps is not None else data_payload.get("comps", {})
        summary = archetype.valuation_summary(
            data_payload, comps=comps, regime_vector=regime_vector,
            financials=data_payload.get("financials"))
        summary["as_of"] = as_of.isoformat() if as_of else "latest"
        summary["lifecycle_versions"] = len(self._registry.get(ticker, []))
        return summary


# --------------------------------------------------------------------------- #
#  Default router factory (wires the anchor 60/15/15/10 barbell)
# --------------------------------------------------------------------------- #

def build_default_router(config: Optional[dict] = None,
                         config_path: str = "v5_config.json",
                         fx_rates: Optional[dict[str, float]] = None) -> PolymorphicRouter:
    """Build a router pre-registered with every name in ``portfolio_metadata``.

    Routing precedence per ticker:
      1. an explicit ``portfolio_metadata[ticker]['archetype']`` short-name, else
      2. the ``archetype_routing`` map (type -> archetype) from config, else
      3. the built-in :data:`ARCHETYPE_BY_TYPE` fallback.

    This realizes the anchor test bench (AGA.V Option-Convexity spear with
    royalty/cyclical ballast) straight from config, so the factory is immediately
    usable against the live 60/15/15/10 barbell."""
    if config is None:
        config = load_config(config_path)
    router = PolymorphicRouter(config)
    routing = {**ARCHETYPE_BY_TYPE, **config.get("archetype_routing", {})}
    usd = config.get("usd_to_cad")
    fx = dict(fx_rates) if fx_rates else ({"USD": float(usd)} if usd else None)

    for ticker, meta in config.get("portfolio_metadata", {}).items():
        name = meta.get("archetype") or routing.get(str(meta.get("type", "")).lower())
        if name is None:
            continue                                             # unknown type -> skip (explicit, not silent guess)
        cls = ARCHETYPE_REGISTRY.get(name)
        if cls is None:
            raise ArchetypeConfigError(f"{ticker}: unknown archetype {name!r}")
        router.register_asset(ticker, cls(ticker, config, fx_rates=fx),
                              label=f"{meta.get('type', '?')}/{meta.get('stage', '?')}")
    return router
