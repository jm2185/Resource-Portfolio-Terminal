"""
Calibration — turning the decision archive into a learning system (Forge Phase 5 / roadmap Idea 2).

You make few decisions in a 4-name book, so each is trackable and systematic bias (always too bullish
on upside, floors always too conservative) is real money error, not noise. This module grades a frozen
decision against what actually happened, and aggregates the closed decisions into a scorecard.

The objective function is **Druckenmiller's, not a diversified-value book's**: what matters is *how
much you make when right vs. how much you lose when wrong*, and whether you pressed your good calls.
So the headline metrics are **slugging** (avg win ÷ avg loss), **expectancy per decision**, **upside
capture** (did you ride winners to the bull leg or under-bet them?), and **downside containment** (did
you respect the floor?). Hit-rate, conservatism bias, and the reliability curve survive but are
DEMOTED on purpose — a tool that optimizes you toward "be right more often" would quietly turn this
into a value book. (If the top line of a scorecard is hit-rate, it's mis-built.)

A decision is frozen at decision time: ``{ticker, date, verdict, side, price, legs:{floor,base,bull,
bear}, rho, phi, jsf, archetype}``. An outcome stamps the realized price at a horizon against those
frozen legs — so a bull call is "right" if price approached the bull leg in-window; a floor is "right"
if it held. Multi-horizon, because a discovery thesis and a royalty re-rate play out on different clocks.

Pure stdlib, fully testable.
"""
from __future__ import annotations

from typing import Optional

try:
    import base_rates as br
except Exception:                                  # base rates are an enhancement, never a hard dep
    br = None

WIN_THRESHOLD = 0.05            # |return| below this is a scratch (neither win nor loss)
MIN_PERSONAL_N = 5             # below this the book is COLD — report priors + wide intervals, no false %

#: archetype → the published base rate that best anchors its "does the thesis pay" probability while
#: the personal sample is thin. Only researched priors are mapped; others stay uninformative (honest).
ARCHETYPE_PRIOR = {
    "option_convexity": "discovery_to_mine",      # the spear's payoff is discovery-like (MinEx 0.50)
    "explorer": "discovery_to_mine",
    "discovery": "discovery_to_mine",
}


def _num(x):
    try:
        f = float(x)
        return f if f == f else None        # reject NaN
    except (TypeError, ValueError):
        return None


def infer_side(verdict: Optional[str]) -> str:
    """Long vs avoid from the verdict/directive. The book is long-only; 'long' means we're in / adding,
    'avoid' means we passed or exited (a correct AVOID that then fell is a *win* for the process)."""
    d = str(verdict or "").upper()
    if any(k in d for k in ("ACCUMULATE", "CORE HOLD", "PRESS", "RE-AFFIRM", "BELOW FLOOR",
                            "STRONG ASYMMETRY", "MONITOR", "HOLD")):
        return "long"
    if any(k in d for k in ("AVOID", "EXIT", "TRIM", "RICH", "STAND ASIDE", "DE-RISK")):
        return "avoid"
    return "long"


def score_outcome(decision: dict, realized_price: float, *, horizon_days: Optional[int] = None) -> dict:
    """Grade one frozen decision against a realized price. Returns the leg hit, the realized vs
    projected return, upside capture, floor-held, and a win/loss/scratch result keyed to the side."""
    p0 = _num(decision.get("price"))
    rp = _num(realized_price)
    legs = decision.get("legs", {}) or {}
    floor, base, bull = _num(legs.get("floor")), _num(legs.get("base")), _num(legs.get("bull"))
    side = decision.get("side") or infer_side(decision.get("verdict"))
    if p0 is None or rp is None or p0 <= 0:
        return {"status": "unscored", "reason": "missing decision price or realized price"}

    realized_return = rp / p0 - 1.0
    projected_bull_return = (bull / p0 - 1.0) if (bull and bull > 0) else None
    floor_held = (rp >= floor) if floor is not None else None

    # which leg the realized price reached (long frame; advances floor -> bull)
    if bull is not None and rp >= bull:
        leg_hit = "bull"
    elif base is not None and rp >= base:
        leg_hit = "base"
    elif rp >= p0:
        leg_hit = "above_entry"
    elif floor is not None and rp >= floor:
        leg_hit = "held_floor"
    else:
        leg_hit = "broke_floor"

    # upside capture: realized vs the projected bull leg (were you under-betting your good calls?)
    upside_capture = None
    if projected_bull_return and projected_bull_return > 0 and realized_return > 0:
        upside_capture = round(realized_return / projected_bull_return, 3)

    # result, keyed to side. For an AVOID, a *fall* is a correct call (process win).
    if side == "avoid":
        signed = -realized_return                      # falling price validates the avoid
    else:
        signed = realized_return
    if abs(signed) < WIN_THRESHOLD:
        result = "scratch"
    else:
        result = "win" if signed > 0 else "loss"

    return {
        "status": "scored",
        "ticker": decision.get("ticker"),
        "archetype": decision.get("archetype"),
        "side": side,
        "horizon_days": horizon_days,
        "realized_return": round(realized_return, 4),
        "signed_return": round(signed, 4),
        "projected_bull_return": round(projected_bull_return, 4) if projected_bull_return is not None else None,
        "upside_capture": upside_capture,
        "leg_hit": leg_hit,
        "floor_held": floor_held,
        "result": result,
    }


