"""
Scenario-robustness engine (action-plan P3) — the convergence point.

The whole signal layer (P1 forward tailwind, P2 SENTINEL monitors) was built to feed THIS: a small,
explicit set of macro scenarios whose probability WEIGHTS are driven by the live signals, and a
per-name robustness score that asks the Druckenmiller question — *how does each holding do across the
whole distribution of futures, not just the one I'm rooting for?*

The four scenarios (the book must survive all of them):
  A · Managed debasement / financial repression   — the debasement tilt WINS   (driver: macro regime)
  B · Disorderly fiscal dominance / bear-steepener — crisis-hedge convexity     (driver: rates dash, P2.1)
  C · AI-productivity muddle-through-WIN           — debasement tilt INVALIDATED (driver: productivity, P2.2)
  D · Reflation / growth without debasement        — industrial metals bid       (driver: copper Cu/Au)

Two outputs:
  1. **scenario weights** — driven FROM the signals (a base house prior, tilted by each scenario's
     driver), normalized to 1. Rising productivity breadth raises C; a firing bear-steepener raises B.
  2. **per-name robustness** — `E[payoff] − λ·downside_dev` across the weighted scenarios. The penalty
     is DOWNSIDE semideviation (sub-mean futures only), NOT symmetric stdev: the all-weather question is
     "how bad are the bad futures", so a name is docked for a deep-negative scenario (the spear's C) but
     NEVER for a huge upside one (the spear's B) — penalizing upside convexity in a convexity book is the
     Markowitz error. It still rewards the all-weather ballast (GROY — positive in A/B, only mildly soft
     in C) OVER the spear (AGA.V — deeply negative in C), so **robustness ranks GROY #1** while the spear
     leads on raw single-scenario UPSIDE (reported separately so convexity is never buried) — but the gap
     reflects the spear's real DOWNSIDE, not its upside. A *different lens*, not a barbell replacement.

And one alarm: the **scenario-C / uranium hole** — when the C(+D) weight is non-trivial but the book's
C/D-winning exposure (the electrification-royalty slot) is thin, raise it. The book is structurally
under-hedged to the AI-productivity win; this makes that explicit instead of leaving it implicit.

Pure + dependency-free; one-directional (a consumer of the monitors, never a re-computer). Payoffs are
slot-derived defaults, overridable per name via `v5_config.json → portfolio_metadata[t].scenario_payoffs`.
Tunables live under `scenario_engine.*` (proposal-gated). No eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_SCENARIO_CONFIG", "SCENARIOS", "SCENARIO_KEYS", "SCENARIO_GLOSSARY",
           "scenario_tooltip", "DEFAULT_SLOT_PAYOFFS", "scenario_weights", "assess"]

SCENARIOS: dict[str, dict[str, str]] = {
    "A": {"name": "Managed debasement / financial repression",
          "thesis": "Real yields pinned low/negative, fiscal dominance managed via repression — the monetary-debasement tilt WINS.",
          "wins": "gold/silver, royalties", "loses": "cash, long duration",
          "driver": "macro regime — low/negative real yield + soft DXY"},
    "B": {"name": "Disorderly fiscal dominance / bear-steepener",
          "thesis": "The long end breaks, term premium spikes — crisis-hedge regime; convex upside for the spear, volatility everywhere.",
          "wins": "gold, convex silver, crisis hedges", "loses": "duration, credit",
          "driver": "rates dashboard (P2.1) — bear-steepener + fiscal-dominance"},
    "C": {"name": "AI-productivity muddle-through-WIN",
          "thesis": "Broad + accelerating productivity lets the system grow OUT of the debt without debasing — invalidates the debasement tilt.",
          "wins": "electrification/productivity beneficiaries, broad equities", "loses": "the debasement premium (gold/silver)",
          "driver": "productivity monitor (P2.2) — breadth × trajectory"},
    "D": {"name": "Reflation / growth without debasement",
          "thesis": "Cyclical growth and industrial-metals demand bid, but the precious-metal debasement premium compresses.",
          "wins": "copper/industrial metals, project generators", "loses": "pure debasement premium",
          "driver": "copper Cu/Au reflation"},
    "E": {"name": "Benign normalization / goldilocks",
          "thesis": "Real yields normalize POSITIVE, growth steady, no debasement, no crisis — the debasement premium just fades. Productive equities and cash-yield compound; a hard-asset book goes sideways. The future the all-resource book has no answer to.",
          "wins": "broad/quality equities, cash & short duration", "loses": "the debasement premium (gold/silver drift)",
          "driver": "inverse-stress — positive/normal real yield, low MRI, no bear-steepener"},
}

#: The live scenario set, data-driven so the count can grow (E added the benign/goldilocks future the
#: monetary-debasement scenarios A–D structurally omit — the critique's uncovered column).
SCENARIO_KEYS: tuple = ("A", "B", "C", "D", "E")

#: Per-scenario payoff (−1 deeply hurt … +1 strongly wins) by thesis slot — the house default. The E
#: column is the honest one: a hard-asset book is a mild headwind in benign normalization (no
#: debasement wind), and electrification is the one resource sleeve that still earns its keep there.
DEFAULT_SLOT_PAYOFFS: dict[str, dict[str, float]] = {
    "silver-spear":             {"A": 0.80, "B": 1.00, "C": -0.70, "D": 0.20, "E": -0.30},
    "gold-royalty-ballast":     {"A": 0.70, "B": 0.70, "C": -0.20, "D": 0.10, "E": -0.10},
    "project-generator-holdco": {"A": 0.40, "B": 0.10, "C": -0.10, "D": 0.50, "E": 0.05},
    "electrification-royalty":  {"A": 0.10, "B": 0.00, "C": 0.60,  "D": 0.70, "E": 0.30},
}
#: Coarser fallback by archetype when a name has no recognized slot.
DEFAULT_ARCHETYPE_PAYOFFS: dict[str, dict[str, float]] = {
    "convex_explorer":  {"A": 0.70, "B": 0.95, "C": -0.65, "D": 0.20, "E": -0.30},
    "royalty_streamer": {"A": 0.65, "B": 0.65, "C": -0.10, "D": 0.20, "E": -0.10},
    "project_generator":{"A": 0.40, "B": 0.10, "C": -0.10, "D": 0.50, "E": 0.05},
}

DEFAULT_SCENARIO_CONFIG: dict[str, Any] = {
    "base_prior": {"A": 0.30, "B": 0.20, "C": 0.18, "D": 0.15, "E": 0.17},  # house central case (debasement-tilted; E = the benign residual)
    "signal_gain": 0.60,            # how hard the live signals tilt the prior
    "dispersion_lambda": 0.50,      # robustness = E[payoff] − λ·downside_dev  (the all-weather penalty)
    "dispersion_mode": "downside",  # "downside" semideviation (penalize sub-mean futures only) | "full" (legacy symmetric stdev — docks upside convexity)
    "real_yield_pivot": 0.5,        # real yield at/below which scenario-A signal saturates toward 1
    "dxy_soft": 100.0,              # DXY below this adds a small managed-debasement (A) bump
    "cu_au_lo": 1.30, "cu_au_hi": 2.00,   # copper/gold ×1000 range mapping to the D signal
    "hole_c_weight": 0.18,          # scenario-C weight at/above this is "non-trivial"
    "hole_hedge_book_weight": 0.30, # C/D-winning book weight below this with high C ⇒ the hole
    "hedge_payoff_thr": 0.40,       # a name with payoff_C or payoff_D ≥ this counts as a C/D hedge
}

SCENARIO_GLOSSARY: dict[str, dict[str, str]] = {
    "scenario_engine": {
        "what": "The four-scenario robustness lens (A managed-debasement · B fiscal-dominance/bear-steepener · C AI-productivity-WIN · D reflation). Weights are driven by the live signals; names are scored on how they do ACROSS the distribution.",
        "scale": "Per name: robustness = probability-weighted E[payoff] − λ·dispersion. Higher = more all-weather.",
        "influence": "Surfaces the robust ballast vs the convex spear, and the book's scenario gaps — it informs sizing/hedging, it does NOT override the barbell.",
        "edge": "Robustness ≠ upside. The spear is MEANT to lose on robustness and win on single-scenario upside — both are reported.",
    },
    "scenario_weights": {
        "what": "The probability weights on A/B/C/D, driven from a house base prior tilted by the live signals (rates→B, productivity→C, macro→A, copper→D).",
        "scale": "Sum to 1. Rising productivity breadth raises C; a firing bear-steepener raises B.",
        "influence": "The probabilities the per-name robustness is weighted by; the upstream of every P3 number.",
    },
    "robustness": {
        "what": "A name's probability-weighted expected payoff MINUS a DOWNSIDE-dispersion penalty (λ·downside semideviation — sub-mean scenarios only) — the all-weather score.",
        "scale": "Higher = holds up across the BAD futures. A name with a deep-negative scenario scores LOWER; a huge UPSIDE scenario is NOT penalized (only the downside is).",
        "influence": "Ranks the book by all-weather fit; pairs with the upside rank, never replaces it.",
        "edge": "Downside-only, so the ballast (GROY) tops the spear (AGA.V) on the spear's deep-negative C — never on its convex B upside. Set dispersion_mode='full' for the legacy symmetric penalty.",
    },
    "scenario_c_hole": {
        "what": "The scenario-C / uranium hole — the book is structurally under-hedged to the AI-productivity WIN (and reflation); the electrification-royalty slot is the only real C/D hedge.",
        "scale": "Fires when C weight is non-trivial AND the C/D-winning book weight is thin.",
        "influence": "A standing alarm to scout/size the electrification slot — feeds the rotation/replacement work (P5).",
    },
}


def scenario_tooltip(key: str) -> str:
    e = SCENARIO_GLOSSARY.get(key)
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


def _cfg(config: Optional[dict]) -> dict:
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_SCENARIO_CONFIG.items()}
    block = (config or {}).get("scenario_engine", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def _tape_value(macro_tape: Optional[dict], key: str) -> Optional[float]:
    for s in ((macro_tape or {}).get("signals") or []):
        if s.get("key") == key:
            return _num(s.get("value"))
    return None


def _drivers(rates, productivity, macro_tape, cfg) -> dict:
    """Extract each scenario's 0..1 driver signal from the monitor outputs (None when unavailable)."""
    # B — rates bear-steepener / fiscal dominance. The fiscal-dominance score is 0..100, so it MUST be
    # normalized to 0..1 (like the C driver) BEFORE the tilt — a raw 0..100 here swamps the prior. The
    # bug hid because the steepener bump's _clamp() accidentally saturated the raw score to 1.0 whenever
    # the steepener fired; with the steepener OFF (the live case) the raw score flowed through unclamped.
    b_sig = None
    if rates:
        fd = (rates.get("fiscal_dominance") or {}).get("score")
        b_sig = _clamp(_num(fd) / 100.0) if _num(fd) is not None else None
        if b_sig is not None and (rates.get("bear_steepener") or {}).get("active"):
            b_sig = _clamp(b_sig + 0.15)
    # C — productivity scenario-C pressure
    c_sig = None
    if productivity:
        cp = (productivity.get("scenario_c_pressure") or {}).get("score")
        c_sig = _clamp(_num(cp) / 100.0) if _num(cp) is not None else None
    # A — managed debasement: low/neg real yield (+ soft DXY)
    a_sig = None
    ry = _tape_value(macro_tape, "real_yield")
    if ry is not None:
        a_sig = _clamp((float(cfg["real_yield_pivot"]) - ry) / (2.0 * float(cfg["real_yield_pivot"])))
        dxy = _tape_value(macro_tape, "dxy")
        if dxy is not None and dxy < float(cfg["dxy_soft"]):
            a_sig = _clamp(a_sig + 0.10)
    # D — copper reflation (Cu/Au ×1000)
    d_sig = None
    cu = _tape_value(macro_tape, "cu_au")
    if cu is not None:
        lo, hi = float(cfg["cu_au_lo"]), float(cfg["cu_au_hi"])
        d_sig = _clamp((cu - lo) / max(1e-9, hi - lo))
    # E — benign normalization: the INVERSE of the debasement tilt (real yields normalize POSITIVE),
    # muted by a crisis steepener (a disorderly break is not benign). High ⇒ goldilocks. Reuses ``ry``.
    e_sig = None
    if ry is not None:
        e_sig = _clamp((ry - float(cfg["real_yield_pivot"])) / (2.0 * float(cfg["real_yield_pivot"])))
        if rates and (rates.get("bear_steepener") or {}).get("active"):
            e_sig = _clamp(e_sig - 0.20)
    return {"A": a_sig, "B": b_sig, "C": c_sig, "D": d_sig, "E": e_sig}


