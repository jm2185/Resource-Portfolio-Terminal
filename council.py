"""
The Dialectic Council reconciler (Forge Phase 2) — one verdict, dissent as caveat.

The Council is two advocates and a judge: a **Bull** builds the strongest long case, a **Bear +
Liquidity Sentinel** the strongest invalidation case, each grounding claims in live engine numbers
(ρ, φ, the gate, the ladder); the **Arbiter** reconciles them into a SINGLE call with the tension
named. This module is the Arbiter's deterministic core — the part that must obey the house's
signal-coherence rules exactly, every time, rather than being re-argued by a model each run:

  1. **The engine is the dominant prior.** The reconciliation starts from the engine's own directive
     (BELOW FLOOR — ACCUMULATE, UPSIDE SPENT — TRIM, …). Claims *adjust* it; they never shadow it.
  2. **Grounded beats narrative.** A claim that cites a live engine field moves the verdict more than
     a web/judgment claim. Narrative that contradicts an engine field is flagged.
  3. **The Bear sharpens, it never vetoes the spear.** For an option-convexity name, narrative-only
     bear claims cannot force an EXIT — only engine evidence (a tripped forensic gate, collapsed φ/ρ)
     can. The Bear's job is to set the invalidation level, which rides the one verdict as a caveat.
  4. **The forensic gate caps the Bull.** A severe JSF cap means the engine already says de-risk; no
     volume of bull claims overrides it.
  5. **One verdict; dissent survives only as a flagged caveat** — never a second rival headline.

Regime posture *composes* on top (ACCUMULATE → "ACCUMULATE, smaller / slower" at a 0.75x cap); it
is a book-level dial, never a name-level rival score.

Pure stdlib, fully testable. The agent layer (.claude/agents/bull|bear|arbiter) produces the claims;
this turns them into the coherent verdict and the convergence score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional


# Directive → a bull-share PRIOR in [0,1] (the engine's own call, before the debate adjusts it).
# Matched by keyword so it is robust to the engine's exact phrasing / suffixes.
_DIRECTIVE_PRIOR: list = [
    ("FORENSIC DECAY", 0.15),
    ("AVOID", 0.18),
    ("BELOW FLOOR", 0.72),
    ("BELOW FAIR VALUE", 0.70),
    ("STRONG ASYMMETRY", 0.68),
    ("CORE HOLD", 0.62),
    ("THESIS INTACT", 0.55),
    ("FAIR VALUE", 0.50),
    ("MONITOR", 0.52),
    ("UPSIDE SPENT", 0.38),
    ("RICH", 0.33),
    ("STAND ASIDE", 0.30),
    ("TRIM", 0.36),
    ("ACCUMULATE", 0.68),
    ("HOLD", 0.48),
]

GROUNDED_WEIGHT = 1.0
NARRATIVE_WEIGHT = 0.5
TILT_GAIN = 0.25                 # how far the debate can move the engine prior (engine stays dominant)
TILT_SCALE = 2.0                # tanh sensitivity: scales the move by ABSOLUTE grounded evidence, so
                                # a lone grounded claim moves the verdict more than a lone narrative one
CONTESTED_BAND = (45, 55)        # convergence inside this is "contested" -> tighter downstream pass


@dataclass
class Claim:
    """One debate claim. ``grounded`` = cites a live engine field (``field``); else narrative.
    ``invalidation`` flags a Bear claim that names a hard invalidation level (rides the verdict)."""
    side: str                      # "bull" | "bear"
    text: str
    grounded: bool = False
    field: Optional[str] = None
    weight: float = 1.0
    invalidation: bool = False

    def effective_weight(self) -> float:
        base = GROUNDED_WEIGHT if self.grounded else NARRATIVE_WEIGHT
        return max(0.0, float(self.weight)) * base


def _directive_prior(directive: Optional[str]) -> float:
    d = str(directive or "").upper()
    for key, prior in _DIRECTIVE_PRIOR:
        if key in d:
            return prior
    return 0.50                    # unknown directive -> neutral


def _as_claims(items) -> list:
    out = []
    for c in items or []:
        if isinstance(c, Claim):
            out.append(c)
        elif isinstance(c, dict):
            out.append(Claim(side=c.get("side", "bull"), text=c.get("text", ""),
                             grounded=bool(c.get("grounded", False)), field=c.get("field"),
                             weight=float(c.get("weight", 1.0)),
                             invalidation=bool(c.get("invalidation", False))))
    return out


def _stance_from_share(bull_share: float, *, improving: bool) -> str:
    if bull_share >= 0.66:
        return "PRESS" if improving else "RE-AFFIRM"
    if bull_share >= 0.55:
        return "RE-AFFIRM"
    if bull_share >= 0.45:
        return "HOLD"
    if bull_share >= 0.34:
        return "TRIM"
    return "EXIT / DE-RISK"


def reconcile(facts: dict, bull_claims, bear_claims, *, posture: Optional[dict] = None,
              improving: bool = False) -> dict:
    """Reconcile a Bull and Bear case into one verdict for a name.

    ``facts``: the agent-facing rating projection (ticker, archetype, directive, asymmetry{rho,
    floor_coverage,upside_pct}, gate{applied,cap,reason}, ladder{floor,...}). ``posture``: optional
    book-level regime dial ({code, cap, label}) that composes onto the action. ``improving``: the
    asymmetry got better since last underwrite (lets a strong bull read 'PRESS', the Druck point).
    """
    bull = _as_claims(bull_claims)
    bear = _as_claims(bear_claims)
    archetype = str(facts.get("archetype") or "")
    asym = facts.get("asymmetry") or {}
    gate = facts.get("gate") or {}
    directive = facts.get("directive") or ""

    prior = _directive_prior(directive)
    wb = sum(c.effective_weight() for c in bull)
    wr = sum(c.effective_weight() for c in bear)
    wtot = wb + wr
    # Saturating on ABSOLUTE net evidence (not normalized) so the magnitude of grounded support
    # actually matters: a lone grounded claim moves the prior more than a lone narrative one, and
    # the move is bounded by TILT_GAIN so the engine directive always stays the dominant signal.
    claim_tilt = math.tanh((wb - wr) / TILT_SCALE)               # [-1,1], bull-positive
    bull_share = prior + TILT_GAIN * claim_tilt

    guardrails: list = []

    # Guardrail 4: a severe forensic cap means the engine already says de-risk — cap the bull.
    gate_applied = bool(gate.get("applied"))
    severe_gate = gate_applied and float(gate.get("cap", 10.0) or 10.0) <= 5.0
    if severe_gate:
        bull_share = min(bull_share, 0.25)
        guardrails.append("forensic_gate_caps_bull")

    bull_share = max(0.0, min(1.0, bull_share))

    # Bear's GROUNDED share — only engine-grounded bear evidence can force an exit.
    bear_grounded = sum(c.effective_weight() for c in bear if c.grounded)
    bear_grounded_share = (bear_grounded / wtot) if wtot > 0 else 0.0
    phi = asym.get("floor_coverage")
    rho = asym.get("rho")
    engine_break = bool(severe_gate
                        or (isinstance(phi, (int, float)) and phi < 0.9)
                        or (isinstance(rho, (int, float)) and rho < 0.5))

    stance = _stance_from_share(bull_share, improving=improving)

    # Guardrail 3: the Bear never vetoes the convex spear on narrative alone.
    if archetype == "option_convexity" and stance == "EXIT / DE-RISK" and not engine_break \
            and bear_grounded_share < 0.34:
        stance = "TRIM"
        guardrails.append("bear_no_narrative_veto_on_spear")

    # Convergence (one number, with the contested flag).
    bull_pct = round(bull_share * 100)
    bear_pct = 100 - bull_pct
    contested = CONTESTED_BAND[0] <= bull_pct <= CONTESTED_BAND[1]

    # Tension = the strongest surviving GROUNDED claim on the losing side (dissent named, not hidden).
    losing = bear if bull_share >= 0.5 else bull
    tension = _strongest(losing)

    # Caveats: the Bear's invalidation level (rides the one verdict) + its strongest grounded points.
    caveats = []
    inval = next((c for c in bear if c.invalidation), None)
    if inval is None and isinstance((facts.get("ladder") or {}).get("floor"), (int, float)):
        caveats.append(f"Hard invalidation near the floor "
                       f"${facts['ladder']['floor']:.2f} (φ margin-of-safety leg).")
    elif inval is not None:
        caveats.append(inval.text)
    for c in sorted([c for c in bear if c.grounded and not c.invalidation],
                    key=lambda c: c.effective_weight(), reverse=True)[:2]:
        caveats.append(c.text)

    # Verdict line + regime composition (posture is a book-level dial that composes onto the action).
    verdict_line = f"{stance} • {directive}".strip(" •")
    posture_note = None
    if isinstance(posture, dict) and posture.get("cap") is not None:
        try:
            cap = float(posture["cap"])
            if cap < 1.0 and stance in ("PRESS", "RE-AFFIRM", "HOLD"):
                verdict_line += f"  ({cap:g}x regime cap — accumulate smaller / slower)"
                posture_note = f"regime posture {posture.get('label', posture.get('code', ''))} caps size to {cap:g}x"
            elif cap >= 1.0 and stance in ("PRESS", "RE-AFFIRM"):
                verdict_line += f"  ({cap:g}x regime — tailwind)"
        except (TypeError, ValueError):
            pass

    grounded_ratio = round((sum(1 for c in bull + bear if c.grounded) / len(bull + bear)), 3) \
        if (bull or bear) else 0.0

    return {
        "ticker": facts.get("ticker"),
        "archetype": archetype,
        "stance": stance,
        "engine_directive": directive,
        "verdict_line": verdict_line,
        "convergence": {"bull": bull_pct, "bear": bear_pct, "contested": contested},
        "tension": tension,
        "caveats": caveats,
        "posture_note": posture_note,
        "guardrails_applied": guardrails,
        "grounded_ratio": grounded_ratio,
        "engine_break": engine_break,
    }


def _strongest(claims) -> Optional[str]:
    grounded = [c for c in claims if c.grounded]
    pool = grounded or claims
    if not pool:
        return None
    return max(pool, key=lambda c: c.effective_weight()).text


# --------------------------------------------------------------------------- swap system (Forge M6)
# A swap is NOT a new agent — it's a two-name Council convening: @bull argues the challenger, @bear
# plays incumbent-defender (reads Living Memory for catalysts + computes exit friction from the M3
# liquidity model), and the Arbiter reconciles under a FRICTION-ADJUSTED HURDLE and a CATALYST LOCK.
# Darwinian high-grading without over-trading: you only swap when the *net* edge clears a high bar and
# the incumbent isn't sitting on a near catalyst (don't sell the day before the drill result).
SWAP_HURDLE = 0.35          # net edge a challenger must beat to justify the round-trip
SWAP_LOCK_WINDOW = 30       # days: a catalyst inside this on the incumbent → DEFER (21–45 band; 30 mid)
SLIP_PER_DAY = 0.012        # slippage added per day of liquidation runway (thin junior tape)
SLIP_MAX = 0.20            # cap the slippage estimate
REENTRY_COST = 0.02        # round-trip spread / re-entry friction


def _swap_cfg(config, key, default):
    try:
        v = (((config or {}).get("forge") or {}).get("swap") or {}).get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def estimate_friction(days_90, *, config=None, reentry_cost=None) -> float:
    """Round-trip friction = slippage(from the M3 liquidity runway) + re-entry cost. Illiquid
    incumbents (long runway) cost more to exit — that's the over-trading brake made quantitative."""
    slip_per_day = _swap_cfg(config, "slip_per_day", SLIP_PER_DAY)
    slip_max = _swap_cfg(config, "slip_max", SLIP_MAX)
    reentry = reentry_cost if reentry_cost is not None else _swap_cfg(config, "reentry_cost", REENTRY_COST)
    d = days_90 if isinstance(days_90, (int, float)) and days_90 == days_90 else 0.0
    slippage = max(0.0, min(slip_max, float(d) * slip_per_day))
    return round(slippage + reentry, 4)


