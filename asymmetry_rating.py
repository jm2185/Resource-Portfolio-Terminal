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

from typing import Any, Optional

__all__ = [
    "DEFAULT_CONVICTION_CONFIG",
    "compute_asymmetry_rating",
    "build_conviction_state",
    "merge_conviction_config",
]


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
    "q_weights": {"forensic": 0.45, "quality": 0.35, "conviction": 0.20},
    "tq_band": [0.55, 1.70],             # Technical-Quality multiplier band -> resource quality 0..1
    "kappa_by_archetype": {"option_convexity": 0.60, "_default": 0.40},
    "pillar_weights_by_archetype": {
        "option_convexity": {"T": 0.30, "Q": 0.25, "V": 0.45},
        "_default": {"T": 0.25, "Q": 0.30, "V": 0.45},
    },
    "forensic_gate": {
        "score_floor": 1.5, "score_cap": 4.0,         # JSF < 1.5  -> rating capped at 4.0
        "aggressive_dilution": 0.10, "dilution_cap": 4.5,   # >10%/yr share growth -> cap 4.5
        "min_runway_months": 6.0, "runway_cap": 4.5,        # <6 months runway -> cap 4.5
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
    (the discretionary macro-asymmetry lean — esp. ``alpha_option`` for explorers)."""
    mri = _clamp(_num(asset.get("mri"), 50.0), 0.0, 100.0)
    alpha = _clamp(_num(asset.get("regime_alpha"), 0.0), -1.0, 1.0)
    m = _clamp(1.0 - mri / 100.0, 0.0, 1.0)            # 1.0 risk-on (MRI->0), 0.0 stress (MRI->100)
    a = _clamp((1.0 + alpha) / 2.0, 0.0, 1.0)          # archetype tailwind lean re-centred to [0,1]
    kbya = cfg.get("kappa_by_archetype", {})
    kappa = float(kbya.get(asset.get("archetype"), kbya.get("_default", 0.40)))
    T = 10.0 * (kappa * a + (1.0 - kappa) * m)
    return {"score": round(T, 3), "macro_posture": round(m, 3), "asymmetry_lean": round(a, 3),
            "kappa": kappa, "mri": round(mri, 1), "alpha": round(alpha, 3)}


def _resource_quality(asset: dict[str, Any], cfg: dict[str, Any]) -> float:
    """Asset/resource quality q_a in [0,1] — the junior-miner lens. Prefers the Technical-Quality
    multiplier (grade, blended Ag+Au metallurgy, real Fraser-index jurisdiction, infra, depth),
    then an explicit override, then Fraser index, then the live market-leg confidence."""
    if _finite(asset.get("resource_quality")):
        return _clamp(_num(asset["resource_quality"]), 0.0, 1.0)
    if _finite(asset.get("avg_tq")):
        lo, hi = cfg.get("tq_band", [0.55, 1.70])
        return _clamp((_num(asset["avg_tq"]) - lo) / max(1e-9, hi - lo), 0.0, 1.0)
    if _finite(asset.get("fraser_index")):
        return _clamp(_num(asset["fraser_index"]) / 100.0, 0.0, 1.0)
    if _finite(asset.get("market_confidence")):
        return _clamp(_num(asset["market_confidence"]), 0.0, 1.0)
    return 0.5


def _pillar_company_quality(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Q in [0,10] — the company in a vacuum: forensic survival + resource/asset quality +
    management/conviction credibility."""
    s_f = _clamp(_num(asset.get("forensic_score"), 2.5), 0.0, 4.0)
    q_a = _resource_quality(asset, cfg)
    c = _clamp(_num(asset.get("conviction"), 0.5), 0.0, 1.0)
    w = cfg.get("q_weights", {})
    Q = 10.0 * (w.get("forensic", 0.45) * (s_f / 4.0)
                + w.get("quality", 0.35) * q_a
                + w.get("conviction", 0.20) * c)
    return {"score": round(Q, 3), "forensic_score": round(s_f, 2), "resource_quality": round(q_a, 3),
            "conviction": round(c, 3)}


def _pillar_valuation_asymmetry(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """V in [0,10] — the heart: realistic upside (Bull target) vs the hard downside floor."""
    P = _num(asset.get("price"), 0.0)
    F = max(0.0, _num(asset.get("floor"), 0.0))
    base = _num(asset.get("base"), 0.0)
    B = _num(asset.get("bull"), base) or base               # bull target, defaulting to base
    if not (P > 0.0):
        return {"score": 0.0, "upside_pct": None, "downside_to_floor_pct": None,
                "rho": None, "floor_coverage": None, "payoff": 0.0, "support": 0.0,
                "warning": "no live price"}

    delta = float(cfg.get("delta_floor", 0.10))
    rho_half = float(cfg.get("rho_half", 2.0))
    U = max(0.0, B / P - 1.0)                                # realistic upside fraction
    Df = max(0.0, 1.0 - F / P)                               # downside-to-floor fraction
    rho = U / max(Df, delta)                                 # asymmetry ratio
    v_payoff = rho / (rho + rho_half) if rho > 0 else 0.0

    phi = F / P                                              # floor coverage (>=1 => below liquidation)
    lo, hi = cfg.get("support_band", [0.75, 1.25])
    v_support = _clamp((phi - lo) / max(1e-9, hi - lo), 0.0, 1.0)

    wv = cfg.get("v_payoff_weight", 0.65); ws = cfg.get("v_support_weight", 0.35)
    V = 10.0 * (wv * v_payoff + ws * v_support)
    return {"score": round(V, 3), "upside_pct": round(U * 100, 1),
            "downside_to_floor_pct": round(Df * 100, 1), "rho": round(rho, 3),
            "floor_coverage": round(phi, 3), "payoff": round(v_payoff, 3),
            "support": round(v_support, 3)}


# --------------------------------------------------------------------------- #
#  Forensic gate / confidence ribbon / labels / directive
# --------------------------------------------------------------------------- #
def _forensic_gate(asset: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Hard gate (a cap, never a smooth penalty): imminent/aggressive dilution or a broken
    runway cap the rating — you do not watch a basket about to dilute you."""
    g = cfg.get("forensic_gate", {})
    s_f = _num(asset.get("forensic_score"), 2.5)
    dil = asset.get("dilution_velocity")
    runway = asset.get("runway_months")
    cap, reasons = 10.0, []
    if s_f < g.get("score_floor", 1.5):
        cap = min(cap, g.get("score_cap", 4.0)); reasons.append(f"JSF {s_f:.1f} < {g.get('score_floor', 1.5)}")
    if _finite(dil) and _num(dil) >= g.get("aggressive_dilution", 0.10):
        cap = min(cap, g.get("dilution_cap", 4.5)); reasons.append(f"dilution {_num(dil) * 100:.0f}%/yr")
    if _finite(runway) and _num(runway) < g.get("min_runway_months", 6.0):
        cap = min(cap, g.get("runway_cap", 4.5)); reasons.append(f"runway {_num(runway):.0f}mo")
    return {"applied": cap < 10.0, "cap": round(cap, 2), "reason": "; ".join(reasons) or "clean"}


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


def _band_label(rating: float, cfg: dict[str, Any]) -> str:
    for threshold, label in cfg.get("bands", DEFAULT_CONVICTION_CONFIG["bands"]):
        if rating >= threshold:
            return label
    return "BROKEN / AVOID"


def _directive(asset: dict[str, Any], rating: float, gate: dict[str, Any],
               V: dict[str, Any]) -> str:
    if gate.get("applied") and gate.get("cap", 10.0) <= 4.5:
        return "FORENSIC DECAY — AVOID / DE-RISK"
    phi = V.get("floor_coverage")
    upside = V.get("upside_pct")
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

    gate = _forensic_gate(asset, cfg)
    rating = min(a_raw, gate["cap"])
    rating = _clamp(rating, 0.0, 10.0)
    ribbon = _confidence_ribbon(asset, cfg)
    band = _band_label(rating, cfg)
    directive = _directive(asset, rating, gate, V)

    return {
        "ticker": asset.get("ticker"),
        "archetype": archetype,
        "archetype_code": asset.get("archetype_code"),
        "rating": round(rating, 2),
        "rating_raw": round(a_raw, 2),
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
    }
    if meta:
        out["context"] = meta
    return out