def scenario_weights(rates=None, productivity=None, macro_tape=None, *, config=None) -> dict:
    """Probability weights on A–E, driven from the base prior tilted by the live signals. Returns
    ``{weights, drivers, base_prior}``; weights always sum to 1 (falls back to the prior when no
    signals are present)."""
    cfg = _cfg(config)
    base = cfg["base_prior"]
    gain = float(cfg["signal_gain"])
    drv = _drivers(rates, productivity, macro_tape, cfg)
    raw = {}
    for s in SCENARIO_KEYS:
        b = float(base.get(s, 0.0))
        sig = drv.get(s)
        raw[s] = max(1e-6, b * (1.0 + gain * sig) if sig is not None else b)
    tot = sum(raw.values())
    weights = {s: round(raw[s] / tot, 4) for s in raw}
    return {"weights": weights, "drivers": drv, "base_prior": base}


def _payoffs_for(holding: dict) -> dict:
    """Resolve a holding's per-scenario payoffs: explicit override → slot default → archetype → flat.
    A missing scenario key defaults to 0 (neutral), so a legacy 4-key (A–D) override keeps working as
    the set grows (E added) without silently being discarded."""
    ov = holding.get("scenario_payoffs") or holding.get("payoffs")
    if isinstance(ov, dict) and any(_num(ov.get(s)) is not None for s in SCENARIO_KEYS):
        return {s: (float(_num(ov.get(s))) if _num(ov.get(s)) is not None else 0.0) for s in SCENARIO_KEYS}
    slot = holding.get("slot") or holding.get("thesis_slot")
    if slot in DEFAULT_SLOT_PAYOFFS:
        d = DEFAULT_SLOT_PAYOFFS[slot]
        return {s: float(d.get(s, 0.0)) for s in SCENARIO_KEYS}
    arch = holding.get("archetype")
    if arch in DEFAULT_ARCHETYPE_PAYOFFS:
        d = DEFAULT_ARCHETYPE_PAYOFFS[arch]
        return {s: float(d.get(s, 0.0)) for s in SCENARIO_KEYS}
    return {s: 0.0 for s in SCENARIO_KEYS}