def swap_verdict(incumbent: dict, challenger: dict, *, friction: Optional[float] = None,
                 catalyst_days: Optional[float] = None, regime_inflection: bool = False,
                 lock_window: Optional[int] = None, hurdle: Optional[float] = None,
                 config: Optional[dict] = None) -> dict:
    """Reconcile an UP-TIER (swap) proposal under the hurdle + lock. ``incumbent`` / ``challenger`` are
    fact dicts ({ticker, rho, ...}). Returns SWAP / REJECT / DEFER with the arithmetic shown.

      edge      = challenger.rho / incumbent.rho − 1
      net_edge  = edge − friction
      lock      = catalyst_within(incumbent, LOCK_WINDOW) OR regime_inflection_flagged
      ⇒ DEFER if lock (regardless of edge); SWAP if net_edge ≥ HURDLE; else REJECT.
    """
    hurdle = hurdle if hurdle is not None else _swap_cfg(config, "hurdle", SWAP_HURDLE)
    lock_window = lock_window if lock_window is not None else int(_swap_cfg(config, "lock_window",
                                                                            SWAP_LOCK_WINDOW))
    inc_rho = incumbent.get("rho")
    chl_rho = challenger.get("rho")
    if not isinstance(inc_rho, (int, float)) or not isinstance(chl_rho, (int, float)) or inc_rho <= 0:
        return {"decision": "REJECT", "reason": "missing/invalid ρ on a side",
                "incumbent": incumbent.get("ticker"), "challenger": challenger.get("ticker")}
    if friction is None:
        friction = estimate_friction(incumbent.get("days_90"), config=config)
    edge = chl_rho / inc_rho - 1.0
    net_edge = edge - friction

    catalyst_lock = (catalyst_days is not None and catalyst_days <= lock_window) or bool(regime_inflection)
    if catalyst_lock:
        decision = "DEFER"
        if catalyst_days is not None and catalyst_days <= lock_window:
            rationale = (f"DEFER — {incumbent.get('ticker')} has a catalyst in {catalyst_days:g}d "
                         f"(≤ {lock_window}d lock): don't sell into it. Re-run after.")
        else:
            rationale = (f"DEFER — regime inflection flagged: hold the book steady before re-tiering.")
    elif net_edge >= hurdle:
        decision = "SWAP"
        rationale = (f"SWAP — net edge {net_edge:+.1%} clears the {hurdle:.0%} hurdle "
                     f"(edge {edge:+.1%} − friction {friction:.1%}).")
    else:
        decision = "REJECT"
        rationale = (f"REJECT — net edge {net_edge:+.1%} below the {hurdle:.0%} hurdle "
                     f"(edge {edge:+.1%} − friction {friction:.1%}). Not worth the round-trip.")

    return {
        "decision": decision,
        "incumbent": incumbent.get("ticker"), "challenger": challenger.get("ticker"),
        "edge": round(edge, 4), "friction": round(friction, 4), "net_edge": round(net_edge, 4),
        "hurdle": hurdle, "lock_window": lock_window, "catalyst_lock": catalyst_lock,
        "days_to_catalyst": catalyst_days, "regime_inflection": bool(regime_inflection),
        "rho": {"incumbent": inc_rho, "challenger": chl_rho},
        "rationale": rationale,
    }


