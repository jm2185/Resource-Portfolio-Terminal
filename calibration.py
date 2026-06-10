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

import math
from typing import Optional

try:
    import base_rates as br
except Exception:                                  # base rates are an enhancement, never a hard dep
    br = None

WIN_THRESHOLD = 0.05            # |return| below this is a scratch (neither win nor loss)
MIN_PERSONAL_N = 5             # below this the book is COLD — report priors + wide intervals, no false %
RUIN_RETURN = -0.50           # a single held decision at/below this (a halving) is a ruin-class wound

#: rho (asymmetric payoff) bar a bet must clear AT DECISION TIME to count as WELL-SHAPED. The
#: decision-quality axis grades this FROZEN shape independently of how the print landed (Duke /
#: anti-resulting: a good bet that drifts flat is still a good bet; a lucky thin bet is still thin).
ARCHETYPE_RHO_BAR = {"option_convexity": 2.5, "explorer": 2.5, "discovery": 2.5,
                     "asset_light_yield": 1.5}
DEFAULT_RHO_BAR = 2.0
PHI_BAR = 1.0                  # floor_coverage ≥ 1 = the REP floor covers price (margin of safety intact)

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

    # decision-quality axis — graded on the FROZEN bet shape (rho/phi), INDEPENDENT of the print.
    # (Duke / anti-resulting: separate "was this a good bet" from "did it pay off this time".)
    rho = _num(decision.get("rho"))
    phi = _num(decision.get("phi"))
    bar = ARCHETYPE_RHO_BAR.get(str(decision.get("archetype") or "").strip().lower(), DEFAULT_RHO_BAR)
    if rho is None and phi is None:
        decision_quality = "unknown"                   # nothing frozen to judge the shape on
    elif (rho is not None and rho >= bar) and (phi is None or phi >= PHI_BAR):
        decision_quality = "well_shaped"
    else:
        decision_quality = "thin"
    # thesis-implied breakeven prob from the payoff ratio: p* = 1/(1+ρ) (aggregate calibration anchor).
    implied_breakeven_p = round(1.0 / (1.0 + rho), 4) if (rho is not None and (1.0 + rho) > 0) else None

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
        # --- decision-quality axis (frozen shape, outcome-independent) ---
        "rho": rho,
        "phi": phi,
        "decision_quality": decision_quality,
        "implied_breakeven_p": implied_breakeven_p,
    }


def _path_metrics(rows: list) -> dict:
    """The WEALTH PATH over decisions actually HELD (longs) — the ergodic view expectancy is blind to.
    A concentrated book lives ONE multiplicative path: arithmetic expectancy can be positive while the
    geometric (compounded) return is negative (Taleb / ergodicity). Reports geometric return per
    decision, the ending wealth multiple, max drawdown, and ruin-class events (a floor-break that also
    halved). Avoids don't compound your book, so they're excluded from the wealth path."""
    held = [s for s in rows if s.get("side") == "long" and _num(s.get("realized_return")) is not None]
    if not held:
        return {}
    rs = [float(s["realized_return"]) for s in held]
    geo = math.exp(sum(math.log(max(1e-6, 1.0 + r)) for r in rs) / len(rs)) - 1.0
    w = peak = 1.0
    max_dd = 0.0
    for r in rs:
        w *= (1.0 + r)
        peak = max(peak, w)
        if peak > 0:
            max_dd = max(max_dd, (peak - w) / peak)
    ruin = sum(1 for s in held
               if s.get("floor_held") is False and float(s["realized_return"]) <= RUIN_RETURN)
    return {"geometric_return_per_decision": round(geo, 4), "ending_wealth_mult": round(w, 4),
            "max_drawdown": round(max_dd, 4), "ruin_events": ruin, "n_held": len(held)}


def _expectancy_ci(signed: list, mass: float = 0.90) -> Optional[tuple]:
    """A normal 90% interval on expectancy — only meaningful once the sample is warm, so callers gate
    it on n ≥ MIN_PERSONAL_N (Tetlock: don't print a frequentist interval off 2 points)."""
    n = len(signed)
    if n < 2:
        return None
    m = sum(signed) / n
    var = sum((x - m) ** 2 for x in signed) / (n - 1)
    se = (var / n) ** 0.5
    z = 1.645 if mass == 0.90 else 1.96
    return (round(m - z * se, 4), round(m + z * se, 4))