def _robustness(payoffs: dict, weights: dict, lam: float, mode: str = "downside") -> dict:
    exp = sum(weights[s] * payoffs[s] for s in SCENARIO_KEYS)
    # Dispersion penalty. DOWNSIDE semideviation (default) penalizes ONLY scenarios worse than expected
    # — the all-weather question is "how bad are the bad futures", not "how much does it vary at all".
    # Symmetric variance (legacy "full") squares the deviation in EVERY scenario, so it docks a convex
    # name for its UPSIDE leg too (the spear's +1.00 in B inflates the penalty) — exactly backwards for a
    # book whose reason to exist is upside convexity (the Markowitz error in a Druckenmiller book). The
    # spear should be penalized for its deep-negative C, never for its huge B.
    if str(mode).lower() == "full":
        var = sum(weights[s] * (payoffs[s] - exp) ** 2 for s in SCENARIO_KEYS)
    else:
        var = sum(weights[s] * min(0.0, payoffs[s] - exp) ** 2 for s in SCENARIO_KEYS)
    sd = var ** 0.5
    best = max(SCENARIO_KEYS, key=lambda s: payoffs[s])
    worst = min(SCENARIO_KEYS, key=lambda s: payoffs[s])
    return {"expected_payoff": round(exp, 4), "dispersion": round(sd, 4),
            "dispersion_mode": "full" if str(mode).lower() == "full" else "downside",
            "robustness": round(exp - lam * sd, 4),
            "best_scenario": best, "worst_scenario": worst,
            "best_payoff": round(payoffs[best], 3), "worst_payoff": round(payoffs[worst], 3)}