def swap_to_memory_entry(verdict: dict) -> dict:
    """Shape a swap verdict for living_memory.write(type='decision', ...) / the PIPELINE UP-TIER panel."""
    return {
        "type": "decision",
        "ticker": verdict.get("challenger"),
        "text": (f"UP-TIER {verdict.get('decision')}: {verdict.get('challenger')} vs "
                 f"{verdict.get('incumbent')} — {verdict.get('rationale')}"),
        "tags": ["swap", "up_tier", str(verdict.get("decision", "")).lower()],
        "meta": verdict,
    }


def to_memory_entry(verdict: dict) -> dict:
    """Shape a reconciled verdict for living_memory.write(type='council_verdict', ...)."""
    conv = verdict.get("convergence", {})
    text = (f"{verdict.get('stance')} — {verdict.get('verdict_line')} "
            f"[{conv.get('bull')}/{conv.get('bear')}"
            f"{' CONTESTED' if conv.get('contested') else ''}]")
    return {
        "type": "council_verdict",
        "ticker": verdict.get("ticker"),
        "text": text,
        "tags": ["council"] + (["contested"] if conv.get("contested") else [])
        + (verdict.get("guardrails_applied") or []),
        "meta": {
            "stance": verdict.get("stance"),
            "convergence": conv,
            "tension": verdict.get("tension"),
            "caveats": verdict.get("caveats"),
            "engine_directive": verdict.get("engine_directive"),
            "grounded_ratio": verdict.get("grounded_ratio"),
        },
    }
