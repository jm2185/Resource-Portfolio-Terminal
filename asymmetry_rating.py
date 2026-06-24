"""CommodityEx Monitor v5.3 — Phase 7: T-Q-V Asymmetry Rating (Conviction Mode).

A pure, dependency-free 0-10 rating that helps a concentrated, high-conviction operator
decide *which baskets are worth watching very closely* — WITHOUT any of the diversified-book
machinery (hard position caps, ES95 throttle, covariance shrinkage, fractional-Kelly
de-leveraging) that Phase 7 demotes out of the primary view.

Three transparent pillars (see ``PHASE7_CONVICTION_MODE.md`` §2 for the full rationale):

  * **T — Macro Tailwind**  : is the regime a tailwind for this archetype? (esp. ``alpha_option``)
  * **Q — Company Quality** : the asset on its own merits — resource quality, jurisdiction,
                              balance-sheet survival (JSF / cash-burn / dilution), management.
  * **V — Valuation Asymmetry** (the heart): realistic upside (Bull target) vs. the hard
                              downside floor (REP / liquidation value).

Design rules implemented here:
  * Valuation asymmetry carries the most weight; weights are archetype-aware.
  * A **forensic hard gate** caps the score when dilution is imminent/aggressive — survival is
    necessary, not sufficient. It is a ``min`` cap, never a smooth subtraction.
  * Model **dispersion is a confidence ribbon** (a ``± band``), never a penalty to the point
    estimate — the deliberate departure from the earlier "BAR" dispersion-penalty proposals.

The module is intentionally numpy/pandas-free so Conviction Mode can be computed and displayed
with the reduced math load (engine, Streamlit sandbox, tests, any future frontend).
"""

from __future__ import annotations

import math
from typing import Any, Optional

import quality_lenses                      # archetype-native Q lenses (royalty/holdco read on their own merits)

__all__ = [
    "DEFAULT_CONVICTION_CONFIG",
    "compute_asymmetry_rating",
    "build_conviction_state",
    "merge_conviction_config",
    "ASYMMETRY_GLOSSARY",
    "tooltip_text",
    "NICHE_TAGS",
    "niche_tags_for",
]


