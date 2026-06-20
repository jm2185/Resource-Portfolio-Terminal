"""
Ballast upside-measurement frameworks (action-plan P5.2) — GROY & GMX.

The spear's upside is option-convexity (the ρ payoff diagram). The ballast names do NOT work that way,
and measuring them with the spear's lens flatters or buries them. Their upside is **structural and
durable**, decomposed into named legs:

  * **GROY (gold-royalty-ballast)** — royalty cash-flow / GEO growth, gold-price leverage, and a P/NAV
    re-rate toward peers. Base = operational growth (no re-rate); bull = base + the re-rate.
  * **GMX (project-generator-holdco)** — portfolio NAV growth, the holdco discount closing toward a
    target, and discovery optionality. Base = NAV growth + discount-close; bull = base + the discovery
    kicker (small probability × large payoff).

Each framework returns the legs (with their % contribution), a base/bull upside range, and the key
driver — the ballast analog of the spear's asymmetry, so the desk sizes the ballast on its OWN merits.
Pure + dependency-free; betas/targets tunable via /confirm (`upside_framework.*`). No eval(); graceful
on partial inputs (a missing leg is simply omitted, never invented).
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_UPSIDE_CONFIG", "UPSIDE_GLOSSARY", "upside_tooltip",
           "groy_upside", "gmx_upside", "assess"]

DEFAULT_UPSIDE_CONFIG: dict[str, Any] = {
    "groy": {"gold_beta": 1.0, "default_target_pnav": 1.0},   # royalty NAV leverage to gold; peer P/NAV
    "gmx": {"default_target_discount": 0.20},                  # a healthy holdco trades ~20% below NAV
}

UPSIDE_GLOSSARY: dict[str, dict[str, str]] = {
    "upside_framework": {
        "what": "The ballast upside lens — GROY/GMX upside decomposed into structural legs (cash-flow growth, re-rate, discount-close, discovery), NOT the spear's option-convexity.",
        "scale": "Per name: a base upside (operational/structural) and a bull upside (base + the re-rate / discovery kicker), in %.",
        "influence": "Sizes the ballast on its own merits so it isn't measured (and under-weighted) against the spear's convex payoff.",
        "edge": "Ballast upside is modest + DURABLE by design; the point is reliability, not a convex tail.",
    },
    "groy_upside": {
        "what": "GROY upside = royalty cash-flow / GEO growth + gold-price leverage + a P/NAV re-rate.",
        "scale": "Base = growth + gold leverage (no re-rate); bull adds the re-rate toward the peer P/NAV.",
        "influence": "The ballast's structural return path; pairs with its low scenario dispersion (P3).",
    },
    "gmx_upside": {
        "what": "GMX upside = portfolio NAV growth + the holdco discount closing + discovery optionality.",
        "scale": "Base = NAV growth + discount-close; bull adds the discovery kicker.",
        "influence": "The project-generator return path; the discount-close is the most reliable leg.",
    },
}


def upside_tooltip(key: str) -> str:
    e = UPSIDE_GLOSSARY.get(key)
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


def _cfg(config: Optional[dict], key: str) -> dict:
    base = dict(DEFAULT_UPSIDE_CONFIG[key])
    block = (config or {}).get("upside_framework", {}) if config else {}
    if isinstance(block, dict) and isinstance(block.get(key), dict):
        base.update(block[key])
    return base


def _pack(legs: list, base_names: set, bull_names: set, framework: str) -> dict:
    legs = [l for l in legs if l is not None and _num(l.get("pct")) is not None]
    base = round(sum(l["pct"] for l in legs if l["name"] in base_names), 2)
    bull = round(sum(l["pct"] for l in legs if l["name"] in (base_names | bull_names)), 2)
    key = max(legs, key=lambda l: l["pct"])["name"] if legs else None
    return {"framework": framework, "legs": [{"name": l["name"], "pct": round(l["pct"], 2),
                                              "note": l.get("note", "")} for l in legs],
            "base_upside_pct": base, "bull_upside_pct": bull, "key_driver": key}


def groy_upside(*, geo_growth_pct: Any = None, gold_upside_pct: Any = None,
                current_pnav: Any = None, target_pnav: Any = None, config: Optional[dict] = None) -> dict:
    """GROY upside decomposition. ``geo_growth_pct``: forward GEO/cash-flow growth; ``gold_upside_pct``:
    the gold scenario move; ``current_pnav``/``target_pnav``: P/NAV now vs the peer target. All optional."""
    cfg = _cfg(config, "groy")
    legs = []
    g = _num(geo_growth_pct)
    if g is not None:
        legs.append({"name": "royalty cash-flow / GEO growth", "pct": g, "note": "NAV accretion from GEOs"})
    au = _num(gold_upside_pct)
    if au is not None:
        beta = float(cfg["gold_beta"])
        legs.append({"name": "gold price leverage", "pct": au * beta, "note": f"gold ×{beta:g} royalty beta"})
    cp, tp = _num(current_pnav), _num(target_pnav if target_pnav is not None else cfg["default_target_pnav"])
    if cp and cp > 0 and tp is not None:
        legs.append({"name": "P/NAV re-rate", "pct": (tp / cp - 1.0) * 100.0,
                     "note": f"P/NAV {cp:g}→{tp:g}"})
    out = _pack(legs, {"royalty cash-flow / GEO growth", "gold price leverage"}, {"P/NAV re-rate"}, "GROY")
    out.update({"glossary": {k: upside_tooltip(k) for k in ("upside_framework", "groy_upside")}})
    return out


def gmx_upside(*, nav_growth_pct: Any = None, current_discount: Any = None, target_discount: Any = None,
               discovery_option_pct: Any = None, config: Optional[dict] = None) -> dict:
    """GMX upside decomposition. ``nav_growth_pct``: portfolio NAV growth; ``current_discount`` /
    ``target_discount``: holdco discount-to-NAV now vs target (fractions, e.g. 0.35); ``discovery_option_pct``:
    the discovery optionality kicker. All optional."""
    cfg = _cfg(config, "gmx")
    legs = []
    nv = _num(nav_growth_pct)
    if nv is not None:
        legs.append({"name": "portfolio NAV growth", "pct": nv, "note": "deals / royalty additions"})
    cd = _num(current_discount)
    td = _num(target_discount if target_discount is not None else cfg["default_target_discount"])
    if cd is not None and td is not None and (1.0 - cd) > 0:
        # price = NAV·(1−discount); closing the discount lifts price by (1−td)/(1−cd) − 1
        legs.append({"name": "holdco discount close", "pct": ((1.0 - td) / (1.0 - cd) - 1.0) * 100.0,
                     "note": f"discount {cd:.0%}→{td:.0%}"})
    do = _num(discovery_option_pct)
    if do is not None:
        legs.append({"name": "discovery optionality", "pct": do, "note": "small prob × large payoff"})
    out = _pack(legs, {"portfolio NAV growth", "holdco discount close"}, {"discovery optionality"}, "GMX")
    out.update({"glossary": {k: upside_tooltip(k) for k in ("upside_framework", "gmx_upside")}})
    return out


def assess(target: str, inputs: Optional[dict] = None, *, config: Optional[dict] = None) -> dict:
    """Dispatch by ticker or slot to the right ballast framework. ``target`` ∈ {GROY,
    gold-royalty-ballast, GMX.TO, project-generator-holdco}. ``inputs`` are the framework kwargs."""
    inputs = inputs or {}
    t = str(target or "").upper()
    if t in ("GROY", "GOLD-ROYALTY-BALLAST"):
        return groy_upside(**inputs, config=config)
    if t in ("GMX.TO", "GMX", "PROJECT-GENERATOR-HOLDCO"):
        return gmx_upside(**inputs, config=config)
    return {"framework": None, "legs": [], "base_upside_pct": None, "bull_upside_pct": None,
            "key_driver": None, "note": f"no ballast upside framework for {target!r} (spear uses ρ/φ asymmetry)"}
