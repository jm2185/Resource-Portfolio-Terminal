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
    enriched whatif 'base'/'scenario' sub-dict. Pure; the commodity breakpoint is FIRST-ORDER (a linear
    spot sensitivity), labelled as such — honest about its own precision rather than faking it."""
    summary = summary or {}
    iv = summary.get("intrinsic_after_forensic")
    if iv is None:
        iv = summary.get("intrinsic", summary.get("blended_intrinsic"))
    legs = summary.get("legs") or {}
    weights = summary.get("weights") or {}
    cb = summary.get("component_breakdown") or summary.get("breakdown") or {}

    build_up = []
    for leg in ("cost", "market", "income"):
        d = cb.get(leg) or {}
        if leg in legs or d:
            build_up.append({"leg": leg, "method": d.get("method"),
                             "value_cad": d.get("value_cad", legs.get(leg)),
                             "weight": weights.get(leg)})
    forensic = (cb.get("forensic") or {}).get("score")

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
        beta, spot_now = mkt.get("spot_beta"), mkt.get("spot_now")
        mkt_val, w_mkt = mkt.get("value_cad"), weights.get("market")
        # Translate to a primary-commodity move. The market leg is spot-linked as value ∝ spotᵝ, so the
        # break is CONVEX, not linear (juniors gap; a floored downside curves). Solve the power law
        # EXACTLY rather than first-order — and keep the linear figure beside it so the curvature shows.
        if beta and spot_now and mkt_val and iv > 0:
            contrib_abs = mkt_val * (w_mkt if w_mkt is not None else 1.0)   # market contribution to iv (CAD)
            non_mkt = iv - contrib_abs                                      # the rest (held fixed vs spot)
            contrib = max(0.0, min(1.0, contrib_abs / iv))
            sens = beta * contrib
            move_lin = round(-drop_to_price / sens, 1) if sens > 0 else None  # first-order, for comparison
            note = ("first-order linear understates curvature; juniors also break on DISCRETE gaps "
                    "(a discounted financing / drill miss) that no smooth spot move captures — this is "
                    "the smooth-path break, not the only one.")
            bp = {"commodity": mkt.get("commodity") or drv.get("commodity"), "spot_now": spot_now,
                  "spot_break_linear": (round(spot_now * (1.0 + move_lin / 100.0), 4)
                                        if move_lin is not None else None),
                  "convexity_note": note}
            # exact power-law solve: non_mkt + contrib_abs·mᵝ = price  ⇒  m = ((price−non_mkt)/contrib_abs)^(1/β)
            ratio = (price - non_mkt) / contrib_abs if contrib_abs > 0 else None
            if ratio is not None and ratio > 0:
                m = ratio ** (1.0 / beta)
                bp.update({"spot_break": round(spot_now * m, 4),
                           "spot_move_pct": round((m - 1.0) * 100.0, 1),
                           "method": "power-law spot linkage (exact under value∝spotᵝ)"})
            elif ratio is not None:                  # non-spot floor already ≥ price → spot alone can't break it
                bp.update({"spot_break": None, "spot_move_pct": None,
                           "method": ("spot alone cannot reach price (floor ≥ px) — only dilution / "
                                      "a de-rating breaks the thesis here.")})
            else:
                bp.update({"spot_break": bp["spot_break_linear"], "spot_move_pct": move_lin,
                           "method": "first-order (linear spot sensitivity)"})
            breakpoint_.update(bp)
    return {"ticker": ticker, "intrinsic": iv, "price": price, "upside_pct": upside_pct,
            "build_up": build_up, "forensic_score": forensic, "drivers": drv,
            "breakpoint": breakpoint_}


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
        seg = f"{c['leg']} {_money(c.get('value_cad'))}"
        if c.get("method"):
            seg += f" ({c['method']})"
        parts.append(seg)
    build = ("  = " + " · ".join(parts)) if parts else ""
    fp = card.get("forensic_score")
    if fp is not None:
        build += f"  [forensic {fp:g}]"
    drv = card.get("drivers") or {}
    drv_txt = ("\n  drivers: " + " · ".join(
        (f"{k} {v:g}" if isinstance(v, (int, float)) else f"{k} {v}") for k, v in drv.items())) if drv else ""
    bp = card.get("breakpoint") or {}
    bp_txt = ""
    if bp:
        bp_txt = f"\n  breaks → price at −{bp.get('intrinsic_drop_pct')}% intrinsic"
        if bp.get("spot_break") is not None:
            bp_txt += f" ≈ {bp.get('commodity') or 'spot'} {_money(bp.get('spot_break'))} ({bp.get('method')})"
    return head + build + drv_txt + bp_txt
