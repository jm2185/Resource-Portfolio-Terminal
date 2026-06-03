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
        "what": "Macro Tailwind — is the current regime a tailwind or headwind for THIS archetype?",
        "scale": "High = risk-on regime (low MRI) and a favorable archetype lean (α>0). Low = stress regime / adverse lean.",
        "influence": "One of the three weighted pillars. It matters most for explorers (option_convexity), whose edge is macro-asymmetry, and least for cash-flow royalties.",
        "edge": "A strong macro tailwind PLUS floor support is what lifts a strong setup from STRONG into PRIME (8.5+).",
    },
    "Q": {
        "what": "Company Quality, in a vacuum — the asset on its own merits: forensic survival (JSF), resource/asset quality, and management.",
        "scale": "High = clean balance sheet, strong resource/cash-flow quality, proven management. Low = weak fundamentals.",
        "influence": "The heaviest pillar for royalties / asset-light yield (Q-weighted), where recurring cash-flow quality is the whole story.",
        "edge": "Archetype-aware: for an explorer, Q reads grade/scale/jurisdiction; for a royalty, it reads cash-flow durability and balance-sheet strength.",
    },
    "V": {
        "what": "Valuation — measured per archetype: ASYMMETRY (explosive bull-vs-floor) for explorers, or VALUE (fair-value-centred) for cash-flow names.",
        "scale": "Asymmetry: big upside over a held floor scores high. Value: ~5 at fair value, higher trading below intrinsic with floor support.",
        "influence": "The heaviest pillar for explorers (option_convexity); meaningful but secondary for royalties.",
        "edge": "A quality royalty at fair value lands mid-range (≈5–7), NOT near zero for lacking a 5× — that was the old bug the value mode fixes.",
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
        "what": "Confidence ribbon (±) — a PRECISION band, not a penalty: how wide the estimate is given data sparsity and scenario spread.",
        "scale": "Tight (±0.4) with full data; wider (±1.5+) when sparse or when bull/bear scenarios diverge.",
        "influence": "Never moves the point rating — it only communicates how firm that number is.",
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
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


# --------------------------------------------------------------------------- #
#  Phase 7.4 — Niche-tag hooks (forward-looking; NON-FUNCTIONAL placeholder).
#  A lightweight place for future SUB-archetypes to plug in WITHOUT touching the five core
#  archetypes. A niche tag is a finer label under a parent archetype (e.g. an "accretive royalty
#  acquirer" under asset_light_yield, or a "near-term developer" under commodity_cyclical) that a
#  later phase could use to specialize tooltips / weights / gates. Nothing reads these yet, so
#  adding or removing entries is non-breaking.
# --------------------------------------------------------------------------- #
NICHE_TAGS: dict[str, list[str]] = {
    "asset_light_yield": ["accretive_acquirer", "mature_royalty", "streaming"],
    "commodity_cyclical": ["near_term_developer", "marginal_producer", "low_cost_producer"],
    "option_convexity": ["discovery_explorer", "resource_expansion", "pre_pea"],
}


def niche_tags_for(archetype: Optional[str]) -> list[str]:
    """Candidate sub-archetype tags for a core archetype (forward-looking; empty when none)."""
    return list(NICHE_TAGS.get(archetype or "", []))


# --------------------------------------------------------------------------- #
#  Defaults — every constant is config-overridable via a ``conviction_mode`` block
#  (consistent with the ``archetype_factory`` convention from Phase 5).
# --------------------------------------------------------------------------- #
DEFAULT_CONVICTION_CONFIG: dict[str, Any] = {
    "rho_half": 2.0,                     # asymmetry ratio at which V_payoff = 0.5 (a 2:1 setup)
    "delta_floor": 0.10,                 # min downside denominator -> rewards genuine floor support
    "support_band": [0.75, 1.25],        # floor-coverage phi mapped 0..1 across this band
    "v_payoff_weight": 0.65,
    "v_support_weight": 0.35,
    "q_weights": {"forensic": 0.35, "quality": 0.40, "management": 0.25},
    "tq_band": [0.55, 1.70],             # Technical-Quality multiplier band -> resource quality 0..1
    "kappa_by_archetype": {"option_convexity": 0.66, "_default": 0.40},
    # Per-archetype pillar blend. V (asymmetry) dominates for explorers; Q (cash-flow quality)
    # dominates for royalties/asset-light; cyclicals are balanced. V stays meaningful everywhere.
    "pillar_weights_by_archetype": {
        "option_convexity": {"T": 0.33, "Q": 0.22, "V": 0.45},
        "commodity_cyclical": {"T": 0.30, "Q": 0.35, "V": 0.35},
        "asset_light_yield": {"T": 0.15, "Q": 0.55, "V": 0.30},
        "pure_macro_delta": {"T": 0.45, "Q": 0.25, "V": 0.30},
        "_default": {"T": 0.25, "Q": 0.30, "V": 0.45},
    },
    # How the V pillar is measured per archetype: "asymmetry" = explosive bull-vs-floor (explorers);
    # "value" = fair-value-centred for cash-flow assets (5 at fair value, not 0 for lacking a 5x).
    "v_mode_by_archetype": {"option_convexity": "asymmetry", "_default": "value"},
    "v_value": {                          # value-mode shape
        "gap_scale": 0.40,                # tanh scale on (fair_value/price - 1)
        "center": 0.60,                   # value_term at fair value (quality deserves a premium)
        "slope": 0.40,                    # tanh amplitude around the center
        "weights": {"value": 0.45, "support": 0.10, "stability": 0.45},
        "stability_by_archetype": {       # recurring-cash-flow stability proxy (0..1)
            "asset_light_yield": 0.90, "commodity_cyclical": 0.55,
            "pure_macro_delta": 0.55, "_default": 0.65,
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
        "aggressive_dilution": 0.10, "dilution_cap": 4.5,   # >10%/yr share growth -> cap 4.5
        "min_runway_months": 6.0, "runway_cap": 4.5,        # <6 months runway -> cap 4.5
        # Recurring-cash-flow archetypes are exempt from the dilution/runway *burn* triggers
        # (their issuance funds accretive M&A, not survival); the JSF trigger stays universal.
        "survival_exempt_archetypes": ["asset_light_yield"],
    },
    "confidence_ribbon": {
        "full": 0.4, "degraded": 0.8, "sparse": 1.5,
        "spread_mult": 0.5, "max_band": 2.5,
    },
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
    kbya = cfg.get("kappa_by_archetype", {})
    kappa = float(kbya.get(asset.get("archetype"), kbya.get("_default", 0.40)))
    T = 10.0 * (kappa * a + (1.0 - kappa) * m)
    return {"score": round(T, 3), "macro_posture": round(m, 3), "asymmetry_lean": round(a, 3),
            "kappa": kappa, "mri": round(mri, 1), "alpha": round(alpha, 3),
            # how much of T is owed to the archetype macro lean (esp. alpha_option) vs raw regime
            "alpha_contribution": round(10.0 * kappa * a, 3),
            "regime_contribution": round(10.0 * (1.0 - kappa) * m, 3)}


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
    q_a, lenses = _resource_quality(asset, cfg)
    c = _clamp(_num(asset.get("conviction"), 0.5), 0.0, 1.0)
    # Management execution: an analyst track-record input blended with the conviction overlay;
    # falls back to conviction alone when no explicit management score is supplied.
    mgmt_raw = asset.get("management_score")
    mgmt = _clamp(0.6 * _num(mgmt_raw) + 0.4 * c, 0.0, 1.0) if _finite(mgmt_raw) else c
    w = cfg.get("q_weights", {})
    wf = w.get("forensic", 0.35)
    wq = w.get("quality", w.get("resource", 0.40))
    wm = w.get("management", w.get("conviction", 0.25))
    Q = 10.0 * (wf * (s_f / 4.0) + wq * q_a + wm * mgmt)
    return {"score": round(Q, 3), "forensic_score": round(s_f, 2), "resource_quality": round(q_a, 3),
            "management": round(mgmt, 3), "conviction": round(c, 3), "lenses": lenses}


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
        lo, hi = cfg.get("support_band", [0.75, 1.25])
        v_support = _clamp((phi - lo) / max(1e-9, hi - lo), 0.0, 1.0)
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
    lo, hi = cfg.get("support_band", [0.75, 1.25])
    sup_term = _clamp((phi - lo) / max(1e-9, hi - lo), 0.0, 1.0)
    sby = vv.get("stability_by_archetype", {})
    stability = float(sby.get(asset.get("archetype"), sby.get("_default", 0.60)))
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
    if burn_gated and _finite(dil) and _num(dil) >= g.get("aggressive_dilution", 0.10):
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
    sparse legs and with a wide bull/bear scenario spread."""
    rc = cfg.get("confidence_ribbon", {})
    quality = str(asset.get("data_quality", "full")).lower()
    base = float(rc.get(quality, rc.get("full", 0.4)))
    P = _num(asset.get("price"), 0.0)
    bull, bear = asset.get("bull"), asset.get("bear")
    spread = 0.0
    if P > 0 and _finite(bull) and _finite(bear):
        spread = max(0.0, (_num(bull) - _num(bear)) / P)
    band = base + float(rc.get("spread_mult", 0.5)) * spread
    band = _clamp(band, 0.0, float(rc.get("max_band", 2.5)))
    return {"plus_minus": round(band, 2), "quality": quality, "scenario_spread": round(spread, 3)}


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
    a_lifted = a_raw + lift

    gate = _forensic_gate(asset, cfg)
    rating = _clamp(min(a_lifted, gate["cap"]), 0.0, 10.0)
    ribbon = _confidence_ribbon(asset, cfg)
    band = _band_label(rating, cfg, mode=V.get("mode", "asymmetry"))
    directive = _directive(asset, rating, gate, V)

    return {
        "ticker": asset.get("ticker"),
        "archetype": archetype,
        "archetype_code": asset.get("archetype_code"),
        "rating": round(rating, 2),
        "rating_raw": round(a_raw, 2),
        "conviction_lift": round(lift, 3),
        "band": band,
        "pillars": {"T": T, "Q": Q, "V": V},
        "pillar_weights": pw,
        "gate": gate,
        "confidence_ribbon": ribbon,
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