def scorecard(scored: list, *, by_archetype: bool = False) -> dict:
    """Aggregate scored outcomes into the Druckenmiller-objective scorecard. Pass the list of
    ``score_outcome`` results. The headline order is expectancy/slugging/upside-capture/containment;
    hit-rate is reported but DEMOTED (last)."""
    rows = [s for s in scored if s.get("status") == "scored"]
    if not rows:
        return {"n": 0, "note": "no closed decisions yet"}

    signed = [s["signed_return"] for s in rows]
    wins = [s for s in rows if s["result"] == "win"]
    losses = [s for s in rows if s["result"] == "loss"]
    avg_win = (sum(s["signed_return"] for s in wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(s["signed_return"] for s in losses)) / len(losses)) if losses else 0.0
    slugging = round(avg_win / avg_loss, 2) if avg_loss > 0 else (float("inf") if wins else 0.0)
    expectancy = round(sum(signed) / len(rows), 4)

    captures = [s["upside_capture"] for s in rows if s.get("upside_capture") is not None]
    upside_capture = round(sum(captures) / len(captures), 3) if captures else None

    floor_calls = [s for s in rows if s.get("floor_held") is not None]
    contained = [s for s in floor_calls if s["floor_held"]]
    downside_containment = round(len(contained) / len(floor_calls), 3) if floor_calls else None

    decided = wins + losses                            # scratches excluded from hit-rate
    hit_rate = round(len(wins) / len(decided), 3) if decided else None

    out = {
        "n": len(rows),
        # --- HEADLINE (expectancy first; this is the objective function) ---
        "expectancy_per_decision": expectancy,
        "slugging_ratio": slugging,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "upside_capture": upside_capture,
        "downside_containment": downside_containment,
        # --- SECONDARY (demoted on purpose — never the objective) ---
        "secondary": {"hit_rate": hit_rate, "wins": len(wins), "losses": len(losses),
                      "scratches": len(rows) - len(decided)},
    }
    if by_archetype:
        groups: dict = {}
        for s in rows:
            groups.setdefault(s.get("archetype") or "_unknown", []).append(s)
        out["by_archetype"] = {a: scorecard(g, by_archetype=False) for a, g in groups.items()}
    return out


def _beta_ci(a: float, b: float, mass: float = 0.90) -> tuple:
    """Beta credible interval — via base_rates if present, else a normal approximation (still an
    interval, never a bare point)."""
    if br is not None:
        return br.beta_ci(a, b, mass)
    mean = a / (a + b)
    var = a * b / ((a + b) ** 2 * (a + b + 1))
    sd = var ** 0.5
    z = 1.645                                          # 90%
    return (round(max(0.0, mean - z * sd), 4), round(min(1.0, mean + z * sd), 4))


def win_probability(scored: list, *, ledger_rejects: Optional[list] = None) -> dict:
    """Bayesian win-probability with a credible interval — NEVER a bare %. A weakly-informative
    Beta(1,1) updated with personal wins/losses, widened by the Ledger's REJECT outcomes (a passed
    name that then fell is a process win; one that ran is a miss). With a thin sample the interval is
    deliberately wide — that's the point of reporting cold-start honestly."""
    rows = [s for s in scored if s.get("status") == "scored"]
    wins = sum(1 for s in rows if s["result"] == "win")
    losses = sum(1 for s in rows if s["result"] == "loss")
    for e in (ledger_rejects or []):
        wins += int(e.get("wins", 0) or 0)
        losses += int(e.get("losses", 0) or 0)
    a, b = 1.0 + wins, 1.0 + losses                   # Beta(1,1) prior
    n = wins + losses
    return {"mean": round(a / (a + b), 4), "ci90": _beta_ci(a, b), "wins": wins, "losses": losses,
            "n": n, "cold_start": n < MIN_PERSONAL_N,
            "note": ("COLD — wide interval; lean on base rates" if n < MIN_PERSONAL_N
                     else "warming — personal sample now informative")}


