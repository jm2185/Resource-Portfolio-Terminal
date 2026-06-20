"""
Two-lens regime split (Regime Engine v2, G1+G2) — fix interpretation, not data.

The blended MRI / macro-tape vote mixes two regimes into one tally: broad-market risk appetite (VIX,
vol term, HY, SOFR, CFTC) and the metals-specific environment (real yield, DXY/gold, GSR, copper/gold,
the curve tell). They can point opposite ways — a high real yield is risk-*on* for the broad economy
but a risk-*off* headwind for metals — so the broad majority buries the metals minority and the panel
prints a reassuring "RISK-ON" while the signals that actually drive a concentrated metals book flash
caution. This module splits the read into **two same-lens sub-scores that render side by side**:

  * **Broad-Market Risk** — VIX · VIX term · HY spread · SOFR spread · CFTC. "Is the market fearful?"
  * **Metals Regime** — real yield · DXY/gold · gold/silver · copper/gold · the curve tell · DXY.
    "Is the environment supporting the metals book?" **This is the lens that drives conviction**; broad
    risk is context. They are NOT re-blended — the disagreement IS the signal.

G2: the curve signal is driven by the SAME `bear_steepener` flag the P2.1 rates dashboard and the P3
scenario engine consume (no divergent curve interpretation possible). A firing bear-steepener registers
as the fiscal-dominance tell it is (a metals-regime caution + scenario-B nudge); a flat / bull-steepening
curve stays dormant.

Pure + dependency-free; one-directional (reads the same inputs P3 uses, never recomputes them). Lens
weights are config (`regime_lens.weights`, proposal-gated) — default is equal-weight vote-counting.
No `eval()`; graceful on thin inputs.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["LENS", "DEFAULT_REGIME_LENS_CONFIG", "REGIME_LENS_GLOSSARY", "regime_lens_tooltip", "assess"]

#: Each macro-tape signal belongs to exactly ONE lens (no signal feeds both).
LENS: dict[str, str] = {
    # broad-market risk appetite
    "vix": "broad", "vix_term": "broad", "hy_spread": "broad", "sofr_spread": "broad", "cftc": "broad",
    # metals-specific environment
    "real_yield": "metals", "dxy_gold": "metals", "gsr": "metals", "cu_au": "metals",
    "curve_2s30s": "metals", "dxy": "metals",
}

DEFAULT_REGIME_LENS_CONFIG: dict[str, Any] = {
    # equal-weight by default (vote-counting). A book whose thesis is real-yield/curve-sensitive may
    # weight those up — that is config, human-approved (proposal-gated), never silent.
    "weights": {k: 1.0 for k in LENS},
    "tilt_band": 0.20,                 # |tilt| <= band -> NEUTRAL/MIXED; outside -> on/off
    "gsr_cheap": 85.0,                 # GSR above this = silver very cheap (deep setup, supportive level)
}

REGIME_LENS_GLOSSARY: dict[str, dict[str, str]] = {
    "broad": {
        "what": "Broad-Market Risk lens — VIX, VIX term, HY spread, SOFR spread, CFTC. Is the market fearful or greedy?",
        "scale": "RISK-ON (calm/greedy) · NEUTRAL · RISK-OFF (fearful). CONTEXT for a metals book, not the driver.",
        "influence": "Context only. Can legitimately diverge from the metals lens — the divergence is the signal, not an error.",
    },
    "metals": {
        "what": "Metals Regime lens — real yield, DXY/gold, gold/silver, copper/gold, the curve tell, DXY. Is the environment supporting the metals book?",
        "scale": "SUPPORTIVE · MIXED · HEADWIND. THIS lens drives conviction for the book.",
        "influence": "Foregrounded read for the concentrated metals book; shares the curve tell with the P2.1 bear-steepener and scenario weight B (one source, no divergence).",
        "edge": "A high real yield is risk-ON for the broad economy but a HEADWIND here — the two lenses can disagree by design.",
    },
}


def regime_lens_tooltip(key: str) -> str:
    e = REGIME_LENS_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Reads: ", "influence": "Role: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _metals_signal(key: str, value: Optional[float], bear_steepener: bool, cfg: dict) -> tuple[float, str]:
    """Metals-lens interpretation of one signal → (score in [-1,1], corrected read). Re-derived from
    the raw value (not the blended bias) so the metals read is self-consistent and G3-correct."""
    v = _num(value)
    if key == "real_yield":
        if v is None:
            return 0.0, "real yield n/a"
        return (-1.0, "Headwind — elevated real yield") if v > 2.0 else (
            (1.0, "Tailwind — low real yield") if v < 0.5 else (0.0, "Neutral real yield"))
    if key == "dxy_gold":                       # DXY/Gold×1k: LOW = gold strong vs $ (metals-supportive)
        if v is None:
            return 0.0, "DXY/gold n/a"
        return (1.0, "Gold strong vs dollar (supportive)") if v < 45 else (-1.0, "Dollar strong vs gold (headwind)")
    if key == "dxy":
        if v is None:
            return 0.0, "DXY n/a"
        return (-1.0, "Strong dollar (headwind)") if v > 104 else ((1.0, "Soft dollar (supportive)") if v < 100 else (0.0, "Neutral dollar"))
    if key == "cu_au":                           # G3: copper's level is supply-driven — caveat, don't score clean reflation
        if v is None:
            return 0.0, "copper/gold n/a"
        return (0.0, "Reflation bid — supply-contaminated (caveat, not a clean read)") if v > 1.5 else (-1.0, "Defensive / slowdown")
    if key == "gsr":                             # G3: LEVEL only (no leadership claim); high GSR = silver cheap (setup)
        if v is None:
            return 0.0, "GSR n/a"
        if v > cfg.get("gsr_cheap", 85.0):
            return 1.0, "Silver very cheap vs gold (deep setup)"
        return 0.0, "Silver relatively cheap vs gold (level; direction not asserted)"
    if key == "curve_2s30s":                     # G2: driven by the SAME bear_steepener flag as P2.1/P3
        if bear_steepener:
            return -1.0, "Bear-steepener — fiscal-dominance tell (caution; feeds scenario B)"
        return 0.0, "Curve dormant (no bear-steepener)"
    return 0.0, "—"


def _broad_score(bias: Any) -> float:
    b = str(bias or "").lower()
    return 1.0 if b == "risk_on" else (-1.0 if b == "risk_off" else 0.0)


def _aggregate(rows: list, cfg: dict) -> tuple[float, list]:
    weights = cfg.get("weights", {})
    num = den = 0.0
    for r in rows:
        w = float(weights.get(r["key"], 1.0))
        num += w * r["score"]
        den += w
    return (num / den if den else 0.0), rows


def assess(macro_tape: Any, *, bear_steepener: Optional[bool] = None,
           rates: Optional[dict] = None, config: Optional[dict] = None) -> dict:
    """Split the macro tape into the two lenses. ``macro_tape``: the list of tape signals (or the
    {"signals": [...]} dict). ``bear_steepener`` (or ``rates['bear_steepener']['active']``) wires G2.
    Returns the two sub-scores side by side, the divergence flag, and tooltips."""
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_REGIME_LENS_CONFIG.items()}
    block = (config or {}).get("regime_lens", {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v

    sigs = macro_tape.get("signals") if isinstance(macro_tape, dict) else macro_tape
    sigs = sigs or []
    if bear_steepener is None and isinstance(rates, dict):
        bear_steepener = bool((rates.get("bear_steepener") or {}).get("active"))
    bear_steepener = bool(bear_steepener)

    broad_rows, metals_rows = [], []
    for s in sigs:
        if not isinstance(s, dict):
            continue
        key = s.get("key")
        lens = LENS.get(key)
        if lens == "broad":
            broad_rows.append({"key": key, "label": s.get("label"), "score": _broad_score(s.get("bias")),
                               "read": s.get("read"), "value": s.get("value")})
        elif lens == "metals":
            sc, read = _metals_signal(key, s.get("value"), bear_steepener, cfg)
            metals_rows.append({"key": key, "label": s.get("label"), "score": sc, "read": read,
                                "value": s.get("value")})

    band = float(cfg.get("tilt_band", 0.20))
    broad_tilt, _ = _aggregate(broad_rows, cfg)
    metals_tilt, _ = _aggregate(metals_rows, cfg)

    def _label(tilt, pos, mid, neg):
        return pos if tilt > band else (neg if tilt < -band else mid)

    broad_label = _label(broad_tilt, "RISK-ON", "NEUTRAL", "RISK-OFF")
    metals_label = _label(metals_tilt, "SUPPORTIVE", "MIXED", "HEADWIND")
    # divergence: broad benign while metals is not clearly supportive (or outright opposite signs)
    divergence = (broad_label == "RISK-ON" and metals_label in ("MIXED", "HEADWIND")) or \
                 (broad_tilt > band and metals_tilt < -band)

    return {
        "broad": {"label": broad_label, "tilt": round(broad_tilt, 3),
                  "score": round(50 + 50 * broad_tilt, 1), "role": "context", "signals": broad_rows},
        "metals": {"label": metals_label, "tilt": round(metals_tilt, 3),
                   "score": round(50 + 50 * metals_tilt, 1), "role": "drives_conviction",
                   "drives_conviction": True, "signals": metals_rows},
        "divergence": bool(divergence),
        "divergence_note": ("broad risk-on masks a metals headwind — read the metals lens"
                            if divergence else "lenses broadly agree"),
        "curve_tell": {"bear_steepener": bear_steepener,
                       "shared_with": "rates_dashboard.bear_steepener + scenario.weights.B"},
        "drives_conviction": "metals",
        "glossary": {k: regime_lens_tooltip(k) for k in REGIME_LENS_GLOSSARY},
        "note": "two same-lens sub-scores, never re-blended — the divergence is the signal, not an error",
    }