def _process_metrics(rows: list) -> dict:
    """Process-vs-luck (Duke): split closed decisions by FROZEN ``decision_quality`` and compare
    expectancy. If well-shaped bets out-earn thin ones the edge is in the PROCESS, not the print. Plus
    an aggregate calibration — realized long win-rate vs the average thesis-implied breakeven 1/(1+ρ)
    (a Brier-style check that the book clears its OWN implied bar, not just that prices rose)."""
    shaped = [s for s in rows if s.get("decision_quality") == "well_shaped"]
    thin = [s for s in rows if s.get("decision_quality") == "thin"]

    def _exp(g):
        return round(sum(s["signed_return"] for s in g) / len(g), 4) if g else None

    out = {"well_shaped_n": len(shaped), "thin_n": len(thin),
           "expectancy_well_shaped": _exp(shaped), "expectancy_thin": _exp(thin)}
    if out["expectancy_well_shaped"] is not None and out["expectancy_thin"] is not None:
        out["process_edge"] = round(out["expectancy_well_shaped"] - out["expectancy_thin"], 4)
    longs = [s for s in rows if s.get("side") == "long" and s.get("implied_breakeven_p") is not None
             and s.get("result") in ("win", "loss")]
    if longs:
        avg_be = sum(s["implied_breakeven_p"] for s in longs) / len(longs)
        win_rate = sum(1 for s in longs if s["result"] == "win") / len(longs)
        out["calibration"] = {"avg_implied_breakeven": round(avg_be, 4),
                              "realized_win_rate": round(win_rate, 4),
                              "edge_vs_breakeven": round(win_rate - avg_be, 4), "n": len(longs)}
    return out


