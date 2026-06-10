"""
Shared what-if action logic (Iteration 2 — the action spine).

Pure helpers (no engine / numpy / fastapi import) so the math is unit-testable on
its own. The engine method ``Engine.run_whatif`` supplies the live router + base
inputs and calls these; the FastAPI route ``POST /action/whatif`` and the MCP tool
``run_valuation_whatif`` are thin wrappers over that one method — so the GUI, the
TUI, the Claude/agy panes and the agents all hit the same implementation.

Override grammar (one string or a dict):
    "silver=+5 ry=-0.5 peer=+20%"
  value forms:  79.8 (absolute) · +5 / -0.5 (delta) · +20% / -10% (percent of base)
  knobs:        silver/ag, gold, ry (real yield), vol, peer (EV/oz), mri, dxy
"""

from __future__ import annotations

# User-facing knob -> canonical engine input key.
ALIASES = {
    "silver": "spot_ag", "ag": "spot_ag", "spot_ag": "spot_ag",
    "gold": "gold", "au": "gold",
    "ry": "real_yield", "real_yield": "real_yield", "yield": "real_yield", "yields": "real_yield",
    "vol": "silver_vol", "silver_vol": "silver_vol",
    "peer": "peer_ev_oz", "ev": "peer_ev_oz", "peer_ev_oz": "peer_ev_oz",
    "mri": "mri", "regime": "mri",
    "dxy": "dxy",
    "capital_discount": "capital_discount",
}

# Canonical keys that feed the regime vector (recompute regime if any of these move).
REGIME_KEYS = {"real_yield", "silver_vol", "mri", "dxy"}
# Canonical keys that live in the payload's macro block.
MACRO_KEYS = {"spot_ag", "gold", "real_yield", "silver_vol", "capital_discount"}


def canonical(key: str):
    return ALIASES.get(str(key).strip().lower())


def parse_override(spec, base):
    """Resolve one override value against its base.

    number / "79.8" -> absolute · "+5"/"-0.5" -> delta from base · "+20%"/"-10%" -> percent of base.
    """
    if isinstance(spec, (int, float)):
        return float(spec)
    s = str(spec).strip()
    if not s:
        raise ValueError("empty override")
    try:
        if s.endswith("%"):
            if base is None:
                raise ValueError("percent override needs a base value")
            return float(base) * (1.0 + float(s[:-1]) / 100.0)
        if s[0] in "+-":
            return (float(base) if base is not None else 0.0) + float(s)
        return float(s)
    except ValueError as exc:
        raise ValueError(f"bad override value {spec!r}: {exc}")


def parse_overrides(text):
    """'silver=+5 ry=-0.5 peer=+20%' (or a dict) -> {canonical_key: raw_spec}, unknown knobs dropped."""
    if isinstance(text, dict):
        pairs = list(text.items())
    else:
        pairs = []
        for tok in str(text or "").replace(",", " ").split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                pairs.append((k, v))
    out = {}
    for k, v in pairs:
        ck = canonical(k)
        if ck is not None:
            out[ck] = v
    return out


