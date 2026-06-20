"""
Electrification-vehicle replacement work-up (action-plan P5.3).

The P3 scenario engine flags the **scenario-C / uranium hole**: the book is structurally under-hedged
to the AI-productivity-WIN + reflation, and the electrification-royalty slot (URC.TO) is its only real
C/D hedge. This module is the structured work-up for replacing or augmenting that slot — the
**slot-fit-first screen** the cockpit manual mandates before any rotation.

The slot test (from the operating manual) is TWO gates, in order:
  1. **electrification exposure** — exposure to the electrification trade (U / Cu / Co / Ni / Li /
     graphite / rare earths / grid), and
  2. **ballast stability** — a STRUCTURAL vehicle (royalty · streamer · physical holding · diversified
     holdco) that keeps ballast stability; **NOT a direct operator**, and **NOT a volatile pure-spot-metal
     beta**. The test is *electrification exposure + ballast stability* — a physical/holding vehicle FITS;
     a volatile spot-metal operator does NOT, however cheap.

Slot-fit is non-negotiable and comes FIRST; valuation only decides *which* fitter wins. A candidate
that fails either gate is flagged **slot-mismatch** even with strong valuation. The work-up ranks the
fitters against the incumbent and returns SWAP-CANDIDATE / AUGMENT / HOLD — feeding `/rotate` (it never
rotates on its own). Pure + dependency-free; weights tunable via /confirm (`electrification_workup.*`).
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["ELECTRIFICATION_METALS", "STRUCTURAL_VEHICLES", "OPERATOR_VEHICLES",
           "DEFAULT_WORKUP_CONFIG", "WORKUP_GLOSSARY", "workup_tooltip", "slot_fit", "workup"]

#: The electrification trade (gate 1). Aliases included so loose inputs resolve.
ELECTRIFICATION_METALS = {"uranium", "u", "u3o8", "copper", "cu", "cobalt", "co", "nickel", "ni",
                          "lithium", "li", "graphite", "rare earth", "rare earths", "ree",
                          "grid", "transmission", "electrification"}
#: Structural (ballast) vehicles that PASS gate 2.
STRUCTURAL_VEHICLES = {"royalty", "streamer", "royalty/streamer", "physical", "physical_holding",
                       "physical holding", "holding", "holdco", "diversified_holdco",
                       "diversified holdco", "trust", "physical_trust"}
#: Operator-like vehicles that FAIL gate 2 (a direct operator is not ballast).
OPERATOR_VEHICLES = {"operator", "miner", "producer", "explorer", "developer", "mine"}

DEFAULT_WORKUP_CONFIG: dict[str, Any] = {
    "weights": {"stability": 0.45, "exposure_breadth": 0.30, "valuation": 0.25},
    "stability_score": {"royalty": 1.0, "streamer": 1.0, "physical_holding": 0.95, "trust": 0.9,
                        "diversified_holdco": 0.8, "holdco": 0.75, "holding": 0.85, "default": 0.6},
    "swap_margin": 0.08,            # a challenger must beat the incumbent's score by this to be SWAP
}

WORKUP_GLOSSARY: dict[str, dict[str, str]] = {
    "electrification_workup": {
        "what": "The slot-fit-first replacement work-up for the electrification-royalty slot (the scenario-C / uranium hole). Two gates — electrification exposure + ballast stability — then rank the fitters vs the incumbent.",
        "scale": "Per candidate: slot-FIT or slot-MISMATCH; fitters score on stability · exposure breadth · valuation.",
        "influence": "Feeds /rotate — SWAP-CANDIDATE / AUGMENT / HOLD. Slot-fit is non-negotiable and comes before valuation.",
        "edge": "A volatile pure-spot-metal operator is a MISMATCH however cheap; a physical/holding vehicle fits.",
    },
}


def workup_tooltip(key: str) -> str:
    e = WORKUP_GLOSSARY.get(key)
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


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _metals(candidate: dict) -> list[str]:
    c = candidate.get("commodities") or candidate.get("commodity") or []
    if isinstance(c, str):
        c = [c]
    return [_norm(x) for x in c]


def _exposure_hits(metals: list[str]) -> list[str]:
    return sorted({m for m in metals if m in ELECTRIFICATION_METALS})


def slot_fit(candidate: dict, *, config: Optional[dict] = None) -> dict:
    """Apply the two-gate electrification slot test to one candidate. Returns ``{ticker, fit, gates,
    verdict, exposure}``. Gate order: electrification exposure, then ballast stability."""
    vehicle = _norm(candidate.get("vehicle"))
    metals = _metals(candidate)
    hits = _exposure_hits(metals)

    # gate 1 — electrification exposure
    g1 = bool(hits)
    gates = [{"gate": "electrification_exposure", "pass": g1,
              "reason": (f"exposure: {', '.join(hits)}" if g1 else "no electrification-metal exposure")}]

    # gate 2 — ballast stability (structural vehicle, not operator, not a volatile pure-spot beta)
    is_structural = any(v in vehicle for v in STRUCTURAL_VEHICLES)
    is_operator = any(v in vehicle for v in OPERATOR_VEHICLES)
    pure_spot = bool(candidate.get("pure_spot_beta")) or (
        _norm(candidate.get("volatility")) == "high" and not is_structural)
    g2 = bool(is_structural and not is_operator and not pure_spot)
    if not vehicle:
        g2 = False
        reason2 = "vehicle unknown — cannot confirm ballast stability"
    elif is_operator:
        reason2 = f"direct operator ({vehicle}) — not ballast"
    elif pure_spot:
        reason2 = "volatile pure-spot-metal beta — not ballast stability"
    elif is_structural:
        reason2 = f"structural vehicle ({vehicle}) — ballast stable"
    else:
        reason2 = f"vehicle '{vehicle}' not a recognized structural/ballast vehicle"
    gates.append({"gate": "ballast_stability", "pass": g2, "reason": reason2})

    fit = bool(g1 and g2)
    return {"ticker": candidate.get("ticker"), "fit": fit,
            "verdict": "slot-FIT" if fit else "slot-MISMATCH", "gates": gates, "exposure": hits}


def _stability_score(vehicle: str, cfg: dict) -> float:
    table = cfg["stability_score"]
    for key, val in table.items():
        if key != "default" and key.replace("_", " ") in vehicle.replace("_", " "):
            return float(val)
    return float(table["default"])


def _score(candidate: dict, fit: dict, cfg: dict) -> dict:
    w = cfg["weights"]
    vehicle = _norm(candidate.get("vehicle"))
    stability = _stability_score(vehicle, cfg)
    breadth = min(1.0, len(fit["exposure"]) / 3.0)           # 3+ electrification metals = full breadth
    # valuation: prefer a discount-to-NAV or a low P/NAV when supplied; neutral 0.5 if absent
    val = 0.5
    disc = _num(candidate.get("discount_to_nav"))
    pnav = _num(candidate.get("p_nav"))
    if disc is not None:
        val = max(0.0, min(1.0, disc / 0.40))                # 40% discount = full marks
    elif pnav is not None and pnav > 0:
        val = max(0.0, min(1.0, (1.5 - pnav) / 1.0))         # P/NAV 0.5→1.0 .. 1.5→0.0
    score = w["stability"] * stability + w["exposure_breadth"] * breadth + w["valuation"] * val
    return {"score": round(score, 4), "stability": round(stability, 3),
            "exposure_breadth": round(breadth, 3), "valuation": round(val, 3)}


def workup(candidates: Optional[list], *, incumbent: Optional[dict] = None,
           config: Optional[dict] = None) -> dict:
    """Run the replacement work-up. ``candidates``: list of candidate dicts ({ticker, vehicle,
    commodities, volatility?, discount_to_nav?/p_nav?}). ``incumbent``: the held name's dict (defaults
    to URC.TO). Returns the screened candidates, the fitters ranked, the mismatches, and a
    SWAP/AUGMENT/HOLD recommendation feeding /rotate."""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_WORKUP_CONFIG.items()}
    block = (config or {}).get("electrification_workup", {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v

    inc = incumbent or {"ticker": "URC.TO", "vehicle": "royalty",
                        "commodities": ["uranium"], "volatility": "low"}
    inc_fit = slot_fit(inc, config=config)
    inc_score = _score(inc, inc_fit, cfg) if inc_fit["fit"] else {"score": 0.0}

    screened, fitters, mismatches = [], [], []
    for c in (candidates or []):
        if not isinstance(c, dict) or not c.get("ticker"):
            continue
        f = slot_fit(c, config=config)
        row = {**f}
        if f["fit"]:
            row.update(_score(c, f, cfg))
            fitters.append(row)
        else:
            mismatches.append(row)
        screened.append(row)

    fitters.sort(key=lambda x: x["score"], reverse=True)
    best = fitters[0] if fitters else None

    # recommendation — slot-fit first, then the score-edge vs the incumbent
    if not best:
        rec, why = "HOLD", f"no slot-fitting challenger — keep {inc['ticker']}"
    elif best["score"] >= inc_score["score"] + float(cfg["swap_margin"]):
        rec, why = "SWAP-CANDIDATE", (f"{best['ticker']} fits the slot and out-scores {inc['ticker']} "
                                      f"({best['score']:.2f} vs {inc_score['score']:.2f}) — take to /rotate")
    elif set(best["exposure"]) - set(inc_fit.get("exposure", [])):
        extra = sorted(set(best["exposure"]) - set(inc_fit.get("exposure", [])))
        rec, why = "AUGMENT", (f"{best['ticker']} fits and adds exposure {', '.join(extra)} the incumbent "
                               f"lacks — consider augmenting, not swapping")
    else:
        rec, why = "HOLD", f"no fitter beats {inc['ticker']} by the swap margin — hold the incumbent"

    return {"incumbent": {"ticker": inc["ticker"], "fit": inc_fit["fit"], **inc_score},
            "candidates": screened, "fitters": fitters, "mismatches": [m["ticker"] for m in mismatches],
            "best_fit": (best["ticker"] if best else None), "recommendation": rec, "rationale": why,
            "feeds": "/rotate", "glossary": {k: workup_tooltip(k) for k in WORKUP_GLOSSARY},
            "note": "slot-fit is non-negotiable and comes before valuation; this never rotates on its own"}