# --------------------------------------------------------------------------- #
#  Phase 7.4 — Educational glossary (the canonical tooltip source).
#  One dependency-free dict that every frontend renders behind a "?" icon, so the explanation of
#  each Conviction-Mode metric lives WITH the rating math (not duplicated per frontend) and stays
#  available offline. Each entry: what it measures · what good/bad looks like · how it drives the
#  rating · an edge case (esp. archetype differences). ``tooltip_text(key)`` flattens one to a string.
# --------------------------------------------------------------------------- #
ASYMMETRY_GLOSSARY: dict[str, dict[str, str]] = {
    "rating": {
        "what": "The 0–10 T·Q·V Asymmetry Rating — how closely this single name deserves watching, judged on its own merits.",
        "scale": "8.5–10 PRIME · 7–8.5 STRONG · 5–7 BALANCED · 3–5 WEAK · <3 BROKEN.",
        "influence": "A confidence-weighted blend of the three pillars, lifted toward the standout pillar when the thesis is earned, then hard-capped by the forensic gate.",
        "edge": "Assessment-only: it carries no position-sizing or portfolio math — those live in Detailed Analysis.",
    },
    "T": {
        "what": "Macro Tailwind — the FORWARD structural/secular outlook for THIS archetype + its metal over the multi-year thesis horizon. Built from LEVELS (regime/MRI, the real-yield level, the GSR level), NOT recent price action.",
        "scale": "High = risk-on regime (low MRI) + a favorable archetype lean (α>0) + a structural commodity tailwind. Low = stress regime / adverse lean.",
        "influence": "One of the three weighted pillars. It matters most for explorers (option_convexity), whose edge is macro-asymmetry, and least for cash-flow royalties.",
        "edge": "FORWARD, never backward — near-term price/dollar momentum is a SEPARATE, labeled factor that never enters T, so a strong-secular name sitting in a weak near-term tape still scores a HIGH tailwind (the P1.1 fix).",
    },
    "Q": {
        "what": "Company Quality, in a vacuum — the asset on its own merits across three weighted legs: forensic survival (JSF), resource/asset quality (the checklist below), and management. Scored archetype-tagged, on a vacuum basis (an explorer's checklist is NOT a royalty's cash-flow read).",
        "scale": "High = clean balance sheet, strong resource/cash-flow quality, proven management. Low = weak fundamentals. An explorer's Q is structurally capped by the stage penalty until it de-risks (pre-PEA names can't score producer-grade quality).",
        "influence": "The HEAVIEST pillar for royalties / asset-light yield (Q≈0.55) where recurring cash-flow quality is the whole story; deliberately LIGHT for the spear (Q≈0.22) — see V.",
        "edge": "Archetype-aware: for an explorer Q reads grade/scale/jurisdiction/metallurgy/permitting-stage (stage-penalized for pre-PEA) and is light *because* the spear's edge is V's entry asymmetry, not proven quality; for a royalty Q is heaviest, reading cash-flow durability + balance-sheet strength. JSF is BOTH a Q sub-pillar and a universal hard gate (JSF<1.5 caps the whole rating, every archetype).",
    },
    "V": {
        "what": "Valuation — measured per archetype: ASYMMETRY (explosive bull-vs-floor) for explorers, VALUE (fair-value-centred) for cash-flow names. Asymmetry V is built from three LEGIBLE inputs, not a black box: the REP/liquidation FLOOR, the floor-coverage ratio φ = floor÷price (φ≥1 means you're buying below the conservative liquidation value of the asset base → asset-backed downside), and the payoff ρ = realistic upside ÷ downside-to-floor → a payoff term blended with a floor-support term.",
        "scale": "Asymmetry: big upside over a held floor scores high; φ≥1 (price at/below liquidation) is maximum structural support, and a 1.08× coverage reads as ~8% of asset-backed cushion under the price. Value: ~5 at fair value, higher trading below intrinsic with floor support.",
        "influence": "The HEAVIEST pillar for explorers (option_convexity, V=0.45) — *because* for a below-floor, fully-funded, catalyst-rich spear the entire edge IS the entry asymmetry: you're paid to take unproven upside (so Q is light at 0.22, asset-backed downside via the floor). V and Q are therefore ONE coherent convex-spear story (22/45), not two disconnected numbers.",
        "self_inverting": "V GRADES THE ENTRY, NOT THE DESTINATION. High V = the best entry. V COMPRESSES as price rallies up through the floor — and that compression is the thesis WORKING (the asymmetry being spent exactly as designed), NOT deterioration. A falling V on strength is healthy; do not read it as a sell/decay signal.",
        "edge": "A quality royalty at fair value lands mid-range (≈5–7), NOT near zero for lacking a 5× — that's value mode. The asymmetry curve's depth-sensitivity below the floor (shallow 1.02× vs deep 1.4× coverage) is audited in the V-vs-coverage note (P1.5).",
    },
    "band": {
        "what": "The plain-language label for the rating, mode-aware.",
        "scale": "Explorers: PRIME CONVICTION / STRONG ASYMMETRY / BALANCED / WEAK / BROKEN. Cash-flow names: PRIME→IMPAIRED QUALITY.",
        "influence": "Purely a label for the numeric rating; it does not feed back into the math.",
    },
    "directive": {
        "what": "The suggested posture — watch-list language, not an order.",
        "scale": "e.g. BELOW FLOOR — ACCUMULATE · STRONG ASYMMETRY — WATCH · QUALITY — CORE HOLD · FORENSIC DECAY — AVOID.",
        "influence": "Derived from the rating, the forensic gate, and the valuation lens; calmer 'value-investor' language for cash-flow names.",
    },
    "mri": {
        "what": "Macro Regime Index (0–100) — systemic risk posture from funding, credit, curve, volatility, commodities and positioning.",
        "scale": "<45 risk-on (tailwind) · 45–65 neutral · >65 stress (headwind).",
        "influence": "The regime half of the T pillar: a lower MRI raises Macro Tailwind.",
    },
    "alpha": {
        "what": "Regime α — the archetype's discretionary macro lean for the current tape (e.g. the junior-miner 'alpha_option').",
        "scale": "+1 strong archetype tailwind · 0 neutral · −1 headwind.",
        "influence": "The archetype half of the T pillar; weighted heavily (high κ) for option_convexity so a favorable junior regime can really lift T.",
    },
    "forensic_score": {
        "what": "JSF — Junior Survival Factor (0–4): a forensic-accounting read of balance-sheet survival (runway, accruals, dilution behavior).",
        "scale": "≥3.5 clean · 2–3.5 watch · <1.5 broken.",
        "influence": "A pillar of Q AND the universal hard gate: a genuinely broken balance sheet (JSF<1.5) caps the rating regardless of archetype.",
        "edge": "The JSF gate applies to every archetype; only the dilution/runway burn-triggers are archetype-exempt.",
    },
    "resource_quality": {
        "what": "Asset-quality checklist (0–1): grade · scale · jurisdiction · metallurgy · permitting (or a cash-flow-quality proxy for royalties).",
        "scale": "Near 1 = world-class deposit / durable cash flow; near 0 = marginal.",
        "influence": "The largest sub-component of the Q pillar.",
    },
    "management": {
        "what": "Management execution — an analyst track-record read blended with the live conviction/insider signal.",
        "scale": "Near 1 = proven, aligned operators; near 0 = poor or unproven.",
        "influence": "A sub-component of the Q pillar.",
    },
    "dilution": {
        "what": "Dilution velocity — annualized growth in shares outstanding.",
        "scale": "Explorers: <2%/yr clean, >10%/yr aggressive. Royalties: routine — equity funds accretive cash-flowing acquisitions.",
        "influence": "For explorers (option_convexity) it trips the forensic SURVIVAL gate and can cap the rating near 4.5. For recurring-cash-flow archetypes (asset_light_yield) it is EXEMPT — the concern, if any, belongs in valuation accretion, not survival.",
        "edge": "THE key archetype difference: the same ~30%/yr share growth is a red flag for an explorer and normal for a growing royalty acquirer.",
    },
    "runway": {
        "what": "Cash runway — months of liquidity at the current burn.",
        "scale": "Explorers: <6 months is a survival flag. Producers/royalties: not a meaningful survival metric (they generate cash).",
        "influence": "A burn-survival gate trigger for explorers; EXEMPT for recurring-cash-flow archetypes.",
    },
    "floor_coverage": {
        "what": "Floor coverage (φ) = floor ÷ price — how much of the price is backed by the hard REP / liquidation floor.",
        "scale": "≥1.0 = trading at/below liquidation value (maximum structural support). <0.85 = priced well above the floor.",
        "influence": "Drives the V support term, relaxes the forensic gate when high, and (with macro) powers the PRIME lift.",
        "edge": "Below floor with real upside is the explorer's prime setup — it must NOT be slammed for routine financing.",
    },
    "upside": {
        "what": "Upside — realistic Bull target vs current price (asymmetry mode), or the gap to fair value (value mode).",
        "scale": "Bigger is better; near 0 means the upside is largely spent.",
        "influence": "The payoff numerator of the V pillar.",
    },
    "payoff": {
        "what": "Payoff ratio ρ — realistic upside ÷ downside-to-floor (explorers only).",
        "scale": "ρ≈2 is a 2:1 setup (mid-score); ρ→∞ when price sits at/below the floor.",
        "influence": "The core of asymmetry-mode V: a big payoff over a solid floor is heavily rewarded.",
    },
    "stability": {
        "what": "Cash-flow stability (value mode) — how recurring/durable the income is.",
        "scale": "Royalties ≈0.9 (high) · cyclicals ≈0.55. Higher = more dependable.",
        "influence": "A weighted term in value-mode V, rewarding dependable cash-flow names.",
    },
    "ribbon": {
        "what": "Confidence ribbon (±) — the ESTIMATE band: how precisely intrinsic is known given input quality. With triangulation legs present it is a propagated P10/P50/P90 distribution (input confidence + staleness + empirical peer dispersion → sampled band), not a heuristic.",
        "scale": "Tight (±0.4) with high-confidence fresh inputs; wider as inputs go stale/low-confidence or methods disagree. The P10–P90 band claims 80% containment — the replay harness grades that claim (PIT coverage).",
        "influence": "Never subtracts from the weighted-average rating, but a wider band shrinks the conviction LIFT (fail-closed: stale or low-confidence data automatically earns less conviction).",
        "edge": "Two bands, kept distinct: this estimate band says how FIRM the number is; the scenario ladder (bear/base/bull) is a set of thesis legs — what it's worth IF a scenario happens — never quantiles of this distribution.",
    },
    "gate": {
        "what": "Forensic gate — a hard cap (a min, never a smooth subtraction) for survival problems.",
        "scale": "Clean = no cap. Triggered = rating capped (≈4–4.5), relaxed toward 10 by floor support.",
        "influence": "Survival is necessary, not sufficient: a broken balance sheet (JSF) gates every archetype; dilution/runway gate only the cash-burn archetypes.",
    },
    "archetype": {
        "what": "Cash-flow-lifecycle archetype that sets the rating lens and weights.",
        "scale": "option_convexity (explorer) · commodity_cyclical (developer/producer) · asset_light_yield (royalty/streamer) · pure_macro_delta (passive).",
        "influence": "Chooses the V mode (asymmetry vs value), the pillar weights, and which forensic triggers apply.",
    },
}


