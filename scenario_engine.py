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
  2. **per-name robustness** — `E[payoff] − λ·dispersion` across the weighted scenarios. The
     dispersion penalty is the point: it rewards the all-weather ballast (GROY — positive in A/B, only
     mildly soft in C) OVER the convex spear (AGA.V — huge in B, deeply negative in C). So **robustness
     ranks GROY #1** while the spear still leads on raw single-scenario UPSIDE (reported separately so
     the convexity is never buried). Robustness is a *different lens*, not a replacement for the barbell.

And one alarm: the **scenario-C / uranium hole** — when the C(+D) weight is non-trivial but the book's
C/D-winning exposure (the electrification-royalty slot) is thin, raise it. The book is structurally
under-hedged to the AI-productivity win; this makes that explicit instead of leaving it implicit.

Pure + dependency-free; one-directional (a consumer of the monitors, never a re-computer). Payoffs are
slot-derived defaults, overridable per name via `v5_config.json → portfolio_metadata[t].scenario_payoffs`.
Tunables live under `scenario_engine.*` (proposal-gated). No eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_SCENARIO_CONFIG", "SCENARIOS", "SCENARIO_GLOSSARY", "scenario_tooltip",
           "DEFAULT_SLOT_PAYOFFS", "scenario_weights", "assess"]

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
}

#: Per-scenario payoff (−1 deeply hurt … +1 strongly wins) by thesis slot — the house default.
DEFAULT_SLOT_PAYOFFS: dict[str, dict[str, float]] = {
    "silver-spear":             {"A": 0.80, "B": 1.00, "C": -0.70, "D": 0.20},
    "gold-royalty-ballast":     {"A": 0.70, "B": 0.70, "C": -0.20, "D": 0.10},
    "project-generator-holdco": {"A": 0.40, "B": 0.10, "C": -0.10, "D": 0.50},
    "electrification-royalty":  {"A": 0.10, "B": 0.00, "C": 0.60,  "D": 0.70},
}
#: Coarser fallback by archetype when a name has no recognized slot.
DEFAULT_ARCHETYPE_PAYOFFS: dict[str, dict[str, float]] = {
    "convex_explorer":  {"A": 0.70, "B": 0.95, "C": -0.65, "D": 0.20},
    "royalty_streamer": {"A": 0.65, "B": 0.65, "C": -0.10, "D": 0.20},
    "project_generator":{"A": 0.40, "B": 0.10, "C": -0.10, "D": 0.50},
}

DEFAULT_SCENARIO_CONFIG: dict[str, Any] = {
    "base_prior": {"A": 0.34, "B": 0.22, "C": 0.20, "D": 0.24},  # house central case (debasement-tilted)
    "signal_gain": 0.60,            # how hard the live signals tilt the prior
    "dispersion_lambda": 0.50,      # robustness = E[payoff] − λ·weighted_stdev  (the all-weather penalty)
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
        "what": "A name's probability-weighted expected payoff MINUS a dispersion penalty (λ·weighted stdev across scenarios) — the all-weather score.",
        "scale": "Higher = consistent across futures. A high-upside, high-variance bet scores LOWER than a steady ballast.",
        "influence": "Ranks the book by all-weather fit; pairs with the upside rank, never replaces it.",
        "edge": "The dispersion penalty is why the ballast (GROY) tops the spear (AGA.V) here — by design.",
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
    # B — rates bear-steepener / fiscal dominance
    b_sig = None
    if rates:
        fd = (rates.get("fiscal_dominance") or {}).get("score")
        b_sig = _num(fd)
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
    return {"A": a_sig, "B": b_sig, "C": c_sig, "D": d_sig}


def scenario_weights(rates=None, productivity=None, macro_tape=None, *, config=None) -> dict:
    """Probability weights on A/B/C/D, driven from the base prior tilted by the live signals.
    Returns ``{weights, drivers, base_prior}``; weights always sum to 1 (falls back to the prior when
    no signals are present)."""
    cfg = _cfg(config)
    base = cfg["base_prior"]
    gain = float(cfg["signal_gain"])
    drv = _drivers(rates, productivity, macro_tape, cfg)
    raw = {}
    for s in ("A", "B", "C", "D"):
        b = float(base.get(s, 0.25))
        sig = drv.get(s)
        raw[s] = max(1e-6, b * (1.0 + gain * sig) if sig is not None else b)
    tot = sum(raw.values())
    weights = {s: round(raw[s] / tot, 4) for s in raw}
    return {"weights": weights, "drivers": drv, "base_prior": base}


def _payoffs_for(holding: dict) -> dict:
    """Resolve a holding's per-scenario payoffs: explicit override → slot default → archetype → flat."""
    ov = holding.get("scenario_payoffs") or holding.get("payoffs")
    if isinstance(ov, dict) and all(_num(ov.get(s)) is not None for s in ("A", "B", "C", "D")):
        return {s: float(_num(ov[s])) for s in ("A", "B", "C", "D")}
    slot = holding.get("slot") or holding.get("thesis_slot")
    if slot in DEFAULT_SLOT_PAYOFFS:
        return dict(DEFAULT_SLOT_PAYOFFS[slot])
    arch = holding.get("archetype")
    if arch in DEFAULT_ARCHETYPE_PAYOFFS:
        return dict(DEFAULT_ARCHETYPE_PAYOFFS[arch])
    return {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}


def _robustness(payoffs: dict, weights: dict, lam: float) -> dict:
    exp = sum(weights[s] * payoffs[s] for s in ("A", "B", "C", "D"))
    var = sum(weights[s] * (payoffs[s] - exp) ** 2 for s in ("A", "B", "C", "D"))
    sd = var ** 0.5
    best = max(("A", "B", "C", "D"), key=lambda s: payoffs[s])
    worst = min(("A", "B", "C", "D"), key=lambda s: payoffs[s])
    return {"expected_payoff": round(exp, 4), "dispersion": round(sd, 4),
            "robustness": round(exp - lam * sd, 4),
            "best_scenario": best, "worst_scenario": worst,
            "best_payoff": round(payoffs[best], 3), "worst_payoff": round(payoffs[worst], 3)}


def assess(holdings: Optional[list], *, rates=None, productivity=None, macro_tape=None,
           oil=None, config=None) -> dict:
    """Score the book across the four scenarios.

    ``holdings``: list of ``{ticker, slot|thesis_slot, archetype, weight, scenario_payoffs?}``. The
    monitor outputs (``rates``/``productivity``/``macro_tape``) drive the weights. Returns the
    scenarios (with weights folded in), the rankings by robustness, the upside leader, and the
    scenario-C/uranium hole flag.
    """
    cfg = _cfg(config)
    lam = float(cfg["dispersion_lambda"])
    wpack = scenario_weights(rates, productivity, macro_tape, config=config)
    weights = wpack["weights"]

    rows = []
    for h in (holdings or []):
        if not isinstance(h, dict) or not h.get("ticker"):
            continue
        payoffs = _payoffs_for(h)
        r = _robustness(payoffs, weights, lam)
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
                 for s in ("A", "B", "C", "D")}
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