def archetype_base_rate(archetype: Optional[str]) -> Optional[dict]:
    """The published base-rate prior anchoring an archetype's thesis-payoff odds (estimate + CI +
    source), or None if no researched prior maps to it (kept honest — we don't invent authority)."""
    if br is None:
        return None
    name = ARCHETYPE_PRIOR.get(str(archetype or "").strip().lower())
    return br.estimate(name) if name else None


def priored_scorecard(scored: list, *, ledger_rejects: Optional[list] = None,
                      archetypes: Optional[list] = None) -> dict:
    """The expectancy scorecard PLUS a cold-start layer: the Bayesian win-probability (with interval),
    and the published base rates anchoring the book while the personal sample is thin. The headline
    Druckenmiller metrics are unchanged; this just refuses false precision when n is small."""
    sc = scorecard(scored, by_archetype=True)
    n = sc.get("n", 0)
    cold = n < MIN_PERSONAL_N
    out = dict(sc)
    out["win_probability"] = win_probability(scored, ledger_rejects=ledger_rejects)
    out["cold_start"] = cold
    # surface the base rates for the archetypes actually in the book (or the ones present in outcomes)
    arches = archetypes or sorted({s.get("archetype") for s in scored if s.get("archetype")})
    base = {}
    for a in arches:
        e = archetype_base_rate(a)
        if e:
            base[a] = e
    out["base_rates"] = base
    if br is not None:
        # always-useful reference priors (shown even with zero decisions)
        out["reference_priors"] = {k: br.estimate(k) for k in
                                   ("discovery_to_mine", "ma_premium_20d", "time_to_production_years")}
    if cold:
        out["cold_start_note"] = (f"COLD START (n={n} < {MIN_PERSONAL_N}): leaning on published base "
                                  f"rates with wide credible intervals — no false-precision %.")
    return out


def bias_proposals(sc: dict) -> list:
    """Detect SYSTEMATIC bias and emit param-change PROPOSALS (key/value/reason). NEVER applies them —
    they route through propose_param_change → /confirm (the human gate). Returns [] when nothing is
    actionable or the sample is too thin to trust."""
    proposals: list = []
    n = sc.get("n", 0)
    if n < MIN_PERSONAL_N:
        return proposals                              # don't propose off a cold sample
    sec = sc.get("secondary", {}) or {}
    losses = sec.get("losses", 0)
    contain = sc.get("downside_containment")
    capture = sc.get("upside_capture")
    # 1) floors running CONSERVATIVE: floors always held AND essentially no losses -> the REP floor may
    #    be set too low (leaving upside on the table). Propose easing conservatism, never auto-apply.
    if contain is not None and contain >= 0.99 and losses == 0:
        proposals.append({
            "key": "conservatism_scalar", "value_hint": "−0.05 step (toward less conservative)",
            "metric": "downside_containment", "observed": contain,
            "reason": (f"Floors held on every closed decision (containment {contain:.0%}) with zero "
                       f"losses over n={n} — the REP floor may be running conservative, costing upside. "
                       f"Consider easing conservatism_scalar one step. PROPOSAL ONLY — confirm to apply."),
        })
    # 2) UNDER-BETTING winners: systematically low upside capture -> behavioral, no clean param knob.
    if capture is not None and capture < 0.40 and sec.get("wins", 0) >= 3:
        proposals.append({
            "key": None, "kind": "review", "metric": "upside_capture", "observed": capture,
            "reason": (f"Upside capture {capture:.0%} across {sec.get('wins')} winners — you may be "
                       f"under-riding good calls (exiting before the bull leg). No config knob; a "
                       f"behavioral review item, not a tunable."),
        })
    return proposals


def decision_from_rating(basket: dict, *, verdict: Optional[str] = None) -> dict:
    """Freeze a decision record from a live conviction rating (the agent-facing projection). Captures
    the legs, ρ, φ, the gate cap (JSF proxy), and the archetype at decision time."""
    ladder = basket.get("ladder", {}) or {}
    asym = basket.get("asymmetry", {}) or {}
    gate = basket.get("gate", {}) or {}
    v = verdict or basket.get("directive")
    return {
        "ticker": basket.get("ticker"),
        "verdict": v,
        "side": infer_side(v),
        "price": ladder.get("price"),
        "legs": {k: ladder.get(k) for k in ("floor", "bear", "base", "bull")},
        "rho": asym.get("rho"),
        "phi": asym.get("floor_coverage"),
        "jsf_cap": gate.get("cap"),
        "archetype": basket.get("archetype"),
    }