def tooltip_text(key: str) -> str:
    """Flatten one glossary entry to a single multi-line string for a frontend tooltip.
    Returns ``""`` for an unknown key (callers can fall back / hide the icon)."""
    e = ASYMMETRY_GLOSSARY.get(key)
    if not e:
        return ""
    # "self_inverting" is the prominent mechanism line (e.g. V's "high V = entry; V falling on
    # strength = thesis working") — rendered with a flag prefix so it stands out in plain text;
    # only entries that carry it show it (the guard below), so other metrics are unaffected.
    order = ("what", "scale", "influence", "self_inverting", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ",
              "self_inverting": "⚠ KEY — ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


# --------------------------------------------------------------------------- #
#  Phase 7.4 — Niche-tag hooks (forward-looking; NON-FUNCTIONAL placeholder).
#  A lightweight place for future SUB-archetypes to plug in WITHOUT touching the five core
#  archetypes. A niche tag is a finer label under a parent archetype (e.g. an "accretive royalty
#  acquirer" under asset_light_yield, or a "near-term developer" under commodity_cyclical) that a
#  later phase could use to specialize tooltips / weights / gates. Nothing reads these yet, so
#  adding or removing entries is non-breaking.
# --------------------------------------------------------------------------- #
#: Fallback mirror of the canonical taxonomy (archetypes.SUBARCHETYPE_DNA is authoritative). Used
#: only if archetypes can't be imported; kept in sync by test_subarchetype_taxonomy_in_sync.
NICHE_TAGS: dict[str, list[str]] = {
    "asset_light_yield": ["nsr_royalty", "streamer", "royalty_generator_holdco", "mature_royalty"],
    "option_convexity": ["grassroots", "delineation", "pre_pea", "pea_dev"],
    "commodity_cyclical": ["near_term_dev", "ramp_up", "marginal_producer", "low_cost_producer"],
    "pure_macro_delta": ["physical_trust", "futures_etp"],
    "capital_margin": ["enricher", "infrastructure"],
}


def niche_tags_for(archetype: Optional[str]) -> list[str]:
    """Candidate sub-archetype tags for a core archetype. Sourced from the canonical
    ``archetypes.SUBARCHETYPE_DNA`` (3rd taxonomy axis), with a local mirror as a graceful
    fallback so this module stays importable on its own. Empty when none."""
    if not archetype:
        return []
    try:                                              # canonical source of truth
        from archetypes import subarchetypes_for
        names = [d.name for d in subarchetypes_for(archetype)]
        if names:
            return names
    except Exception:
        pass
    return list(NICHE_TAGS.get(archetype, []))


# --------------------------------------------------------------------------- #
#  Defaults — every constant is config-overridable via a ``conviction_mode`` block
#  (consistent with the ``archetype_factory`` convention from Phase 5).
# --------------------------------------------------------------------------- #
DEFAULT_CONVICTION_CONFIG: dict[str, Any] = {
    "rho_half": 2.0,                     # asymmetry ratio at which V_payoff = 0.5 (a 2:1 setup)
    "delta_floor": 0.10,                 # min downside denominator -> rewards genuine floor support
    "support_band": [0.75, 1.25],        # floor-coverage phi mapped 0..1 across this band
    # P1.5: shape of the V support term vs floor-coverage DEPTH. "linear" (DEFAULT, the shipped
    # behavior) ramps across support_band then FLAT-SHELFS at 1.0 — deeper-than-band coverage earns
    # nothing more, so "barely below floor" and "deeply below floor" score nearly alike. "depth" is
    # a monotonic, concave, never-flat curve tanh(beta·(phi-lo)) that keeps rewarding margin-of-
    # safety depth below the floor. Default stays "linear"; switching to "depth" is a proposal-gated
    # CALIBRATION change (/confirm) — see docs/CALIBRATION_AUDIT_2026-06-20.md and the V-vs-φ curve.
    "support_curve": "linear",
    "support_depth_beta": 1.5,
    "v_payoff_weight": 0.65,
    "v_support_weight": 0.35,
    "q_weights": {"forensic": 0.35, "quality": 0.40, "management": 0.25},
    "tq_band": [0.55, 1.70],             # Technical-Quality multiplier band -> resource quality 0..1
    "kappa_by_archetype": {"option_convexity": 0.66, "_default": 0.40},
    # How much of the macro tailwind is the COMMODITY-specific regime (gold ≠ silver ≠ uranium)
    # vs the shared archetype lean. (kappa = archetype lean · lambda below = commodity lean ·
    # remainder = raw MRI posture; base_w = max(0, 1-kappa-lambda).)
    # AUDITED for this terminal (NOT inherited blindly), reasoned, not yet backtested — TUNE:
    #   royalty 0.45  -> the underlying metal is a pure-play royalty's primary tailwind (> kappa 0.40).
    #                    Note overlap: alpha_yield already part-captures gold (real yields) but NOT
    #                    uranium, so commodity weight matters more for uranium than gold.
    #   producer 0.40 -> high operating leverage to spot.
    #   explorer 0.20 -> archetype optionality dominates (kappa 0.66); metal secondary (kappa+λ≤0.86).
    #   macro 0.0     -> a macro play, not a single-commodity tailwind.
    "commodity_weight_by_archetype": {
        "asset_light_yield": 0.45, "commodity_cyclical": 0.40,
        "option_convexity": 0.20, "pure_macro_delta": 0.0,
        # conventional-core lenses ride NO single commodity — their tailwind is the macro regime
        # (a compounder wins AI-upside/benign; a deep-value name on its own swing variable), not a metal.
        "compounder": 0.0, "deep_value": 0.0, "_default": 0.10,
    },
    # Per-archetype pillar blend. V (asymmetry) dominates for explorers; Q (cash-flow quality)
    # dominates for royalties/asset-light; cyclicals are balanced. V stays meaningful everywhere.
    "pillar_weights_by_archetype": {
        "option_convexity": {"T": 0.33, "Q": 0.22, "V": 0.45},
        "commodity_cyclical": {"T": 0.30, "Q": 0.35, "V": 0.35},
        "asset_light_yield": {"T": 0.15, "Q": 0.55, "V": 0.30},
        "pure_macro_delta": {"T": 0.45, "Q": 0.25, "V": 0.30},
        # conventional core (dual-sided TIV): the compounder's MoS is its MOAT (Q dominant, the
        # torpedo is a quality call); the deep-value name's MoS is the DISCOUNT (V dominant).
        "compounder": {"T": 0.20, "Q": 0.45, "V": 0.35},
        "deep_value": {"T": 0.15, "Q": 0.30, "V": 0.55},
        "_default": {"T": 0.25, "Q": 0.30, "V": 0.45},
    },
    # How the V pillar is measured per archetype: "asymmetry" = explosive bull-vs-floor (explorers);
    # "value" = fair-value-centred for cash-flow assets (5 at fair value, not 0 for lacking a 5x).
    # deep_value runs ASYMMETRY mode — the entry discount IS the convexity, and φ (asset/FCF floor
    # coverage) is real; compounder runs VALUE mode — fair-value-centric, the failure is the torpedo.
    "v_mode_by_archetype": {"option_convexity": "asymmetry", "deep_value": "asymmetry",
                            "compounder": "value", "_default": "value"},
    "v_value": {                          # value-mode shape
        "gap_scale": 0.40,                # tanh scale on (fair_value/price - 1)
        "center": 0.60,                   # value_term at fair value (quality deserves a premium)
        "slope": 0.40,                    # tanh amplitude around the center
        "weights": {"value": 0.45, "support": 0.10, "stability": 0.45},
        "stability_by_archetype": {       # recurring-cash-flow stability proxy (0..1)
            "asset_light_yield": 0.90, "commodity_cyclical": 0.55,
            "pure_macro_delta": 0.55,
            # a durable compounder's cash flows are stable (high); a deep-value turnaround's are
            # contingent on the swing variable (moderate) until NIS (Phase 5) confirms the receipts.
            "compounder": 0.85, "deep_value": 0.60, "_default": 0.65,
        },
        "stability_by_subarchetype": {    # finer than archetype, when the kind matters within it: a
            # project-generator / royalty-generator HOLDCO is valued via asset_light_yield but its value
            # is NAV + discovery optionality, NOT recurring NSR cash flow — so it does NOT earn the
            # royalty's 0.90 stability (which otherwise dominates V and props a 'quality' rating on a
            # name trading well above NAV). Overrides the archetype default when the subarchetype matches.
            "royalty_generator_holdco": 0.55,
        },
    },
    # Non-linear lift so a strong, *earned* thesis can exceed the weighted-average ceiling.
    "conviction_lift": {"strength": 0.65},
    # Value/quality band labels for cash-flow assets (asymmetry bands above are for explorers).
    "bands_value": [
        [8.5, "PRIME QUALITY"],
        [7.0, "HIGH QUALITY"],
        [5.0, "SOLID / FAIR"],
        [3.0, "RICH / WEAK"],
        [0.0, "IMPAIRED"],
    ],
    "forensic_gate": {
        "score_floor": 1.5, "score_cap": 4.0,         # JSF < 1.5  -> rating capped at 4.0
        "aggressive_dilution": 0.10, "dilution_cap": 4.5,   # >10%/yr share growth -> cap 4.5 ...
        "dilution_runway_comfort_months": 18.0,             # ...UNLESS the raise funded a long runway
        "min_runway_months": 6.0, "runway_cap": 4.5,        # <6 months runway -> cap 4.5
        # Recurring-cash-flow archetypes are exempt from the dilution/runway *burn* triggers
        # (their issuance funds accretive M&A, not survival); the JSF trigger stays universal.
        # Conventional-core lenses are profitable operating businesses, not junior miners burning to
        # a catalyst — the resource burn gate is the wrong test; NIS (Phase 5) is their integrity check.
        "survival_exempt_archetypes": ["asset_light_yield", "compounder", "deep_value"],
    },
    "confidence_ribbon": {
        "full": 0.4, "degraded": 0.8, "sparse": 1.5,
        "spread_mult": 0.5, "max_band": 2.5,
        # Phase 3 (validation flywheel): when the asset carries its triangulation legs the ± is
        # produced by the DISTRIBUTIONAL estimate band (uncertainty.intrinsic_distribution), and
        # width_points_mult maps the band's relative width into rating points. The heuristic
        # base/spread terms remain the fallback when no legs reach the rating.
        "width_points_mult": 4.0,
    },
    # Overrides for uncertainty.DEFAULTS (the confidence→sigma map, staleness widening, draws,
    # seed). Tunable through v5_config → /confirm; empty = module defaults.
    "uncertainty": {},
    "bands": [
        [8.5, "PRIME CONVICTION"],
        [7.0, "STRONG ASYMMETRY"],
        [5.0, "BALANCED"],
        [3.0, "WEAK / EXPENSIVE"],
        [0.0, "BROKEN / AVOID"],
    ],
}


# --------------------------------------------------------------------------- #
#  Small numeric helpers (no third-party deps)
# --------------------------------------------------------------------------- #
def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _finite(x: Any) -> bool:
    try:
        f = float(x)
        return f == f and f not in (float("inf"), float("-inf"))
    except (TypeError, ValueError):
        return False


def _num(x: Any, default: float = 0.0) -> float:
    return float(x) if _finite(x) else float(default)


def _support_term(phi: float, cfg: dict[str, Any]) -> float:
    """Floor-coverage φ -> the V support term in [0,1]. Two shapes (config ``support_curve``):

      * ``"linear"`` (DEFAULT, shipped): φ mapped across ``support_band`` [lo,hi] then clamped — a
        FLAT SHELF above hi, so coverage deeper than hi earns nothing more (the P1.5 finding: a
        45%-weight pillar treats "barely below floor" ≈ "deeply below floor").
      * ``"depth"``: a monotonic, concave, never-flat curve ``tanh(beta·(φ-lo))`` that keeps
        rewarding margin-of-safety DEPTH below the floor (the P1.5 proposal — proposal-gated).
    """
    lo, hi = cfg.get("support_band", [0.75, 1.25])
    if cfg.get("support_curve", "linear") == "depth":
        beta = float(cfg.get("support_depth_beta", 1.5))
        return _clamp(math.tanh(beta * max(0.0, _num(phi) - lo)), 0.0, 1.0)
    return _clamp((_num(phi) - lo) / max(1e-9, hi - lo), 0.0, 1.0)


def merge_conviction_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Shallow-merge a caller ``conviction_mode`` block over the defaults (one level deep for
    the nested dicts), so a partial config never drops a required key."""
    cfg = dict(DEFAULT_CONVICTION_CONFIG)
    block = (config or {}).get("conviction_mode", config or {}) if config else {}
    if not isinstance(block, dict):
        return cfg
    for k, v in block.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
        else:
            cfg[k] = v
    return cfg


# --------------------------------------------------------------------------- #
#  Pillar computations
# --------------------------------------------------------------------------- #
def _pillar_macro_tailwind(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """T in [0,10] from the live MRI (regime posture) and the archetype regime alpha
    (the discretionary macro-asymmetry lean — esp. ``alpha_option`` for explorers). For
    Option Convexity assets the alpha term dominates (``kappa`` high): a favorable junior-miner
    regime must be able to meaningfully lift the score — that asymmetry is the core edge."""
    mri = _clamp(_num(asset.get("mri"), 50.0), 0.0, 100.0)
    alpha = _clamp(_num(asset.get("regime_alpha"), 0.0), -1.0, 1.0)
    m = _clamp(1.0 - mri / 100.0, 0.0, 1.0)            # 1.0 risk-on (MRI->0), 0.0 stress (MRI->100)
    a = _clamp((1.0 + alpha) / 2.0, 0.0, 1.0)          # archetype tailwind lean re-centred to [0,1]
    arch = asset.get("archetype")
    kbya = cfg.get("kappa_by_archetype", {})
    kappa = float(kbya.get(arch, kbya.get("_default", 0.40)))
    # COMMODITY-specific tailwind (CrowdEx-style layered tag): the name's underlying metal regime
    # (gold ≠ silver ≠ uranium), engine-supplied as commodity_regime ∈ [-1,1]. Shared archetype lean
    # + commodity-specific lean — so two royalties on different metals score different tailwinds.
    cwa = cfg.get("commodity_weight_by_archetype", {})
    lam = float(cwa.get(arch, cwa.get("_default", 0.0)))
    creg = asset.get("commodity_regime")
    if creg is None or lam <= 0.0:                     # backward-compatible: no commodity signal → old blend
        lam, c = 0.0, 0.0
    else:
        c = _clamp((1.0 + _clamp(_num(creg, 0.0), -1.0, 1.0)) / 2.0, 0.0, 1.0)
    # Audit F5: keep (kappa, lam, base_w) a TRUE convex combination. A bad config with
    # kappa+lam>1 would clamp base_w to 0 and SILENTLY drop the raw-MRI posture term (and the
    # archetype/commodity leans would over-weight). Renormalize proportionally so the three
    # weights always sum to 1, and flag that the config over-specified them.
    weight_overspecified = (kappa + lam) > 1.0 + 1e-9
    if weight_overspecified:
        s = kappa + lam
        kappa, lam = kappa / s, lam / s
    base_w = max(0.0, 1.0 - kappa - lam)               # remainder rides the raw MRI posture
    T = 10.0 * (kappa * a + lam * c + base_w * m)
    out = {"score": round(T, 3), "macro_posture": round(m, 3), "asymmetry_lean": round(a, 3),
           "kappa": kappa, "mri": round(mri, 1), "alpha": round(alpha, 3),
           # decomposition: how much of T is archetype lean vs commodity regime vs raw MRI
           "alpha_contribution": round(10.0 * kappa * a, 3),
           "regime_contribution": round(10.0 * base_w * m, 3)}
    if weight_overspecified:
        out["weight_warning"] = ("kappa+lambda exceeded 1 in config — renormalized to a convex "
                                 "blend so the raw-MRI term wasn't silently dropped (audit F5).")
    if lam > 0.0:
        out.update({"commodity": asset.get("commodity"), "commodity_lean": round(c, 3),
                    "commodity_weight": lam, "commodity_regime": round(_num(creg, 0.0), 3),
                    "commodity_contribution": round(10.0 * lam * c, 3)})
    mom = asset.get("commodity_momentum")
    if mom is not None and _finite(mom):
        # SEPARATE, LABELED near-term momentum factor (action plan P1.1) — echoed for display ONLY.
        # It is deliberately NOT part of the T score above: the tailwind stays forward-structural,
        # so a strong-secular / weak-tape name (e.g. GROY) is not dragged down by recent momentum.
        out["commodity_momentum"] = round(_num(mom, 0.0), 3)
    return out


#: Default permitting/stage quality map (grassroots -> producing); config-overridable.
_STAGE_QUALITY = {
    "GRASSROOTS": 0.20, "EXPLORATION": 0.30, "DRILLING": 0.35, "RESOURCE": 0.40,
    "PEA": 0.45, "PFS": 0.60, "DFS": 0.72, "FEASIBILITY": 0.72, "PERMITTING": 0.78,
    "PERMITTED": 0.85, "CONSTRUCTION": 0.90, "PRODUCING": 1.00,
}


def _resource_quality(asset: dict[str, Any], cfg: dict[str, Any]):
    """Junior-miner quality checklist -> (q_a in [0,1], named lens breakdown). A thoughtful
    mining-investor read across the lenses that actually have data, renormalized over what is
    present:

      * **grade**       — head grade (g/t AgEq) vs a benchmark band
      * **scale**       — contained effective AgEq ounces vs a band (multi-bagger needs ounces)
      * **jurisdiction**— real Fraser index (mining-investment attractiveness)
      * **metallurgy**  — blended Ag+Au recovery (can you actually pull the metal?)
      * **permitting**  — development/permitting stage (de-risking toward production)

    Callers may pass pre-computed lens scores in ``asset['quality_lenses']`` (each 0-1), or raw
    inputs (``grade_gpt``, ``resource_oz``, ``fraser_index``, ``recovery``, ``stage``) which are
    normalized here. Falls back to an explicit override, the integrated Technical-Quality
    multiplier, Fraser, or the live market-leg confidence so it never blocks on missing data."""
    ql = cfg.get("quality_lenses", {})

    def band(x, lo, hi):
        return _clamp((_num(x) - lo) / max(1e-9, hi - lo), 0.0, 1.0)

    scores: dict[str, float] = {}
    pre = asset.get("quality_lenses") if isinstance(asset.get("quality_lenses"), dict) else {}
    for k, v in pre.items():
        if _finite(v):
            scores[k] = _clamp(_num(v), 0.0, 1.0)
    if "grade" not in scores and _finite(asset.get("grade_gpt")):
        lo, hi = ql.get("grade_band", [120, 350]); scores["grade"] = band(asset["grade_gpt"], lo, hi)
    if "scale" not in scores and _finite(asset.get("resource_oz")):
        lo, hi = ql.get("scale_band_oz", [20_000_000, 250_000_000]); scores["scale"] = band(asset["resource_oz"], lo, hi)
    if "jurisdiction" not in scores and _finite(asset.get("fraser_index")):
        lo, hi = ql.get("fraser_band", [50, 95]); scores["jurisdiction"] = band(asset["fraser_index"], lo, hi)
    if "metallurgy" not in scores and _finite(asset.get("recovery")):
        lo, hi = ql.get("recovery_band", [0.70, 0.95]); scores["metallurgy"] = band(asset["recovery"], lo, hi)
    if "permitting" not in scores and asset.get("stage"):
        sm = {**_STAGE_QUALITY, **{str(k).upper(): v for k, v in ql.get("stage_quality", {}).items()}}
        sv = sm.get(str(asset["stage"]).upper())
        if _finite(sv):
            scores["permitting"] = _clamp(_num(sv), 0.0, 1.0)

    if scores:
        w = ql.get("weights", {})
        tot = sum(w.get(k, 1.0) for k in scores)
        q_a = (sum(scores[k] * w.get(k, 1.0) for k in scores) / tot) if tot > 0 else (sum(scores.values()) / len(scores))
        return _clamp(q_a, 0.0, 1.0), {k: round(v, 3) for k, v in scores.items()}

    # Graceful fallbacks (no checklist data supplied).
    if _finite(asset.get("resource_quality")):
        return _clamp(_num(asset["resource_quality"]), 0.0, 1.0), {}
    if _finite(asset.get("avg_tq")):
        lo, hi = cfg.get("tq_band", [0.55, 1.70])
        return _clamp((_num(asset["avg_tq"]) - lo) / max(1e-9, hi - lo), 0.0, 1.0), {}
    if _finite(asset.get("fraser_index")):
        lo, hi = ql.get("fraser_band", [50, 95])
        return band(asset["fraser_index"], lo, hi), {}
    if _finite(asset.get("market_confidence")):
        return _clamp(_num(asset["market_confidence"]), 0.0, 1.0), {}
    return 0.5, {}


def _pillar_company_quality(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Q in [0,10] — the company assessed on its own merits, the way a mining investor would:

      * **forensic survival** — JSF (runway, cash-burn acceleration, dilution behavior)
      * **asset quality**     — the resource checklist (grade · scale · jurisdiction · metallurgy · permitting)
      * **management**        — execution track record blended with the insider/conviction read

    None of the diversified-book sizing math enters here."""
    s_f = _clamp(_num(asset.get("forensic_score"), 2.5), 0.0, 4.0)
    # Archetype-native quality FIRST: a royalty/holdco scored on its OWN lenses (balance sheet,
    # operator quality, accretion-per-share) from objective fed inputs — not the explorer checklist,
    # not a market echo. Three outcomes: (1) lenses available → use them; (2) the archetype HAS a
    # native lens set but no inputs are fed yet → keep the proxy but flag it `<set>_lenses_pending`
    # (loud + actionable: the fix is to FEED the quarterly inputs, not a model change); (3) no native
    # set (the explorer) → the real resource checklist, with the generic-proxy flag from increment 1.
    profile = {"archetype": asset.get("archetype"), "subarchetype": asset.get("subarchetype"),
               "commodity": asset.get("commodity")}
    al = quality_lenses.quality_lenses_for(profile, asset.get("quality_inputs") or {}, cfg)
    if al.get("available"):
        q_a, lenses, basis, proxy = al["q_a"], al["lenses"], al["basis"], False
        missing = al.get("missing") or None
    elif al.get("lens_set"):
        q_a, lenses = _resource_quality(asset, cfg)
        basis, proxy, missing = f"{al['lens_set']}_lenses_pending", True, (al.get("missing") or None)
    else:
        q_a, lenses = _resource_quality(asset, cfg)
        basis, proxy = _quality_basis(asset, bool(lenses))
        missing = None
    c = _clamp(_num(asset.get("conviction"), 0.5), 0.0, 1.0)
    # Management execution: an analyst track-record input blended with the conviction overlay;
    # falls back to conviction alone when no explicit management score is supplied. (Capital-allocation
    # DISCIPLINE for a royalty/holdco lives in the accretion / capital_allocation lens above — this
    # stays the forward execution/conviction overlay, a distinct read, so the two don't double-count.)
    mgmt_raw = asset.get("management_score")
    mgmt = _clamp(0.6 * _num(mgmt_raw) + 0.4 * c, 0.0, 1.0) if _finite(mgmt_raw) else c
    w = cfg.get("q_weights", {})
    wf = w.get("forensic", 0.35)
    wq = w.get("quality", w.get("resource", 0.40))
    wm = w.get("management", w.get("conviction", 0.25))
    Q = 10.0 * (wf * (s_f / 4.0) + wq * q_a + wm * mgmt)
    return {"score": round(Q, 3), "forensic_score": round(s_f, 2), "resource_quality": round(q_a, 3),
            "management": round(mgmt, 3), "conviction": round(c, 3), "lenses": lenses,
            "quality_basis": basis, "quality_proxy_only": proxy, "quality_missing": missing}


def _quality_basis(asset: dict[str, Any], has_checklist: bool) -> tuple[str, bool]:
    """What the Q quality leg (``resource_quality``) actually rests on, and whether that is a generic
    PROXY rather than a real per-asset read. ``proxy_only`` is True when Q has no archetype-appropriate
    quality content and is echoing the market / a flat default — the exact silent gap that lets a
    royalty/holdco wear a 'quality' score it never earned. Pure; mirrors ``_resource_quality``'s order."""
    if has_checklist:
        return "resource_checklist", False           # real per-asset mining lenses (the spear)
    if _finite(asset.get("resource_quality")):
        return "resource_quality_override", False
    if _finite(asset.get("avg_tq")):
        return "avg_tq", False
    if _finite(asset.get("fraser_index")):
        return "fraser_proxy", True
    if _finite(asset.get("market_confidence")):
        return "market_confidence_proxy", True
    return "default_0.5", True


def _v_mode(asset: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Pick the V-pillar lens for this archetype: 'asymmetry' (explosive bull-vs-floor, for
    explorers/option-convexity) or 'value' (fair-value-centred, for cash-flow assets)."""
    m = cfg.get("v_mode_by_archetype", {})
    return m.get(asset.get("archetype"), m.get("_default", "value"))


def _pillar_valuation_asymmetry(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """V in [0,10] — measured per archetype.

    * **asymmetry** (explorers): realistic upside (Bull target) vs the hard REP-Floor downside — a
      big payoff over a solid floor is heavily rewarded.
    * **value** (royalties / asset-light / cyclicals / passive): a fair-value-centred score —
      ~5 when price ≈ intrinsic, lifted by trading below fair value + floor support + cash-flow
      stability. A quality royalty at fair value lands mid-range, NOT near zero for lacking a 5×."""
    P = _num(asset.get("price"), 0.0)
    F = max(0.0, _num(asset.get("floor"), 0.0))
    base = _num(asset.get("base"), 0.0)
    if not (P > 0.0):
        return {"score": 0.0, "mode": _v_mode(asset, cfg), "upside_pct": None,
                "downside_to_floor_pct": None, "rho": None, "floor_coverage": None,
                "payoff": 0.0, "support": 0.0, "warning": "no live price"}

    phi = F / P                                              # floor coverage (>=1 => below liquidation)
    mode = _v_mode(asset, cfg)

    if mode == "asymmetry":
        B = _num(asset.get("bull"), base) or base
        delta = float(cfg.get("delta_floor", 0.10))
        rho_half = float(cfg.get("rho_half", 2.0))
        U = max(0.0, B / P - 1.0)
        Df = max(0.0, 1.0 - F / P)
        rho = U / max(Df, delta)
        v_payoff = rho / (rho + rho_half) if rho > 0 else 0.0
        v_support = _support_term(phi, cfg)            # P1.5: linear (default) or depth-sensitive
        wv = cfg.get("v_payoff_weight", 0.65); ws = cfg.get("v_support_weight", 0.35)
        V = 10.0 * (wv * v_payoff + ws * v_support)
        return {"score": round(V, 3), "mode": "asymmetry", "upside_pct": round(U * 100, 1),
                "downside_to_floor_pct": round(Df * 100, 1), "rho": round(rho, 3),
                "floor_coverage": round(phi, 3), "payoff": round(v_payoff, 3),
                "support": round(v_support, 3)}

    # ---- value mode (cash-flow assets) ----
    vv = cfg.get("v_value", {})
    scale = float(vv.get("gap_scale", 0.40))
    center = float(vv.get("center", 0.60)); slope = float(vv.get("slope", 0.40))
    gap = (base / P - 1.0) if base > 0 else 0.0             # +ve => trading below fair value
    value_term = _clamp(center + slope * math.tanh(gap / max(1e-6, scale)), 0.0, 1.0)  # center at fair value
    sup_term = _support_term(phi, cfg)                 # P1.5: linear (default) or depth-sensitive
    sby = vv.get("stability_by_archetype", {})
    sbs = vv.get("stability_by_subarchetype", {})
    sub = asset.get("subarchetype")
    stability = float(sbs[sub] if sub in sbs              # subarchetype override (a holdco ≠ a royalty)
                      else sby.get(asset.get("archetype"), sby.get("_default", 0.60)))
    w = vv.get("weights", {"value": 0.60, "support": 0.15, "stability": 0.25})
    V = 10.0 * (w.get("value", 0.60) * value_term + w.get("support", 0.15) * sup_term
                + w.get("stability", 0.25) * stability)
    return {"score": round(V, 3), "mode": "value", "upside_pct": round(gap * 100, 1),
            "downside_to_floor_pct": None, "rho": None, "floor_coverage": round(phi, 3),
            "value_term": round(value_term, 3), "support": round(sup_term, 3),
            "stability": round(stability, 3)}


# --------------------------------------------------------------------------- #
#  Forensic gate / confidence ribbon / labels / directive
# --------------------------------------------------------------------------- #
def _forensic_gate(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Floor-aware forensic gate. Forensic problems cap the rating, BUT the cap is relaxed in
    proportion to how structurally supported the downside is (price at/below the REP floor): a
    junior raising money to drill while trading below liquidation value is normal and must not be
    slammed to "avoid" — its asymmetry should shine. Conversely, diluting/burning *at a premium*
    (price well above floor) is fully gated. A genuinely broken balance sheet (very low JSF) stays
    a heavy penalty even below the floor.

    For each trigger a raw cap is computed, then lifted toward 10 by ``support`` (the floor
    coverage): ``eff = raw + (10 - raw) * support * relax``. The tightest effective cap wins."""
    g = cfg.get("forensic_gate", {})
    s_f = _num(asset.get("forensic_score"), 2.5)
    dil = asset.get("dilution_velocity")
    runway = asset.get("runway_months")
    archetype = asset.get("archetype", "_default")

    # Phase 7.3: the dilution / runway triggers are CASH-BURN SURVIVAL signals — they flag a
    # pre-revenue name diluting/burning toward a wall. For recurring-cash-flow archetypes (royalties /
    # asset-light yield) share issuance funds *accretive* acquisitions and "runway" is not a survival
    # metric, so slamming them to "forensic decay / avoid" is wrong. Those archetypes are exempt from
    # the two burn triggers; the JSF (genuinely broken balance sheet) trigger stays UNIVERSAL.
    exempt = set(g.get("survival_exempt_archetypes", ["asset_light_yield"]))
    burn_gated = archetype not in exempt

    # Floor support in [0,1]: 0 when price is well above the floor, 1 when at/below it.
    P, F = _num(asset.get("price"), 0.0), max(0.0, _num(asset.get("floor"), 0.0))
    phi = (F / P) if P > 0 else 0.0
    s_lo, s_hi = g.get("floor_support_band", [0.85, 1.10])
    support = _clamp((phi - s_lo) / max(1e-9, s_hi - s_lo), 0.0, 1.0)

    def relaxed(raw_cap, relax):
        return raw_cap + (10.0 - raw_cap) * support * relax

    cap, reasons = 10.0, []
    score_floor = g.get("score_floor", 1.5)
    if s_f < score_floor:
        # A broken balance sheet relaxes less, and the more broken (lower JSF) the less it relaxes.
        jsf_relax = g.get("jsf_relax", 0.5) * (s_f / max(1e-9, score_floor))
        c = relaxed(g.get("score_cap", 4.0), jsf_relax)
        if c < cap:
            cap = c; reasons.append(f"JSF {s_f:.1f}<{score_floor}")
    # Runway-aware dilution: a high dilution VELOCITY that bought a long runway WHILE the name trades
    # at/below its liquidation floor is margin-of-safety FUNDING, not a survival signal — so it does
    # not cap the asymmetry (mirrors the JSF runway-aware dilution gate). Diluting at a PREMIUM (no
    # floor support) stays gated regardless of runway — that's a valuation/promotional caution, not a
    # survival one, and preserves the desk's premium-dilution policy. The short-runway death-spiral
    # trigger below still bites.
    dilution_funded = (support > 0.0 and _finite(runway)
                       and _num(runway) >= g.get("dilution_runway_comfort_months", 18.0))
    if burn_gated and not dilution_funded and _finite(dil) and _num(dil) >= g.get("aggressive_dilution", 0.10):
        c = relaxed(g.get("dilution_cap", 4.5), g.get("dilution_relax", 1.0))
        if c < cap:
            cap = c; reasons.append(f"dilution {_num(dil) * 100:.0f}%/yr")
    if burn_gated and _finite(runway) and _num(runway) < g.get("min_runway_months", 6.0):
        c = relaxed(g.get("runway_cap", 4.5), g.get("runway_relax", 1.0))
        if c < cap:
            cap = c; reasons.append(f"runway {_num(runway):.0f}mo")

    applied = cap < 9.99
    return {"applied": applied, "cap": round(cap, 2),
            "floor_support": round(support, 3),
            "reason": ("; ".join(reasons) + (f" (floor-relaxed {support:.0%})" if applied and support > 0 else ""))
            if reasons else "clean"}


def _confidence_ribbon(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Dispersion -> a +/- band (information about precision), NOT a score deduction. Widens with
    sparse legs, with a wide bull/bear scenario spread, and with a STALE NAV mark (V1
    mark-NAV-to-spot: a stamped commodity spot past its freshness window means the NAV anchor
    itself is imprecise — the ribbon says so instead of the point pretending).

    Phase 3 (validation flywheel): when the asset carries its triangulation legs
    (``legs``/``leg_weights``/``leg_confidence``, optionally an empirical ``leg_sigma``), the band
    is the propagated DISTRIBUTIONAL estimate band (P10/P50/P90 from ``uncertainty.py``) instead
    of the heuristic — input confidence → stated precision, a wired pathway. This is the ESTIMATE
    band ("how precisely do we know intrinsic"); the scenario ladder stays a set of thesis legs."""
    rc = cfg.get("confidence_ribbon", {})
    quality = str(asset.get("data_quality", "full")).lower()
    base = float(rc.get(quality, rc.get("full", 0.4)))
    P = _num(asset.get("price"), 0.0)
    bull, bear = asset.get("bull"), asset.get("bear")
    spread = 0.0
    if P > 0 and _finite(bull) and _finite(bear):
        spread = max(0.0, (_num(bull) - _num(bear)) / P)
    band = base + float(rc.get("spread_mult", 0.5)) * spread
    out: dict[str, Any] = {}
    # ---- distributional estimate band (replaces the spread heuristic when legs are present) ----
    legs = asset.get("legs")
    if isinstance(legs, dict) and legs:
        dist = None
        try:
            import uncertainty as _unc
            dist = _unc.intrinsic_distribution(
                legs, asset.get("leg_weights"),
                leg_confidence=asset.get("leg_confidence"),
                leg_sigma=asset.get("leg_sigma"),
                cfg=cfg.get("uncertainty"))
        except Exception:
            dist = None                                  # graceful: heuristic band remains
        if dist:
            out.update({"p10": dist["p10"], "p50": dist["p50"], "p90": dist["p90"],
                        "rel_width": dist["rel_width"],
                        "drivers": dist["drivers"][:3],
                        "band_source": "distribution"})
            if dist.get("fail_closed"):
                out["fail_closed"] = dist["fail_closed"]
            if dist["rel_width"] is not None:
                band = base + float(rc.get("width_points_mult", 4.0)) * float(dist["rel_width"])
    nq = asset.get("nav_quality") or {}
    nq_spot = nq.get("spot") or {}
    if nq_spot.get("stale"):
        band += float(rc.get("stale_nav_widen", 0.3))
        age = nq_spot.get("age_days")
        out["nav_mark"] = (f"NAV marked to a STALE stamped {nq.get('commodity') or 'commodity'} "
                           f"spot ({f'{age:.0f}d old' if age is not None else 'undated'}) — "
                           f"re-stamp spot_usd in research_cache")
    elif nq_spot.get("tier"):
        out["nav_mark"] = f"NAV marked to {nq_spot['tier']} spot"
    band = _clamp(band, 0.0, float(rc.get("max_band", 2.5)))
    out.update({"plus_minus": round(band, 2), "quality": quality,
                "scenario_spread": round(spread, 3)})
    return out


def _band_label(rating: float, cfg: dict[str, Any], mode: str = "asymmetry") -> str:
    """Band label, mode-aware: asymmetry bands for explorers, value/quality bands for cash-flow
    assets (so a 7.0 royalty reads 'HIGH QUALITY', not 'STRONG ASYMMETRY')."""
    key = "bands_value" if mode == "value" else "bands"
    bands = cfg.get(key) or DEFAULT_CONVICTION_CONFIG.get(key, DEFAULT_CONVICTION_CONFIG["bands"])
    for threshold, label in bands:
        if rating >= threshold:
            return label
    return bands[-1][1] if bands else "BROKEN / AVOID"


def _directive(asset: dict[str, Any], rating: float, gate: dict[str, Any],
               V: dict[str, Any]) -> str:
    # Only call "avoid" on a genuinely severe (not merely floor-relaxed) forensic cap.
    if gate.get("applied") and gate.get("cap", 10.0) <= 5.0:
        return "FORENSIC DECAY — AVOID / DE-RISK"
    phi = V.get("floor_coverage")
    upside = V.get("upside_pct")
    # Value-mode (cash-flow assets) use calmer, value-investor language — not explorer "trim" calls.
    if V.get("mode") == "value":
        if rating >= 7.0:
            return "QUALITY — CORE HOLD"
        if _finite(upside) and _num(upside) >= 12.0:
            return "BELOW FAIR VALUE — ACCUMULATE"
        if _finite(upside) and _num(upside) <= -15.0:
            return "RICH — TRIM"
        if rating >= 5.0:
            return "FAIR VALUE — HOLD"
        return "WEAK SETUP — STAND ASIDE"
    # Asymmetry-mode (explorers / option convexity).
    if _finite(phi) and _num(phi) >= 1.0:
        return "BELOW FLOOR — ACCUMULATE · watch closely"
    if rating >= 7.0:
        return "STRONG ASYMMETRY — WATCH CLOSELY"
    if _finite(upside) and _num(upside) <= 10.0:
        return "UPSIDE SPENT — HOLD / TRIM"
    if rating >= 5.0:
        return "THESIS INTACT — MONITOR"
    return "WEAK SETUP — STAND ASIDE"


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def compute_asymmetry_rating(asset: dict[str, Any],
                             config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Compute the full 0-10 T-Q-V Asymmetry Rating for one basket.

    ``asset`` is a normalized, frontend-agnostic input dict (all keys optional / graceful):
        ticker, archetype, archetype_code, price, floor, base, bull, bear, mri, regime_alpha,
        forensic_score, conviction, data_quality, and any one of
        {resource_quality | avg_tq | fraser_index | market_confidence}, plus optional
        runway_months / dilution_velocity for the gate.

    Returns a dict with the three pillar scores + breakdowns, the archetype-aware blend,
    the forensic gate, the confidence ribbon, the price ladder, the band label and a directive.
    """
    cfg = merge_conviction_config(config)
    archetype = asset.get("archetype", "_default")

    T = _pillar_macro_tailwind(asset, cfg)
    Q = _pillar_company_quality(asset, cfg)
    V = _pillar_valuation_asymmetry(asset, cfg)

    pw_by = cfg.get("pillar_weights_by_archetype", {})
    pw = dict(pw_by.get(archetype, pw_by.get("_default", {"T": 0.25, "Q": 0.30, "V": 0.45})))
    a_raw = pw["T"] * T["score"] + pw["Q"] * Q["score"] + pw["V"] * V["score"]

    # ---- Conviction lift (non-linear): let a strong, well-supported thesis exceed the
    # weighted-average ceiling so high conviction can reach 8.5-9.5. The lift pulls the score
    # toward the standout pillar, scaled by how *earned* it is:
    #   * asymmetry mode -> toward V, scaled by floor support (downside structurally protected)
    #   * value mode     -> toward max(Q,V), scaled by forensic cleanliness (clean fundamentals)
    # It never exceeds the anchor pillar and is gated by support/cleanliness, so it cannot inflate
    # a premium or forensically weak name.
    lift_cfg = cfg.get("conviction_lift", {})
    strength = float(lift_cfg.get("strength", 0.6))
    if V.get("mode") == "value":
        anchor = max(Q["score"], V["score"])
        confidence = _clamp(_num(asset.get("forensic_score"), 2.5) / 4.0, 0.0, 1.0)
    else:
        anchor = V["score"]
        confidence = _clamp(_num(V.get("support"), 0.0), 0.0, 1.0)
    lift = strength * confidence * max(0.0, anchor - a_raw)
    # Phase 3 fail-closed wiring: a wider ESTIMATE band (stale / low-confidence inputs, method
    # disagreement) mechanically shrinks the conviction LIFT — the earned bonus, never the
    # weighted-average base — so data confidence → valuation confidence is a wired pathway.
    # The ribbon stays information (it never subtracts from a_raw); it only gates how much extra
    # conviction a thesis can claim on imprecise inputs.
    ribbon = _confidence_ribbon(asset, cfg)
    if lift_cfg.get("precision_scaling", True) and ribbon.get("rel_width") is not None:
        lift *= 1.0 / (1.0 + max(0.0, float(ribbon["rel_width"])))
    a_lifted = a_raw + lift

    gate = _forensic_gate(asset, cfg)
    rating = _clamp(min(a_lifted, gate["cap"]), 0.0, 10.0)
    band = _band_label(rating, cfg, mode=V.get("mode", "asymmetry"))
    directive = _directive(asset, rating, gate, V)

    return {
        "ticker": asset.get("ticker"),
        "archetype": archetype,
        "archetype_code": asset.get("archetype_code"),
        # 3rd taxonomy axis — finer sort within the archetype + orthogonal sector tags
        # (display/correlation only; deliberately NOT an input to the rating above).
        "subarchetype": asset.get("subarchetype"),
        "subarchetype_label": asset.get("subarchetype_label"),
        "sector_tags": list(asset.get("sector_tags") or []),
        # EVAL-set marker echoed through (rated, not held — no weight, no sizing) so every
        # consumer (TUI book table, agents) can badge the row and never read it as a holding.
        "eval_only": bool(asset.get("eval_only")),
        # the floor rests on a degraded book/proxy (asset-backing inputs not sourced) — consumers render
        # it as "pending" rather than presenting a placeholder as a real margin of safety (OGN.V lesson).
        "floor_degraded": bool(asset.get("floor_degraded")),
        # the Q quality leg has no archetype-appropriate read and is echoing the market / a flat default
        # (a royalty/holdco with no mining checklist) — surfaced top-level so the desk never reads a
        # proxy Q as an earned quality score. The basis string lives in pillars.Q.quality_basis.
        "quality_proxy_only": bool(Q.get("quality_proxy_only")),
        "rating": round(rating, 2),
        "rating_raw": round(a_raw, 2),
        "conviction_lift": round(lift, 3),
        "band": band,
        "pillars": {"T": T, "Q": Q, "V": V},
        "pillar_weights": pw,
        "gate": gate,
        "confidence_ribbon": ribbon,
        # V1 mark-NAV-to-spot quality (tier + staleness) — echoed through so the agents/Story Card
        # see what the NAV anchor was marked against (display/provenance; not a rating input).
        "nav_quality": asset.get("nav_quality"),
        "ladder": {
            "bull": _round_or_none(asset.get("bull")),
            "base": _round_or_none(asset.get("base")),
            "price": _round_or_none(asset.get("price")),
            "bear": _round_or_none(asset.get("bear")),
            "floor": _round_or_none(asset.get("floor")),
        },
        "directive": directive,
    }


def _round_or_none(x: Any, n: int = 3) -> Optional[float]:
    return round(float(x), n) if _finite(x) else None


def build_conviction_state(assets: list[dict[str, Any]],
                           config: Optional[dict[str, Any]] = None,
                           meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Rate a list of baskets and assemble the ``terminal_state['conviction_mode']`` block:
    every basket scored, sorted highest-conviction first, with light book-level context but NO
    portfolio-construction / sizing math (that lives in Detailed Analysis)."""
    rated = []
    for a in assets:
        try:
            rated.append(compute_asymmetry_rating(a, config))
        except Exception as e:                                # one bad basket never breaks the view
            rated.append({"ticker": a.get("ticker"), "status": "error", "error": str(e),
                          "rating": None, "band": "n/a"})
    ranked = sorted(rated, key=lambda r: (r.get("rating") is not None, r.get("rating") or -1.0),
                    reverse=True)
    out = {
        "status": "live",
        "view": "conviction",
        "primary": True,
        "baskets": ranked,
        "top_pick": ranked[0]["ticker"] if ranked and ranked[0].get("rating") is not None else None,
        "rating_scale": "0-10 T-Q-V Asymmetry (Macro Tailwind · Company Quality · Valuation Asymmetry)",
        # Phase 7.4: flattened educational tooltips (key -> text) embedded so any frontend (Flutter,
        # web) can render the same "?" help the Streamlit guide uses, without duplicating the copy.
        "glossary": {k: tooltip_text(k) for k in ASYMMETRY_GLOSSARY},
    }
    if meta:
        out["context"] = meta
    return out