def scorecard(scored: list, *, by_archetype: bool = False) -> dict:
    """Aggregate scored outcomes into the Druckenmiller-objective scorecard. Pass the list of
    ``score_outcome`` results. The headline order is expectancy/slugging/upside-capture/containment;
    hit-rate is reported but DEMOTED (last). Carries a PATH block (the ergodic/geometric view +
    drawdown + ruin) and a PROCESS block (decision-quality split + implied-breakeven calibration) so
    a positive average can't hide a book compounding down, nor a lucky thin bet read as skill."""
    rows = [s for s in scored if s.get("status") == "scored"]
    if not rows:
        return {"n": 0, "note": "no closed decisions yet"}

    signed = [s["signed_return"] for s in rows]
    wins = [s for s in rows if s["result"] == "win"]
    losses = [s for s in rows if s["result"] == "loss"]
    avg_win = (sum(s["signed_return"] for s in wins) / len(wins)) if wins else 0.0
    avg_loss = (abs(sum(s["signed_return"] for s in losses)) / len(losses)) if losses else 0.0
    # Wins with zero losses (the normal early state of a good book) make slugging UNBOUNDED. Never
    # emit float('inf'): it serializes as non-standard `Infinity`, which strict JSON parsers (the MCP
    # consume side) reject — silently killing the whole flywheel payload on the first clean win
    # streak. Report None + slugging_unbounded so consumers degrade gracefully.
    slugging_unbounded = bool(wins) and avg_loss <= 0
    slugging = round(avg_win / avg_loss, 2) if avg_loss > 0 else (None if wins else 0.0)
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
        "slugging_unbounded": slugging_unbounded,
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "upside_capture": upside_capture,
        "downside_containment": downside_containment,
        # --- SECONDARY (demoted on purpose — never the objective) ---
        "secondary": {"hit_rate": hit_rate, "wins": len(wins), "losses": len(losses),
                      "scratches": len(rows) - len(decided)},
    }
    # --- PATH (ergodic / geometric) + PROCESS (decision-quality vs luck) ---
    out["path"] = _path_metrics(rows)
    out["process"] = _process_metrics(rows)
    geo = out["path"].get("geometric_return_per_decision")
    out["path_warning"] = (
        f"PATH RISK: geometric {geo:+.1%}/decision while arithmetic expectancy is {expectancy:+.2f}R — "
        f"the book is compounding DOWN despite a positive average (ergodicity gap; size for the path)."
        if (geo is not None and geo < 0 <= expectancy) else None)
    # --- RELIABILITY (Tetlock: refuse false precision at small n) ---
    # slugging needs ≥3 wins AND ≥2 losses before the win/loss averages mean anything; expectancy gets a
    # frequentist interval only once warm. Below MIN_PERSONAL_N the honest read is win_probability's
    # Bayesian interval + the base rate, NOT these point estimates.
    data_limited = len(rows) < MIN_PERSONAL_N
    out["reliability"] = {
        "n": len(rows), "data_limited": data_limited,
        "slugging_reliable": (len(wins) >= 3 and len(losses) >= 2),
        "expectancy_ci90": (_expectancy_ci(signed) if not data_limited else None),
        "note": (None if not data_limited else
                 f"DATA-LIMITED (n={len(rows)}<{MIN_PERSONAL_N}): expectancy/slugging are point reads "
                 f"off a thin sample — lean on win_probability's interval and the base rate, not these."),
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


#: discovery sleeve → the archetype whose published base rate anchors a candidate's outside view.
SLEEVE_ARCHETYPE = {"spear": "option_convexity", "ballast": "asset_light_yield"}


def candidate_anchor(archetype: Optional[str] = None, *, sleeve: Optional[str] = None,
                     stage: Optional[str] = None, commodity: Optional[str] = None) -> dict:
    """Reference-class prior for a discovery candidate — the OUTSIDE view (Kahneman / Tetlock
    reference-class forecasting): a find is scored against its archetype's published base rate, not in
    a vacuum. Resolve by archetype directly, or by sleeve (spear → option_convexity, ballast →
    asset_light_yield). Returns {archetype, base_rate, line}, or {} when no researched prior maps
    (kept honest — we don't invent authority).

    Flyvbjerg refinement: when ``stage`` is given, CONDITION the prior on the candidate's actual stage
    (chain the forward advancement gates) instead of the flat discovery→mine rate; and name the
    outcome-variable distinction — mine-conversion is a conservative floor on a TRADE that can also pay
    via a takeout or a stage re-rate. ``commodity`` adds the precious-metals advancement tilt."""
    arch = archetype or SLEEVE_ARCHETYPE.get(str(sleeve or "").strip().lower())
    est = archetype_base_rate(arch)
    if not est:
        # No researched thesis-payoff prior maps (notably asset_light_yield — the BALLAST sleeve,
        # 3 of 4 names). The honest read is an EXPLICIT thin-outside-view row, never a silent {}
        # dead-end: the agent must see "no reference class" and say so, not anchor to nothing.
        # We surface the ADJACENT researched priors that do exist for an asset-light/royalty
        # candidate (takeout premium, development lead time) clearly labelled as context, not a
        # payoff probability — we don't invent authority.
        if not arch:
            return {}
        out = {"archetype": arch, "base_rate": None, "outside_view": "thin",
               "line": (f"No researched reference class maps to {arch} — outside view THIN. Anchor "
                        f"the candidate on engine asymmetry (ρ/φ) + slot fit and SAY the prior is "
                        f"missing; do not quote a payoff probability that doesn't exist.")}
        if br is not None and arch == "asset_light_yield":
            adj = {}
            takeout = br.estimate("ma_premium_20d")
            if takeout:
                adj["takeout_premium_20d"] = {"median": takeout.get("median"),
                                              "ci90": list(takeout.get("ci90") or []),
                                              "confidence": takeout.get("confidence")}
            ttp = br.estimate("time_to_production_years")
            if ttp:
                adj["time_to_production_years"] = {"median": ttp.get("median"),
                                                   "ci90": list(ttp.get("ci90") or []),
                                                   "confidence": ttp.get("confidence")}
            if adj:
                out["adjacent_priors"] = adj
                out["line"] += (" Adjacent researched context (NOT a payoff rate): junior takeout "
                                "premium and discovery→production lead time.")
        return out
    val = est.get("mean", est.get("median"))
    ci = list(est.get("ci90") or [])
    ci_txt = f" (90% CI {ci[0]:g}–{ci[1]:g})" if len(ci) == 2 else ""
    line = (f"Reference class for {arch}: {est.get('name')} ≈ {val:g}{ci_txt} "
            f"[{est.get('confidence')}]. Anchor the candidate's score to this outside-view prior — "
            f"a find must beat its reference class, not just tell a good story.")
    out = {"archetype": arch,
           "base_rate": {"name": est.get("name"), "value": val, "ci90": ci,
                         "confidence": est.get("confidence"), "source": est.get("source")},
           "line": line}
    if br is None:
        return out
    # stage-conditional refinement — chain the forward gates from the candidate's ACTUAL stage
    if stage:
        chain = br.forward_to_production(stage)
        if chain:
            out["stage_conditional"] = chain
            sl, sh = chain["ci90"]
            out["line"] += (f" STAGE-CONDITIONAL ({chain['stage']}): P(reach production) ≈ "
                            f"{chain['p_reach_production']:g} (90% CI {sl:g}–{sh:g}) — prefer this to the "
                            f"flat rate; it conditions on where the project actually is.")
    # outcome-variable correction: mine-conversion ≠ the TRADE paying off (takeout / discovery re-rate)
    takeout = br.estimate("ma_premium_20d")
    if takeout:
        out["takeout_class"] = {"name": takeout["name"], "median": takeout.get("median"),
                                "ci90": list(takeout.get("ci90") or []),
                                "confidence": takeout["confidence"]}
    out["trade_payoff_note"] = (
        "mine-conversion is a conservative FLOOR on a spear's trade, not its success rate: the position "
        "can pay via a takeout (junior Au/Ag 20-day premium median ~35%) or a discovery/stage re-rate "
        "without ever becoming a mine. Score the TRADE, not only the mine.")
    # commodity tilt — Schodde: precious-metals discoveries advance at the optimistic end of the interval
    if str(commodity or "").strip().lower() in ("gold", "au", "silver", "ag", "precious"):
        out["commodity_tilt"] = ("precious-metals discoveries convert at the optimistic end of the "
                                 "discovery→mine interval (Schodde) — lean to the upper CI, don't recentre.")
    return out


#: the spear archetypes the H4 "Bear never narrative-vetoes the convex spear" rule applies to.
SPEAR_ARCHETYPES = ("option_convexity", "explorer", "discovery")


def spear_false_positives(scored: list, *, spear_archetypes=SPEAR_ARCHETYPES) -> dict:
    """H4 safety net (Janis / institutionalised optimism). By Arbiter law the Bear sets invalidation but
    NEVER vetoes a convex spear — a deliberate thumb on the scale, defensible ONLY if the calibration
    loop catches the spears that should have been killed. This is that backstop: spear longs that broke
    their floor or lost, and how many were process-ENDORSED (well-shaped, so the bull's case carried and
    the un-vetoing bear let it ship). A rising rate says the no-veto policy is leaking — revisit it."""
    spears = [s for s in scored if s.get("status") == "scored" and s.get("side") == "long"
              and str(s.get("archetype") or "").strip().lower() in spear_archetypes]
    losers = [s for s in spears if s.get("result") == "loss" or s.get("floor_held") is False]
    endorsed = [s for s in losers if s.get("decision_quality") == "well_shaped"]
    n = len(spears)
    return {"spear_decisions": n, "false_positives": len(losers), "endorsed_losers": len(endorsed),
            "floor_breaks": sum(1 for s in spears if s.get("floor_held") is False),
            "false_positive_rate": round(len(losers) / n, 3) if n else None,
            "note": ("the Bear can't veto a spear by design (H4) — the calibration loop is the only "
                     "backstop; watch this rate." if n else "no spear decisions closed — backstop unprimed.")}


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
    out["spear_backstop"] = spear_false_positives(scored)   # H4 safety net (Janis): watch the no-veto leak
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


def brief_prior(priored: dict, archetypes: Optional[list] = None) -> dict:
    """Compact the priored scorecard into the per-archetype prior injected into an agent's DESK-STATE
    frame — the *read side* of the calibration flywheel (the loop calibration.py grades closing back
    into the next underwrite). For each archetype in the book we surface the closed-outcome record
    (n · expectancy · upside-capture · downside-containment) plus the published base rate (central
    value + 90% CI) while the personal sample is thin — so a new underwrite is anchored to the bar the
    archetype has actually cleared, honest about cold start. Returns {} when there's nothing to say.

    ``archetypes`` should be the book's live archetypes so a base rate shows even at zero decisions
    (e.g. the spear's discovery-to-mine 0.50); falls back to whatever the outcomes/priors cover."""
    priored = priored or {}
    by_arch = priored.get("by_archetype") or {}
    base = priored.get("base_rates") or {}
    arches = [a for a in (archetypes or sorted(set(by_arch) | set(base))) if a]
    rows: dict = {}
    for a in arches:
        sc = by_arch.get(a) or {}
        est = base.get(a) or archetype_base_rate(a)
        n = sc.get("n", 0) or 0
        row = {"n": n, "expectancy": sc.get("expectancy_per_decision"),
               "upside_capture": sc.get("upside_capture"),
               "downside_containment": sc.get("downside_containment"),
               "cold": n < MIN_PERSONAL_N}
        if est:
            row["base_rate"] = {"name": est.get("name"),
                                "value": est.get("mean", est.get("median")),
                                "ci90": est.get("ci90")}
        elif a in (archetypes or []):
            # a LIVE book archetype with no researched prior (the ballast sleeve) must still get a
            # row — an explicit "outside view thin", never silent omission (the desk line otherwise
            # shows a cold-start prior for the spear only and the ballast flies blind).
            row["outside_view"] = "thin"
            row["note"] = "no researched reference class — anchor on engine ρ/φ + slot fit"
        if row["expectancy"] is not None or row.get("base_rate") or row.get("outside_view"):
            rows[a] = row
    if not rows:
        return {}
    out = {"archetypes": rows, "cold_start": priored.get("cold_start", True)}
    # forward the reliability verdict so the desk line can caveat a thin-sample headline (an
    # "n=1 exp +1.00R" printed bare reads like signal; the data_limited flag is the honesty).
    rel = priored.get("reliability") or {}
    if rel:
        out["reliability"] = {"n": rel.get("n"), "data_limited": bool(rel.get("data_limited")),
                              "note": rel.get("note")}
    wp = priored.get("win_probability") or {}
    if wp.get("n"):
        out["win_probability"] = {"mean": wp.get("mean"), "ci90": wp.get("ci90"), "n": wp.get("n")}
    # book-level wealth path — the ergodic backstop the agent must see (a +ve average can hide ruin)
    if priored.get("path"):
        out["path"] = priored["path"]
    if priored.get("path_warning"):
        out["path_warning"] = priored["path_warning"]
    # H4 spear backstop — only when primed (≥1 closed spear), so the no-veto leak is visible to the desk
    sb = priored.get("spear_backstop") or {}
    if sb.get("spear_decisions"):
        out["spear_backstop"] = sb
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


#: a scout candidate "delivered the asymmetry" when it returned at least this within the horizon —
#: the funnel's hit bar (a spear shortlist exists to surface multi-bagger setups, not steady grinders).
SCOUT_HIT_RETURN = 0.30


def scout_scorecard(rows: list, *, hit_return: float = SCOUT_HIT_RETURN) -> dict:
    """Grade the SCOUT itself (Phase 8 of the validation flywheel — the same medicine as the
    valuation ledger, applied to discovery). ``rows``: one dict per swept scout candidate —
    ``{ticker, archetype, slot, graduated: bool, realized_return, horizon_days}``.

    DELIBERATE OBJECTIVE INVERSION, say it plainly: for the BOOK the headline is expectancy and
    hit-rate is demoted (Druckenmiller — a 30%-hit book that crushes winners is winning). For
    DISCOVERY — a funnel — frequency IS the right objective: what fraction of surfaced names went
    on to deliver the asymmetry, and did the names we let through beat the ones we killed
    (regret)? A scout whose kills outperform its graduates is generating motion, not value."""
    scored = [r for r in rows or [] if _num(r.get("realized_return")) is not None]
    if not scored:
        return {"n": 0, "note": "no swept scout candidates yet — the watch is accruing"}

    def _bucket(group: list) -> dict:
        hits = [r for r in group if float(r["realized_return"]) >= hit_return]
        rets = [float(r["realized_return"]) for r in group]
        return {"n": len(group),
                "hit_rate": round(len(hits) / len(group), 3),
                "avg_return": round(sum(rets) / len(rets), 4),
                "best": round(max(rets), 4), "worst": round(min(rets), 4)}

    grads = [r for r in scored if r.get("graduated")]
    kills = [r for r in scored if not r.get("graduated")]
    out: dict = {"n": len(scored), "hit_return_bar": hit_return,
                 "headline": "hit-rate (the funnel objective — see note)",
                 "all": _bucket(scored)}
    if grads:
        out["graduated"] = _bucket(grads)
    if kills:
        out["not_graduated"] = _bucket(kills)
    # regret: a non-graduated candidate that hit anyway — the graveyard discipline for scouting
    regret = [r for r in kills if float(r["realized_return"]) >= hit_return]
    out["regret"] = {"n": len(regret),
                     "tickers": sorted({r.get("ticker") for r in regret if r.get("ticker")})}
    if grads and kills:
        edge = _bucket(grads)["avg_return"] - _bucket(kills)["avg_return"]
        out["graduation_edge"] = round(edge, 4)
        if edge < 0:
            out["warning"] = ("kills outperformed graduates — the graduation gate is filtering "
                              "the wrong way; review what @verifier/@anti-scout are rejecting.")
    # per-archetype / per-slot splits (where you run hot)
    for key in ("archetype", "slot"):
        groups: dict = {}
        for r in scored:
            groups.setdefault(r.get(key) or "_unknown", []).append(r)
        if len(groups) > 1 or (groups and "_unknown" not in groups):
            out[f"by_{key}"] = {k: _bucket(g) for k, g in groups.items()}
    out["data_limited"] = len(scored) < MIN_PERSONAL_N
    out["note"] = ("DISCOVERY funnel scorecard: hit-rate headlines HERE BY DESIGN (frequency is "
                   "the funnel's objective) — the book's scorecard keeps expectancy first and "
                   "hit-rate demoted; don't read this section as a license to invert that.")
    return out


def decision_from_rating(basket: dict, *, verdict: Optional[str] = None) -> dict:
    """Freeze a decision record from a live conviction rating (the agent-facing projection). Captures
    the legs, ρ, φ, the gate cap (JSF proxy), and the archetype at decision time.

    GOODHART GUARD (#8): the legs/ρ/φ here MUST come from the ENGINE basket (ladder/asymmetry/gate),
    NEVER from an agent-supplied field. The calibration prior tells agents to "clear this bar"; that
    bar is only un-gameable because the agent cannot move the measuring stick — legs are engine-set and
    the realized price is exogenous. Do not refactor this to read basket['legs']/['rho'] from a
    free-form payload; that would re-open the metric to gaming. (Guarded by test_calibration.)"""
    ladder = basket.get("ladder", {}) or {}
    asym = basket.get("asymmetry", {}) or {}
    gate = basket.get("gate", {}) or {}
    v = verdict or basket.get("directive")
    return {
        "ticker": basket.get("ticker"),
        "verdict": v,
        "side": infer_side(v),
        "price": ladder.get("price"),                  # engine ladder only — not agent-supplied
        "legs": {k: ladder.get(k) for k in ("floor", "bear", "base", "bull")},
        "rho": asym.get("rho"),
        "phi": asym.get("floor_coverage"),
        "jsf_cap": gate.get("cap"),
        "archetype": basket.get("archetype"),
    }
