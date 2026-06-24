"""
quality_lenses.py — archetype-NATIVE company quality (the Q-pillar's quality leg).

The resource checklist (grade · ounces · recovery · drill stage) is the right read for an EXPLORER and
the wrong one for a royalty or a holdco: a royalty company has no head grade, a project-generator
holdco's quality is its balance sheet and capital allocation, not a drill result. Firing the explorer
checklist at them — or, worse, echoing market_confidence — is the bug CLAUDE.md names ("a silver-
explorer triage fired at a gold royalty is a bug, not a shortcut"). And because asset_light_yield
weights Q at 0.55, that proxy was the DOMINANT pillar for the entire ballast book.

So pick the lens SET by profile (archetype · subarchetype) and score each lens from the most OBJECTIVE
sourced input available — counts, fractions, dilution rates, coverage ratios — never a judgment number:

  ROYALTY  (cash-flowing royalty company): diversification · operator_quality · structure_quality ·
           cashflow_coverage · accretion  (accretion = the dilution discipline the proxy was blind to)
  HOLDCO   (project-/royalty-generator):   portfolio_breadth · balance_sheet · capital_allocation ·
           cashflow_coverage              (balance sheet dominant — a debt-free vault IS the quality)

The bands/weights live here (pure, tested, tunable); the inputs are FED quarterly via research_cache
(the holdco_nav pattern), so nothing is hardcoded. A missing input DROPS its lens and renormalizes the
weights over what's present (never invent); a profile with no usable input returns ``available=False``
so the Q pillar degrades LOUDLY (quality_proxy_only) rather than faking a read. Explorer/other archetypes
return available=False by design — they keep the resource checklist. Dependency-free.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_QUALITY_LENS_CONFIG", "quality_lenses_for", "lens_set_for", "is_holdco", "is_royalty"]

# Each lens: (input_key, kind, lo, hi). kind 'band' scores (x-lo)/(hi-lo) clamped; 'inv_band' scores
# 1-that (lower raw is better, e.g. dilution); 'unit' takes a 0..1 input straight. Weights sum to 1.
DEFAULT_QUALITY_LENS_CONFIG: dict[str, Any] = {
    "royalty": {
        "lenses": {
            "diversification":   {"input": "producing_royalty_count", "kind": "band", "lo": 1, "hi": 12, "w": 0.20},
            "operator_quality":  {"input": "tier1_operator_fraction", "kind": "unit", "w": 0.25},
            "structure_quality": {"input": "top_line_fraction",       "kind": "unit", "w": 0.20},
            "cashflow_coverage": {"input": "cashflow_coverage",       "kind": "band", "lo": 0.5, "hi": 3.0, "w": 0.15},
            # accretion: the per-share discipline. Heavy share growth (issue-to-buy) = LOW quality even
            # on a great royalty book — the exact nuance market_confidence erased for GROY.
            "accretion":         {"input": "share_growth_rate",       "kind": "inv_band", "lo": 0.0, "hi": 0.30, "w": 0.20},
        },
    },
    "holdco": {
        "lenses": {
            "portfolio_breadth": {"input": "asset_count",        "kind": "band", "lo": 10, "hi": 300, "w": 0.20},
            # balance_sheet: net liquid (cash + marketable securities − debt) as a share of market cap —
            # a debt-free vault (GMX) scores high; this IS the holdco's hard quality.
            "balance_sheet":     {"input": "net_liquid_to_mktcap", "kind": "band", "lo": 0.0, "hi": 0.5, "w": 0.35},
            "capital_allocation": {"input": "share_growth_rate", "kind": "inv_band", "lo": 0.0, "hi": 0.30, "w": 0.25},
            # coverage runs LOW for a project generator (recurring income < G&A by design) — kept so the
            # score tells the truth about self-funding rather than hiding the one real weakness.
            "cashflow_coverage": {"input": "cashflow_coverage", "kind": "band", "lo": 0.3, "hi": 2.0, "w": 0.20},
        },
    },
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def is_holdco(profile: dict) -> bool:
    """A project-/royalty-generator holdco: its value is NAV + discovery optionality, not recurring
    NSR cash flow. Detected on the subarchetype (the 3rd taxonomy axis), matching the stability
    override and the cockpit's HOLDCO label."""
    sub = str((profile or {}).get("subarchetype") or "").lower()
    return ("holdco" in sub) or ("generator" in sub)


def is_royalty(profile: dict) -> bool:
    """A cash-flowing royalty company — asset_light_yield that is NOT a generator holdco."""
    return str((profile or {}).get("archetype") or "") == "asset_light_yield" and not is_holdco(profile)


def lens_set_for(profile: dict) -> Optional[str]:
    """Which lens set fits this profile: 'holdco', 'royalty', or None (explorer/other → resource
    checklist). Holdco is checked first so a royalty-generator holdco never reads as a plain royalty."""
    if is_holdco(profile):
        return "holdco"
    if is_royalty(profile):
        return "royalty"
    return None


def _score_lens(spec: dict, inputs: dict) -> Optional[float]:
    raw = _num(inputs.get(spec["input"]))
    if raw is None:
        return None
    kind = spec.get("kind", "unit")
    if kind == "unit":
        return _clamp01(raw)
    lo, hi = float(spec.get("lo", 0.0)), float(spec.get("hi", 1.0))
    band = _clamp01((raw - lo) / (hi - lo)) if hi > lo else 0.0
    return (1.0 - band) if kind == "inv_band" else band


def quality_lenses_for(profile: dict, inputs: dict, config: Optional[dict] = None) -> dict:
    """Score a name on its archetype-native quality lenses. Returns ``available`` (False ⇒ no lens set
    for this archetype, or no input present ⇒ caller keeps the resource checklist / proxy and flags it),
    the blended ``q_a`` in [0,1], the per-lens ``lenses``, the renormalized ``weights`` actually used,
    a ``basis`` tag, and ``missing`` (lenses whose input wasn't fed — the quarterly to-do). Pure."""
    lset = lens_set_for(profile)
    out: dict[str, Any] = {"available": False, "basis": None, "lens_set": lset,
                           "lenses": {}, "weights": {}, "missing": []}
    if lset is None:
        return out                                   # explorer / other → not our job (resource checklist)
    cfg = ((config or {}).get("quality_lenses", config or {}) or {})
    spec_block = (cfg.get(lset) or DEFAULT_QUALITY_LENS_CONFIG[lset])["lenses"]
    inputs = inputs or {}
    scores: dict[str, float] = {}
    weights: dict[str, float] = {}
    missing: list[str] = []
    for name, spec in spec_block.items():
        s = _score_lens(spec, inputs)
        if s is None:
            missing.append(name)
            continue
        scores[name] = round(s, 3)
        weights[name] = float(spec.get("w", 1.0))
    if not scores:                                   # no input fed yet → degrade loudly, don't fake
        out["missing"] = missing
        return out
    tot = sum(weights.values()) or 1.0
    q_a = sum(scores[k] * weights[k] for k in scores) / tot
    out.update({"available": True, "basis": f"{lset}_lenses", "q_a": round(_clamp01(q_a), 3),
                "lenses": scores, "weights": {k: round(weights[k] / tot, 3) for k in weights},
                "missing": missing})
    return out
