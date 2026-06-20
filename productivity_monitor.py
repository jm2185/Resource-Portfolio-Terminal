"""
AI-productivity monitor (action-plan P2.2) — the thesis-breaker watch.

The debasement tilt is a BET that the economy stays in the "real-but-narrow" goldilocks zone:
genuine productivity gains, but **concentrated in a few industries** (validates the pick-and-shovel
demand thesis while leaving the monetary-debasement tilt intact). The thesis BREAKS if productivity
goes **broad AND accelerating** — a sustained, broadening climb toward ~2%+ output/hour is the
muddle-through-WIN (scenario C) that lets the system grow out of its debt without debasing, gutting
the metals tilt.

So this watches the two variables that separate the two worlds:
  * **breadth**     — concentrated in a few industries (narrow → goldilocks) vs broadening (→ risk).
  * **trajectory**  — settling back toward trend (benign) vs accelerating to a sustained ~2%+ (→ risk).

Sustained **broadening AND acceleration** trips the discrete flag:
  *"debasement thesis at risk — re-weight toward pick-and-shovel"*.
The composite `scenario_c_pressure` feeds the scenario weights in P3 (rising breadth raises C).

Sources (engine supplies the resolved series): BLS labor-productivity (output/hour) + revisions,
BEA GDP, job-count revisions vs GDP, Fed regional industry-decomposition. Pure + dependency-free
(stdlib only); every threshold is a reasoned first calibration, tunable via /confirm
(`productivity_monitor.*`). No eval(); robust to thin/missing data.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_PRODUCTIVITY_CONFIG", "PRODUCTIVITY_GLOSSARY", "productivity_tooltip", "assess"]

DEFAULT_PRODUCTIVITY_CONFIG: dict[str, Any] = {
    "sustain_level_pct": 2.0,      # output/hour growth at/above this (annualized) is "high / sustained"
    "accel_pp": 0.3,               # recent-half mean exceeds older-half mean by this -> accelerating
    "broad_threshold": 0.55,       # breadth score >= this is "broad" (not narrow/goldilocks)
    "broadening_pp": 0.05,         # breadth rose by this vs the prior reading -> broadening
    "c_weights": {"breadth": 0.5, "trajectory": 0.5},   # composite scenario-C pressure blend
    "c_bands": [[70.0, "BROAD-ACCELERATING"], [45.0, "BROADENING"],
                [20.0, "REAL-BUT-NARROW"], [0.0, "SOFT / BENIGN"]],
}

PRODUCTIVITY_GLOSSARY: dict[str, dict[str, str]] = {
    "productivity_monitor": {
        "what": "The AI-productivity thesis-breaker watch — is the economy in the real-but-narrow goldilocks zone (validates pick-and-shovel, debasement intact) or tipping broad+accelerating (scenario C, debasement at risk)?",
        "scale": "scenario-C pressure 0–100: SOFT/BENIGN <20 · REAL-BUT-NARROW 20–45 · BROADENING 45–70 · BROAD-ACCELERATING >70.",
        "influence": "Feeds the scenario weights (P3): rising breadth + acceleration raises the muddle-through-WIN scenario C, which invalidates the debasement tilt.",
        "edge": "It is a THESIS-BREAKER, not a buy signal — a high read says re-weight toward pick-and-shovel / trim the debasement bet.",
    },
    "prod_breadth": {
        "what": "Productivity breadth — is output/hour growth concentrated in a few industries (narrow) or broadening across many?",
        "scale": "0 = concentrated (goldilocks / pick-and-shovel intact) · 1 = broad-based. Derived from the industry decomposition (1 − normalized HHI).",
        "influence": "Half of the scenario-C composite; broadening is the key tell the win is generalizing.",
    },
    "prod_trajectory": {
        "what": "Productivity trajectory — settling back toward trend (benign) vs accelerating to a sustained ~2%+ output/hour.",
        "scale": "Accelerating = recent-half mean exceeds the older half by ≥ 0.3pp; sustained = recent mean ≥ ~2%.",
        "influence": "Half of the scenario-C composite; the second condition for the thesis-breaker flag.",
    },
    "debasement_at_risk": {
        "what": "The thesis-breaker flag — sustained BROADENING AND ACCELERATION together (the scenario-C signature).",
        "scale": "Active = breadth broad+broadening AND trajectory accelerating+sustained.",
        "influence": "The discrete alert: 'debasement thesis at risk — re-weight toward pick-and-shovel'.",
        "edge": "Needs BOTH conditions — broad-but-flat or narrow-but-accelerating alone does not break the thesis.",
    },
}


def productivity_tooltip(key: str) -> str:
    e = PRODUCTIVITY_GLOSSARY.get(key)
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


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _mean(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_PRODUCTIVITY_CONFIG)
    block = (config or {}).get("productivity_monitor", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def _breadth_from_contributions(contribs: Optional[dict]) -> Optional[float]:
    """Breadth in [0,1] = 1 − normalized HHI over the (positive) industry contributions. 1 = perfectly
    broad (every industry equal), 0 = all growth in one industry. None if unusable."""
    if not isinstance(contribs, dict) or not contribs:
        return None
    vals = [abs(_num(v) or 0.0) for v in contribs.values()]
    tot = sum(vals)
    n = len(vals)
    if tot <= 0 or n < 2:
        return None
    hhi = sum((v / tot) ** 2 for v in vals)               # 1/n (broad) .. 1 (concentrated)
    norm = (hhi - 1.0 / n) / (1.0 - 1.0 / n)               # 0 broad .. 1 concentrated
    return round(_clamp(1.0 - norm), 4)                    # flip so 1 = broad


def assess(productivity: Optional[list], *, breadth: Any = None,
           industry_contributions: Optional[dict] = None, breadth_prior: Any = None,
           config: Optional[dict] = None) -> dict:
    """Assess the AI-productivity regime.

    ``productivity``: recent output/hour growth readings (annualized %), oldest→newest (≥2 to read a
    trajectory). ``breadth``: a 0–1 breadth scalar, OR pass ``industry_contributions`` (dict
    industry→contribution) to derive it. ``breadth_prior``: the breadth one window ago (to detect
    broadening). All optional/graceful.
    """
    cfg = _cfg(config)
    series = [v for v in (_num(x) for x in (productivity or [])) if v is not None]

    # ---- trajectory ----------------------------------------------------------
    accelerating = sustained = None
    recent_mean = older_mean = None
    if len(series) >= 2:
        half = max(1, len(series) // 2)
        older_mean = _mean(series[:-half]) if len(series) > half else _mean(series[:half])
        recent_mean = _mean(series[-half:])
        if recent_mean is not None and older_mean is not None:
            accelerating = (recent_mean - older_mean) >= float(cfg["accel_pp"])
        if recent_mean is not None:
            sustained = recent_mean >= float(cfg["sustain_level_pct"])
    # trajectory score [0,1]: blends "how high" (vs sustain level) and "accelerating".
    traj_level = _clamp((recent_mean or 0.0) / max(1e-9, float(cfg["sustain_level_pct"]))) if recent_mean is not None else None
    traj_score = None
    if traj_level is not None:
        traj_score = _clamp(0.6 * traj_level + (0.4 if accelerating else 0.0))

    # ---- breadth -------------------------------------------------------------
    b_now = _num(breadth)
    if b_now is None:
        b_now = _breadth_from_contributions(industry_contributions)
    b_prior = _num(breadth_prior)
    broad = (b_now is not None and b_now >= float(cfg["broad_threshold"]))
    broadening = (b_now is not None and b_prior is not None
                  and (b_now - b_prior) >= float(cfg["broadening_pp"]))

    # ---- the thesis-breaker flag --------------------------------------------
    # BOTH conditions: breadth broad AND broadening, trajectory accelerating AND sustained.
    debasement_at_risk = bool(broad and broadening and accelerating and sustained)
    flags = []
    if debasement_at_risk:
        flags.append({"id": "debasement_at_risk", "active": True, "level": "risk",
                      "text": ("DEBASEMENT THESIS AT RISK — productivity broad + broadening AND "
                               "accelerating to sustained ~2%+ (scenario C) — re-weight toward pick-and-shovel")})

    # ---- composite scenario-C pressure (0..100) ------------------------------
    w = cfg["c_weights"]
    terms, used = [], []
    if b_now is not None:
        # broadening adds a kick beyond the static level
        b_term = _clamp(b_now + (0.15 if broadening else 0.0))
        terms.append((w["breadth"], b_term)); used.append("breadth")
    if traj_score is not None:
        terms.append((w["trajectory"], traj_score)); used.append("trajectory")
    wsum = sum(wt for wt, _ in terms)
    score = (100.0 * sum(wt * v for wt, v in terms) / wsum) if wsum > 0 else None
    label = None
    if score is not None:
        for thr, lab in cfg["c_bands"]:
            if score >= thr:
                label = lab
                break

    return {
        "trajectory": {"recent_mean": (round(recent_mean, 3) if recent_mean is not None else None),
                       "older_mean": (round(older_mean, 3) if older_mean is not None else None),
                       "accelerating": accelerating, "sustained": sustained,
                       "score": (round(traj_score, 4) if traj_score is not None else None),
                       "n": len(series)},
        "breadth": {"score": (round(b_now, 4) if b_now is not None else None),
                    "broad": broad, "broadening": broadening, "prior": b_prior},
        "zone": label,
        "scenario_c_pressure": {"score": (round(score, 1) if score is not None else None),
                                "label": label, "drivers": used,
                                "note": "feeds scenario C (muddle-through-WIN) — rising = debasement tilt at risk"},
        "flags": flags,
        "glossary": {k: productivity_tooltip(k) for k in PRODUCTIVITY_GLOSSARY},
        "upstream_note": "THESIS-BREAKER watch — a high read says re-weight toward pick-and-shovel, not buy.",
    }
