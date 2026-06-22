"""
Divergence / decoupling SENTINEL — catch a name DECOUPLING from its dominant factor on real flow.

A +12% move WITH silver is leverage — boring, fully explained by beta. A +12% move AGAINST a down-silver
tape on 4× volume is the stock decoupling from its primary driver: a discrete, stock-specific force
overrode the macro, and the volume confirms real flow (not a thin-tape wick). Beta can't decouple a name
from its factor and push it the other way on size — so a flagged event is something specific (an
accumulator, an index add, a leaked corporate event, a promo, insider buying), NOT leverage.

The math (per name, per session):

    expected = beta * factor_return         # what the dominant factor (e.g. silver) explains
    residual = name_return - expected        # the UNEXPLAINED move — the decoupling
    rvol     = volume / ADV                   # relative volume — real flow vs a thin-tape wick
    FLAG when  |residual| >= residual_min  AND  rvol >= rvol_min     (decoupled AND on size)

This module only DETECTS the signature; the triage (/explain-move) ranks the cause and the calibration
flywheel adjudicates the follow-through — the information is in what happens NEXT, not in the candle.
One-directional: a SENTINEL event, NEVER a name-level score or a trade trigger. Pure + dependency-free;
thresholds tunable via /confirm (`divergence_monitor.*`); graceful on thin inputs; no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_DIVERGENCE_CONFIG", "DIVERGENCE_GLOSSARY", "divergence_tooltip", "assess",
           "explain_context", "factor_for", "baseline_from_returns", "assess_book", "select_fresh"]

#: commodity → (the dominant factor a name of this metal decouples FROM, the ETF basket to check for a
#: mechanical/index add). The broad-tape default catches diversified holdcos / unknown sleeves.
_FACTOR_BY_COMMODITY: dict[str, tuple] = {
    "silver": ("silver", "SILJ / SILX (junior silver)"),
    "ag": ("silver", "SILJ / SILX (junior silver)"),
    "gold": ("gold", "GDXJ / GOAU + the gold-royalty ETFs"),
    "au": ("gold", "GDXJ / GOAU + the gold-royalty ETFs"),
    "uranium": ("uranium", "URA / URNM / Sprott Physical Uranium (U.UN)"),
    "u": ("uranium", "URA / URNM / Sprott Physical Uranium (U.UN)"),
    "copper": ("copper", "COPX (copper miners)"),
    "cu": ("copper", "COPX (copper miners)"),
    "cobalt": ("cobalt", "BATT / LIT (battery metals)"),
    "co": ("cobalt", "BATT / LIT (battery metals)"),
    "nickel": ("nickel", "BATT / LIT (battery metals)"),
    "ni": ("nickel", "BATT / LIT (battery metals)"),
    "lithium": ("lithium", "LIT (lithium / battery)"),
    "li": ("lithium", "LIT (lithium / battery)"),
}
_BROAD_FACTOR = ("the broad resource tape (XME / GDX) and its largest sleeve", "XME / GDX (broad miners)")

DEFAULT_DIVERGENCE_CONFIG: dict[str, Any] = {
    "z_min": 2.5,              # |residual| ≥ this many σ of the name's OWN residual vol → decoupled (context-aware)
    "residual_min": 0.06,      # absolute fallback when no σ is supplied: |unexplained move| ≥ 6%
    "rvol_min": 3.0,           # volume ≥ 3× ADV — real flow, not a thin-tape wick
}

DIVERGENCE_GLOSSARY: dict[str, dict[str, str]] = {
    "divergence": {
        "what": "Decoupling SENTINEL — a name moving on its OWN (residual = move − β×factor) on heavy volume (rvol = volume/ADV). A stock-specific force overrode the dominant factor.",
        "scale": "FLAG when |residual| ≥ ~6% AND rvol ≥ ~3×. Up-residual = stock-specific strength; down-residual = weakness.",
        "influence": "A SENTINEL event, never a trade trigger or a name score — it arms the /explain-move triage and a follow-through watch. The information is in what happens next.",
        "edge": "Beta can't decouple a name from its factor and push it the other way on size, so a flagged event is a discrete force (accumulator / index add / leaked event / promo / insider), not leverage.",
    },
}


def divergence_tooltip(key: str) -> str:
    e = DIVERGENCE_GLOSSARY.get(key)
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


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_DIVERGENCE_CONFIG)
    block = (config or {}).get("divergence_monitor", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def explain_context(*, ticker: str = "", archetype: str = "", commodity: str = "",
                    slot: str = "", subarchetype: str = "") -> dict:
    """Type-specific facets for the /explain-move triage, so the prompt fits the NAME instead of a
    silver-explorer template: its dominant FACTOR + the ETF basket to check, whether a DRILL-RESULT leak
    even applies (only pre-revenue explorers/developers drill — NOT royalties, holdcos, producers, or
    physical vehicles), the right INSIDER filing system (SEDI for Canadian listings, SEC Form 4 for US),
    and an archetype-appropriate CORPORATE-event flavour. Pure; graceful — unknown type → broad default."""
    arch = str(archetype or "").strip().lower()
    comm = str(commodity or "").strip().lower()
    slot_l = str(slot or "").strip().lower()
    sub_l = str(subarchetype or "").strip().lower()

    if not comm:                                          # infer the metal from the slot when untagged
        comm = ("silver" if "silver" in slot_l else "gold" if "gold" in slot_l
                else "uranium" if ("electrif" in slot_l or "uranium" in slot_l) else "")
    factor, etfs = _FACTOR_BY_COMMODITY.get(comm, _BROAD_FACTOR)

    is_holdco = any(k in (slot_l + " " + sub_l) for k in ("holdco", "generator"))
    if is_holdco:
        kind, drill = "project-generator / holdco", False
        corporate = "a stake / spinout, a project-generator deal, a financing, or a strategic investor"
    elif arch == "asset_light_yield":
        kind, drill = "royalty / streamer", False
        corporate = "a royalty/stream ACQUISITION, a portfolio add, a financing to fund a deal, or a strategic investor"
    elif arch == "pure_macro_delta":
        kind, drill = "physical / passive vehicle", False
        corporate = "a large unit subscription, a NAV premium/discount shift, or a physical-holdings change"
    elif arch in ("commodity_cyclical", "capital_margin"):
        kind, drill = "producer / operating", False
        corporate = "a production / guidance update, a contract award, a financing, or M&A"
    else:                                                 # option_convexity explorer / developer
        kind, drill = "explorer / developer", True
        corporate = "a financing, a JV / earn-in, M&A, a strategic investor, or a TSX board graduation"

    tk = str(ticker or "").upper()
    if any(tk.endswith(s) for s in (".V", ".TO", ".CN", ".NE", ".TSX", ".TSXV")):
        insider = "SEDI / canadianinsider (Canada — 5 calendar-day filing lag, so a spike-day buy is invisible today)"
    elif tk and ("." not in tk or tk.endswith(".OTC")):
        insider = "SEC Form 4 / EDGAR (US — 2 business-day filing lag)"
    else:
        insider = "the relevant insider system (SEDI for Canada, SEC Form 4 for the US)"

    return {"factor": factor, "etfs": etfs, "drill_relevant": bool(drill), "corporate": corporate,
            "insider": insider, "kind": kind}


def assess(*, name_return: Any = None, factor_return: Any = None, beta: Any = None,
           volume: Any = None, adv: Any = None, residual_sigma: Any = None,
           name: str = "", factor: str = "silver", config: Optional[dict] = None) -> dict:
    """Assess a name's decoupling from its dominant factor this session. ``name_return`` / ``factor_return``
    are fractional session returns (0.12 = +12%); ``beta`` is the name's sensitivity to the factor (defaults
    to 1.0 if unknown — robust because the flag fires on a LARGE residual). ``residual_sigma`` is the name's
    OWN typical residual volatility (std of move − β·factor over a lookback); when given, the threshold is
    CONTEXT-AWARE — |residual| ≥ z_min·σ — so a +6% decouple flags for a low-vol royalty but not for the
    high-vol spear (it falls back to an absolute % when no σ). Returns the residual, relative volume, the
    FLAG (decoupled AND on size), a plain read, and the SENTINEL event payload. Missing returns ⇒ dormant."""
    cfg = _cfg(config)
    nr, fr, b = _num(name_return), _num(factor_return), _num(beta)
    vol, adv_ = _num(volume), _num(adv)

    if nr is None or fr is None:
        return {"available": False, "flag": False, "name": name, "factor": factor,
                "residual": None, "rvol": None, "z": None, "read": "decoupling n/a (need name + factor returns)",
                "flags": [], "events": [], "glossary": {k: divergence_tooltip(k) for k in DIVERGENCE_GLOSSARY}}

    beta_used = b if b is not None else 1.0
    expected = beta_used * fr
    residual = nr - expected
    rvol = (vol / adv_) if (vol is not None and adv_ is not None and adv_ > 0) else None
    explained = (expected / nr) if nr not in (0.0, None) else None
    sign_divergence = (nr > 0.0 > fr) or (nr < 0.0 < fr)

    # CONTEXT-AWARE threshold: normalize the residual by the name's OWN residual σ when supplied — a +6%
    # decouple is normal for the high-vol spear but an earthquake for a low-vol royalty, so "decoupled"
    # must mean "beyond normal FOR THIS NAME". Falls back to an absolute % when no σ is available.
    sig = _num(residual_sigma)
    z = (residual / sig) if (sig is not None and sig > 0) else None
    residual_min, rvol_min, z_min = float(cfg["residual_min"]), float(cfg["rvol_min"]), float(cfg["z_min"])
    decoupled = (abs(z) >= z_min) if z is not None else (abs(residual) >= residual_min)
    on_size = rvol is not None and rvol >= rvol_min
    flag = bool(decoupled and on_size)
    direction = "STRENGTH" if residual > 0 else ("WEAKNESS" if residual < 0 else "—")

    rvol_txt = f"{rvol:.1f}×" if rvol is not None else "rvol n/a"
    z_txt = f" ({z:+.1f}σ)" if z is not None else ""
    read = (f"{name or 'name'} {nr * 100:+.1f}% vs {factor} {fr * 100:+.1f}% "
            f"(β{beta_used:.1f} explains {expected * 100:+.1f}%) → {residual * 100:+.1f}% unexplained{z_txt} on {rvol_txt}")
    if flag:
        read += f" — DECOUPLED on size: a discrete stock-specific {direction.lower()}, not leverage"

    flags, events = [], []
    if flag:
        flags.append({"id": "stock_specific_force", "active": True, "level": "info",
                      "text": (f"{name or 'name'} decoupled from {factor} ({residual * 100:+.1f}% unexplained) "
                               f"on {rvol_txt} — a discrete stock-specific force; run /explain-move")})
        events.append({"type": "divergence", "level": "info", "ticker": name,
                       "text": (f"{name or 'name'} {nr * 100:+.1f}% decoupled from {factor} on {rvol_txt} "
                                f"(residual {residual * 100:+.1f}%) — SENTINEL event, adjudicate by follow-through")})

    return {
        "available": True, "flag": bool(flag), "name": name, "factor": factor,
        "name_return": round(nr, 4), "factor_return": round(fr, 4), "beta": round(beta_used, 3),
        "expected": round(expected, 4), "residual": round(residual, 4),
        "z": round(z, 2) if z is not None else None,
        "decoupled_basis": "sigma" if z is not None else "absolute",
        "rvol": round(rvol, 2) if rvol is not None else None,
        "explained_frac": round(explained, 3) if explained is not None else None,
        "sign_divergence": bool(sign_divergence), "direction": direction, "on_size": bool(on_size),
        "read": read, "flags": flags, "events": events,
        "glossary": {k: divergence_tooltip(k) for k in DIVERGENCE_GLOSSARY},
        "note": "a SENTINEL event, never a trade trigger — the information is in the follow-through",
    }


# ---------------------------------------------------------------------------------------------------
# Book-level orchestration — the AUTOMATED sentinel. The engine calls these per cycle so a decoupling
# auto-fires (a pin + a logged event) WITHOUT the operator clicking /explain-move. Pure + dependency-
# free (plain math, no numpy/pandas) so the whole loop is unit-testable off the engine; the engine
# leg only marshals already-cached data (day returns/volume from the prices worker, 60d returns from
# the comps worker) into these — NO new network calls.
# ---------------------------------------------------------------------------------------------------

def factor_for(*, commodity: str = "", slot: str = "", archetype: str = "") -> tuple:
    """Resolve a holding to the dominant-factor KEY the engine caches a session return for
    ("silver" / "gold" / "copper" / "uranium" / …) plus a human label. A diversified holdco /
    project-generator has NO single dominant driver → (None, "broad …") so the book sweep marks it a
    coverage gap honestly instead of forcing a wrong factor onto it. Mirrors explain_context's slot
    inference; pure."""
    comm = str(commodity or "").strip().lower()
    slot_l = str(slot or "").strip().lower()
    if not comm:                                          # infer the metal from the slot when untagged
        comm = ("silver" if "silver" in slot_l else "gold" if "gold" in slot_l
                else "uranium" if ("electrif" in slot_l or "uranium" in slot_l) else "")
    is_holdco = ("holdco" in slot_l or "generator" in slot_l or comm == "diversified")
    if comm in _FACTOR_BY_COMMODITY:                      # an explicit metal wins even on a holdco shell
        return comm, _FACTOR_BY_COMMODITY[comm][0]
    if is_holdco:
        return None, "the broad resource tape (diversified holdco — no single driver)"
    return None, _BROAD_FACTOR[0]


def baseline_from_returns(name_returns: Any, factor_returns: Any, *, fallback_sigma: Any = None,
                          min_n: int = 20) -> dict:
    """Context-aware β + residual σ for a name from its OWN aligned history — the keystone of the
    σ-normalized threshold (a +6% decouple is normal for the high-vol spear, an earthquake for a
    low-vol royalty). OLS-regress the name's session returns on the factor's (β = cov/var), then σ of
    the residual (move − β·factor). The two lists must be DATE-ALIGNED by the caller (the engine pulls
    both from the same comps-worker frame); they're tail-aligned to the shorter length here. Too few
    aligned points (or no factor history) ⇒ fall back to ``fallback_sigma`` (the name's own total vol —
    a CONSERVATIVE σ that makes flags harder, the safe direction) and β=None (assess defaults to 1.0).
    Pure; plain math."""
    nr = [v for v in (_num(x) for x in (name_returns or [])) if v is not None]
    fr = [v for v in (_num(x) for x in (factor_returns or [])) if v is not None]
    n = min(len(nr), len(fr))
    if n >= max(2, int(min_n)):
        a, b = nr[-n:], fr[-n:]
        mb = sum(b) / n
        var = sum((x - mb) ** 2 for x in b)
        if var > 0:
            ma = sum(a) / n
            cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
            beta = cov / var
            resid = [a[i] - beta * b[i] for i in range(n)]
            mr = sum(resid) / n
            sigma = (sum((x - mr) ** 2 for x in resid) / (n - 1)) ** 0.5
            return {"beta": round(beta, 3), "residual_sigma": round(sigma, 5) if sigma > 0 else None,
                    "n": n, "basis": "regression"}
    fb = _num(fallback_sigma)
    return {"beta": None, "residual_sigma": round(fb, 5) if (fb is not None and fb > 0) else None,
            "n": n, "basis": "fallback" if (fb is not None and fb > 0) else "none"}


def assess_book(holdings: Any, *, snapshot: Optional[dict] = None, baseline: Optional[dict] = None,
                config: Optional[dict] = None) -> dict:
    """Run the decoupling sentinel across the whole book in one pass. ``snapshot`` is the per-cycle
    tape the engine already has — ``{"by_ticker": {tk: {day_return, volume, adv}}, "factors":
    {"silver": r, "gold": r, "copper": r}}``; ``baseline`` is ``{tk: {beta, residual_sigma, basis}}``
    from ``baseline_from_returns``. Each holding is routed to its dominant factor (``factor_for``) and
    assessed; a name with no day-return or no cached factor return is listed in ``coverage.missing``
    (e.g. a diversified holdco, or uranium when no U factor is cached) rather than silently skipped —
    the honest-coverage discipline. Returns ``by_ticker`` reads, the ``flags`` that fired, and
    ``coverage``. Pure."""
    snapshot = snapshot or {}
    baseline = baseline or {}
    by_t = snapshot.get("by_ticker") or {}
    factors = snapshot.get("factors") or {}
    out: dict = {}
    flags: list = []
    covered: list = []
    missing: list = []
    for h in (holdings or []):
        tk = str((h or {}).get("ticker") or "").strip()
        if not tk:
            continue
        fac_key, fac_label = factor_for(commodity=(h or {}).get("commodity", ""),
                                        slot=(h or {}).get("slot", ""),
                                        archetype=(h or {}).get("archetype", ""))
        ni = by_t.get(tk) or {}
        nr = _num(ni.get("day_return"))
        fr = _num(factors.get(fac_key)) if fac_key else None
        if nr is None or fr is None:
            reason = ("no day-return (stale/missing mark)" if nr is None
                      else f"no cached {fac_label} session return")
            missing.append({"ticker": tk, "factor": fac_label, "reason": reason})
            out[tk] = {"available": False, "flag": False, "name": tk, "factor": fac_label,
                       "read": f"{tk} decoupling n/a — {reason}"}
            continue
        bl = baseline.get(tk) or {}
        r = assess(name_return=nr, factor_return=fr, beta=bl.get("beta"),
                   volume=ni.get("volume"), adv=ni.get("adv"),
                   residual_sigma=bl.get("residual_sigma"), name=tk, factor=fac_label, config=config)
        r["baseline_basis"] = bl.get("basis")
        out[tk] = r
        covered.append(tk)
        if r.get("flag"):
            flags.append(r)
    return {"available": bool(covered), "by_ticker": out, "flags": flags,
            "coverage": {"covered": covered, "missing": missing}}


def select_fresh(flagged: Any, fired: Optional[dict] = None, *, today: str = "") -> tuple:
    """Dedup the firing so a decoupling pins ONCE per event, not every cycle. ``fired`` is the engine's
    rolling ledger ``{tk: {date, sign}}``; a flag is FRESH when this ticker hasn't fired today OR the
    residual flipped direction since it last fired (a strength→weakness reversal is a new event worth a
    new pin). A multi-session decoupling re-fires the next day BY DESIGN — 'one that holds and builds
    over 2–3 sessions is accumulation or a pending catalyst'. Returns ``(fresh, fired_next)``. Pure."""
    fired_next = dict(fired or {})
    fresh: list = []
    for r in (flagged or []):
        tk = str((r or {}).get("name") or "").strip()
        if not tk:
            continue
        resid = _num((r or {}).get("residual")) or 0.0
        sign = 1 if resid > 0 else (-1 if resid < 0 else 0)
        prev = fired_next.get(tk) or {}
        if prev.get("date") == today and prev.get("sign") == sign:
            continue                                      # same-direction event already pinned today
        fresh.append(r)
        fired_next[tk] = {"date": today, "sign": sign,
                          "residual": round(resid, 4), "rvol": (r or {}).get("rvol")}
    return fresh, fired_next