def _upside(summary: dict, price):
    iv = summary.get("intrinsic_after_forensic")
    try:
        if price and iv is not None:
            return round((float(iv) / float(price) - 1.0) * 100.0, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


def summarize_delta(base: dict, scenario: dict, price, applied: dict) -> dict:
    """Diff two valuation_summary dicts into a compact base/scenario/delta report."""
    bi = base.get("intrinsic_after_forensic")
    si = scenario.get("intrinsic_after_forensic")
    try:
        intrinsic_pct = round((si / bi - 1.0) * 100.0, 1) if (bi and si) else None
    except (TypeError, ZeroDivisionError):
        intrinsic_pct = None
    bu, su = _upside(base, price), _upside(scenario, price)
    return {
        "price": price,
        "overrides_applied": applied,
        # legs/weights/breakdown pass through so a Story Card can decompose the intrinsic + find its
        # breakpoint without a second engine round-trip (additive — older readers ignore the extras).
        "base": {"intrinsic": bi, "upside_pct": bu, "legs": base.get("legs"),
                 "weights": base.get("weights"), "breakdown": base.get("component_breakdown")},
        "scenario": {"intrinsic": si, "upside_pct": su, "legs": scenario.get("legs"),
                     "weights": scenario.get("weights"), "breakdown": scenario.get("component_breakdown")},
        "delta": {
            "intrinsic_pct": intrinsic_pct,
            "upside_pp": (round(su - bu, 1) if (su is not None and bu is not None) else None),
        },
    }


def _money(v) -> str:
    try:
        return f"CA${float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def story_card(summary: dict, *, price=None, ticker=None, drivers: dict = None) -> dict:
    """Narrative→number Story Card (Damodaran discipline): decompose an intrinsic into its named
    components, the drivers behind it, and the BREAKPOINT — the move that takes the thesis to its
    kill-switch (intrinsic → price). Accepts a raw archetype valuation_summary (to_dict) OR the
    enriched whatif 'base'/'scenario' sub-dict.

    Reconciliation discipline (the parts must equal the whole): each leg's ``contribution_cad`` is
    its POST-weight, POST-forensic share — Σ contribution_cad == intrinsic_after_forensic. Raw leg
    values (pre-weight, pre-penalty) stay visible as ``value_cad`` detail, but the build-up the
    operator reads sums to the number on the card, never past it.

    Breakpoint discipline: the engine's spot linkage is LINEAR — value ∝ max(0, 1+β·(spot/ref−1))
    (engine.calculate_ballast_fair_value) — so the solve inverts THAT model (exact when the leg
    detail carries ``spot_ref``; first-order otherwise, labelled). For the spear (explorer market
    leg = ounces × peer EV/oz; no spot linkage by design) the breakpoint routes through the peer
    multiple instead — the sensitivity that actually exists."""
    summary = summary or {}
    iv = summary.get("intrinsic_after_forensic")
    if iv is None:
        iv = summary.get("intrinsic", summary.get("blended_intrinsic"))
    legs = summary.get("legs") or {}
    weights = summary.get("weights") or {}
    cb = summary.get("component_breakdown") or summary.get("breakdown") or {}
    forensic = (cb.get("forensic") or {}).get("score")

    # implied forensic penalty: iv = penalty × Σ(legs×weights). Derived (not read) so it works for
    # both the raw summary and the whatif sub-dict, and the build-up reconciles by construction.
    blended = sum((legs.get(k) or 0.0) * (weights.get(k) or 0.0) for k in legs)
    penalty = summary.get("forensic_penalty")
    if penalty is None:
        penalty = (iv / blended) if (iv is not None and blended) else 1.0

    build_up, contrib = [], {}
    for leg in ("cost", "market", "income"):
        d = cb.get(leg) or {}
        if leg in legs or d:
            lv, w = legs.get(leg), weights.get(leg)
            c = (lv * w * penalty) if (lv is not None and w is not None) else None
            if c is not None:
                contrib[leg] = c
            build_up.append({"leg": leg, "method": d.get("method"),
                             "value_cad": d.get("value_cad", legs.get(leg)),
                             "weight": w,
                             "contribution_cad": round(c, 4) if c is not None else None})
    build_up_total = round(sum(contrib.values()), 4) if contrib else None

    # Phase 5 (validation flywheel): ensemble dispersion across the legs — each leg is an
    # independent valuation method; the disagreement is itself a signal (tight cluster = trust
    # the number; wide spread = flag it). Surfaced beside the build-up, recorded in the ledger.
    spread = None
    try:
        from valuation_ledger import method_spread as _method_spread
        spread = _method_spread(legs, weights)
    except Exception:
        spread = None

    mkt = cb.get("market") or {}
    drv = dict(drivers or {})
    if mkt.get("spot_now") is not None and "spot" not in drv:
        drv["spot"] = mkt.get("spot_now")

    upside_pct = None
    if price and iv:
        try:
            upside_pct = round((iv / price - 1.0) * 100.0, 1)
        except ZeroDivisionError:
            upside_pct = None

    breakpoint_ = None
    if price and iv and iv > 0:
        drop_to_price = round((1.0 - price / iv) * 100.0, 1)        # % intrinsic must fall to meet price
        breakpoint_ = {"to": "price", "intrinsic_drop_pct": drop_to_price}
        # POST-penalty market contribution — the share of the CARD's intrinsic that moves with the
        # driver. (Using the raw pre-penalty leg here made parts exceed the whole and non_mkt go
        # negative — the V5 audit bug.)
        contrib_abs = contrib.get("market")
        if contrib_abs is None and mkt.get("value_cad") is not None:
            w_mkt = weights.get("market")
            contrib_abs = mkt["value_cad"] * (w_mkt if w_mkt is not None else 1.0) * penalty
        beta, spot_now, spot_ref = mkt.get("spot_beta"), mkt.get("spot_now"), mkt.get("spot_ref")
        peer_ev = mkt.get("peer_ev_oz")
        gap_note = ("the smooth-path break only — juniors also break on DISCRETE gaps "
                    "(a discounted financing / drill miss) no driver solve captures.")
        if contrib_abs and contrib_abs > 0 and iv > 0:
            non_mkt = max(0.0, iv - contrib_abs)        # the rest of the card, held fixed vs the driver
            ratio = (price - non_mkt) / contrib_abs     # required market-contribution multiple
            if beta is not None and beta < 0:
                breakpoint_["beta_warning"] = (f"spot_beta {beta:g} < 0 — an inverse commodity linkage "
                                               f"is almost certainly a config error; verify before "
                                               f"trusting this breakpoint.")
            if beta and spot_now:
                # ---- spot-linked leg (ballast): invert the engine's LINEAR model ----
                bp = {"commodity": mkt.get("commodity") or drv.get("commodity"), "spot_now": spot_now,
                      "gap_note": gap_note}
                if ratio <= 0:                          # non-spot floor already ≥ price
                    bp.update({"spot_break": None, "spot_move_pct": None,
                               "method": ("spot alone cannot reach price (floor ≥ px) — only dilution / "
                                          "a de-rating breaks the thesis here.")})
                elif spot_ref and spot_ref > 0:
                    # exact under the engine model: F(s)=1+β(s/ref−1); F(s*)=ratio·F(s0)
                    f0 = 1.0 + beta * (spot_now / spot_ref - 1.0)
                    f_star = ratio * f0
                    if f0 <= 0 or f_star <= 0:          # engine floors the leg at 0 — spot can't get there
                        bp.update({"spot_break": None, "spot_move_pct": None,
                                   "method": ("spot alone cannot reach price under the engine's floored "
                                              "linear linkage — only dilution / a de-rating breaks it.")})
                    else:
                        s_star = spot_ref * ((f_star - 1.0) / beta + 1.0)
                        bp.update({"spot_break": round(s_star, 4),
                                   "spot_move_pct": round((s_star / spot_now - 1.0) * 100.0, 1),
                                   "method": ("linear spot linkage (engine-exact: value ∝ "
                                              "1+β·(spot/ref−1))")})
                else:
                    # no spot_ref in the payload — first-order around spot_now, labelled as such
                    s_star = spot_now * (1.0 + (ratio - 1.0) / beta)
                    bp.update({"spot_break": round(s_star, 4),
                               "spot_move_pct": round((s_star / spot_now - 1.0) * 100.0, 1),
                               "method": ("first-order linear (no spot_ref in payload — exact only "
                                          "when spot_ref ≈ spot_now)")})
                breakpoint_.update(bp)
            elif peer_ev and peer_ev > 0:
                # ---- the spear: explorer market leg ∝ peer EV/oz (linear); no spot linkage exists,
                #      so the kill-switch is a peer-multiple de-rate (and the discrete financing gap) ----
                if ratio <= 0:
                    breakpoint_.update({"peer_ev_break": None, "peer_ev_move_pct": None,
                                        "method": ("the non-market floor already covers price — only "
                                                   "dilution / a forensic de-rate breaks the thesis.")})
                else:
                    breakpoint_.update({"peer_ev_now": peer_ev,
                                        "peer_ev_break": round(peer_ev * ratio, 4),
                                        "peer_ev_move_pct": round((ratio - 1.0) * 100.0, 1),
                                        "method": ("peer EV/oz sensitivity (explorer market leg ∝ peer "
                                                   "multiple; spot is decoupled by design)")})
                breakpoint_["gap_note"] = gap_note
    return {"ticker": ticker, "intrinsic": iv, "price": price, "upside_pct": upside_pct,
            "build_up": build_up, "build_up_total": build_up_total,
            "method_spread": spread,
            "forensic_penalty": (round(penalty, 4) if penalty is not None else None),
            "forensic_score": forensic, "drivers": drv,
            "breakpoint": breakpoint_}


def ladder_expectation(ladder: dict, *, p: dict = None, price=None) -> dict:
    """V2 — probability-weighted scenario NAV, done honestly.

    With operator/agent-supplied probabilities (``p = {bear, base, bull}``, summing to ~1):
    returns the expected value across the engine's frozen ladder legs, the edge vs price, and the
    spread — labelled as resting entirely on the SUPPLIED p (provenance, not authority).

    WITHOUT supplied probabilities it refuses to invent any. Instead it INVERTS the question —
    the Druckenmiller frame: *what would you have to believe for this price to be fair?*
      • ``p_bull_breakeven`` — the P(bull, vs bear) at which E[V] == price in the two-state frame:
        p·bull + (1−p)·bear = price. Below-breakeven conviction means the price is paying you.
      • ``p_base_floor_breakeven`` — same inversion on the conservative base-vs-floor pair.
    A breakeven is a bar to clear, not a forecast — nothing here fabricates a probability."""
    ladder = ladder or {}

    def _n(k):
        v = ladder.get(k)
        try:
            f = float(v)
            return f if f == f else None
        except (TypeError, ValueError):
            return None
    floor, bear, base, bull = _n("floor"), _n("bear"), _n("base"), _n("bull")
    px = None
    try:
        px = float(price) if price is not None else _n("price")
    except (TypeError, ValueError):
        px = None

    out: dict = {"legs": {"floor": floor, "bear": bear, "base": base, "bull": bull}, "price": px}

    if p:
        pb, pm, pu = (p.get("bear"), p.get("base"), p.get("bull"))
        try:
            pb, pm, pu = float(pb), float(pm), float(pu)
        except (TypeError, ValueError):
            return {**out, "error": "p must supply numeric bear/base/bull probabilities"}
        tot = pb + pm + pu
        if not (0.97 <= tot <= 1.03) or min(pb, pm, pu) < 0:
            return {**out, "error": f"probabilities must be ≥0 and sum to ~1 (got {tot:.3f})"}
        if None in (bear, base, bull):
            return {**out, "error": "ladder is missing a leg (bear/base/bull) — cannot weight it"}
        pb, pm, pu = pb / tot, pm / tot, pu / tot          # renormalize the rounding slack
        ev = pb * bear + pm * base + pu * bull
        out.update({
            "mode": "supplied_p",
            "p": {"bear": round(pb, 4), "base": round(pm, 4), "bull": round(pu, 4)},
            "expected_value": round(ev, 4),
            "edge_pct": (round((ev / px - 1.0) * 100.0, 1) if px else None),
            "spread": round(bull - bear, 4),
            "note": ("E[V] rests ENTIRELY on the supplied probabilities — they are the operator's "
                     "judgment, not a measurement; record them with the decision so they're gradeable."),
        })
        return out

    # no probabilities supplied → invert (never invent)
    out["mode"] = "breakeven_inversion"
    if px is not None and bull is not None and bear is not None and bull > bear:
        pstar = (px - bear) / (bull - bear)
        out["p_bull_breakeven"] = round(min(1.0, max(0.0, pstar)), 4)
        if pstar > 1.0:
            out["read"] = "price ABOVE the bull leg — no belief in this ladder justifies it"
        elif pstar < 0.0:
            out["read"] = "price below the BEAR leg — paid to be wrong on this ladder"
        else:
            out["read"] = (f"the price is fair only if P(bull vs bear) ≥ {pstar:.0%} — "
                           f"clear that bar with evidence, or the tape is offering you edge")
    if px is not None and base is not None and floor is not None and base > floor:
        pf = (px - floor) / (base - floor)
        out["p_base_floor_breakeven"] = round(min(1.0, max(0.0, pf)), 4)
    out["note"] = ("no probabilities supplied — breakevens are the bar to clear, not a forecast "
                   "(we don't invent P; supply p={bear,base,bull} for an explicit E[V]).")
    return out


def render_story_card(card: dict) -> str:
    """One compact line-set for pin_insight / the cockpit — the story and its kill-switch, legibly."""
    card = card or {}
    iv, px, tk = card.get("intrinsic"), card.get("price"), (card.get("ticker") or "—")
    head = f"STORY · {tk} — intrinsic {_money(iv)}"
    if px:
        up = card.get("upside_pct")
        head += f" vs px {_money(px)}" + (f" ({up:+.0f}%)" if up is not None else "")
    parts = []
    for c in card.get("build_up") or []:
        # the contribution is what sums to the intrinsic on the card; the raw leg value is detail
        val = c.get("contribution_cad") if c.get("contribution_cad") is not None else c.get("value_cad")
        seg = f"{c['leg']} {_money(val)}"
        if c.get("method"):
            seg += f" ({c['method']})"
        parts.append(seg)
    build = ("  = " + " + ".join(parts)) if parts else ""
    fp = card.get("forensic_score")
    if fp is not None:
        build += f"  [forensic {fp:g}]"
    ms = card.get("method_spread") or {}
    if ms.get("spread_pct") is not None:
        build += f"  [methods spread {ms['spread_pct']:.0f}% across {ms.get('n_methods')}]"
    drv = card.get("drivers") or {}
    drv_txt = ("\n  drivers: " + " · ".join(
        (f"{k} {v:g}" if isinstance(v, (int, float)) else f"{k} {v}") for k, v in drv.items())) if drv else ""
    bp = card.get("breakpoint") or {}
    bp_txt = ""
    if bp:
        bp_txt = f"\n  breaks → price at −{bp.get('intrinsic_drop_pct')}% intrinsic"
        if bp.get("spot_break") is not None:
            bp_txt += f" ≈ {bp.get('commodity') or 'spot'} {_money(bp.get('spot_break'))} ({bp.get('method')})"
        elif bp.get("peer_ev_break") is not None:
            bp_txt += (f" ≈ peer EV/oz {_money(bp.get('peer_ev_break'))} "
                       f"({bp.get('peer_ev_move_pct'):+.0f}% de-rate; {bp.get('method')})")
    ev = card.get("scenario_ev") or {}
    ev_txt = ""
    if ev.get("mode") == "supplied_p" and ev.get("expected_value") is not None:
        edge = ev.get("edge_pct")
        ev_txt = (f"\n  E[V] {_money(ev['expected_value'])} on supplied p"
                  + (f" ({edge:+.0f}% vs px)" if edge is not None else ""))
    elif ev.get("p_bull_breakeven") is not None:
        ev_txt = f"\n  must believe → P(bull) ≥ {ev['p_bull_breakeven']:.0%} for px to be fair"
    return head + build + drv_txt + bp_txt + ev_txt