def assess(holdings: Optional[list], *, rates=None, productivity=None, macro_tape=None,
           oil=None, config=None) -> dict:
    """Score the book across the scenarios (A–E).

    ``holdings``: list of ``{ticker, slot|thesis_slot, archetype, weight, scenario_payoffs?}``. The
    monitor outputs (``rates``/``productivity``/``macro_tape``) drive the weights. Returns the
    scenarios (with weights folded in), the rankings by robustness, the upside leader, and the
    scenario-C/uranium hole flag.
    """
    cfg = _cfg(config)
    lam = float(cfg["dispersion_lambda"])
    mode = str(cfg.get("dispersion_mode", "downside"))
    wpack = scenario_weights(rates, productivity, macro_tape, config=config)
    weights = wpack["weights"]

    rows = []
    for h in (holdings or []):
        if not isinstance(h, dict) or not h.get("ticker"):
            continue
        payoffs = _payoffs_for(h)
        r = _robustness(payoffs, weights, lam, mode)
        rows.append({"ticker": h["ticker"], "slot": h.get("slot") or h.get("thesis_slot"),
                     "book_weight": _num(h.get("weight")), "payoffs": {s: round(payoffs[s], 3) for s in payoffs},
                     **r})

    by_robust = sorted(rows, key=lambda x: x["robustness"], reverse=True)
    by_upside = sorted(rows, key=lambda x: x["expected_payoff"], reverse=True)
    for i, row in enumerate(by_robust, 1):
        row["robustness_rank"] = i
    upside_rank = {row["ticker"]: i for i, row in enumerate(by_upside, 1)}
    for row in by_robust:
        row["upside_rank"] = upside_rank[row["ticker"]]

    # ---- scenario-C / uranium hole -------------------------------------------
    thr = float(cfg["hedge_payoff_thr"])
    cd_hedge_weight = sum((row["book_weight"] or 0.0) for row in rows
                          if row["payoffs"]["C"] >= thr or row["payoffs"]["D"] >= thr)
    hedges = [row["ticker"] for row in rows if row["payoffs"]["C"] >= thr or row["payoffs"]["D"] >= thr]
    c_weight = weights.get("C", 0.0)
    hole = bool(c_weight >= float(cfg["hole_c_weight"])
                and cd_hedge_weight < float(cfg["hole_hedge_book_weight"]))
    flags = []
    if hole:
        flags.append({"id": "scenario_c_hole", "active": True, "level": "warn",
                      "text": (f"SCENARIO-C / URANIUM HOLE — C weight {c_weight:.0%} "
                               f"(+D), but C/D-winning book weight only {cd_hedge_weight:.0%} "
                               f"({', '.join(hedges) or 'none'}) — under-hedged to the AI-productivity win")})

    scenarios = {s: {**SCENARIOS[s], "weight": weights[s], "driver_signal": wpack["drivers"].get(s)}
                 for s in SCENARIO_KEYS}
    return {
        "scenarios": scenarios,
        "weights": weights,
        "drivers": wpack["drivers"],
        "rankings": by_robust,
        "robustness_leader": (by_robust[0]["ticker"] if by_robust else None),
        "upside_leader": (by_upside[0]["ticker"] if by_upside else None),
        "scenario_c_hole": {"active": hole, "c_weight": round(c_weight, 4),
                            "cd_hedge_book_weight": round(cd_hedge_weight, 4), "hedges": hedges},
        "flags": flags,
        "glossary": {k: scenario_tooltip(k) for k in SCENARIO_GLOSSARY},
        "note": "robustness ≠ upside — the spear leads on single-scenario upside, the ballast on robustness (by design)",
    }
