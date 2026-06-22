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
           "explain_context"]

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
    "residual_min": 0.06,      # |unexplained move| ≥ 6% — the factor doesn't explain it
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
           volume: Any = None, adv: Any = None, name: str = "", factor: str = "silver",
           config: Optional[dict] = None) -> dict:
    """Assess a name's decoupling from its dominant factor this session. ``name_return`` / ``factor_return``
    are fractional session returns (0.12 = +12%); ``beta`` is the name's sensitivity to the factor (defaults
    to 1.0 if unknown — the flag fires on a LARGE residual, so it's robust to beta imprecision). Returns the
    residual (unexplained move), relative volume, the FLAG (decoupled AND on size), a plain read, and the
    SENTINEL event payload. Graceful: missing returns ⇒ ``available=False`` (dormant)."""
    cfg = _cfg(config)
    nr, fr, b = _num(name_return), _num(factor_return), _num(beta)
    vol, adv_ = _num(volume), _num(adv)

    if nr is None or fr is None:
        return {"available": False, "flag": False, "name": name, "factor": factor,
                "residual": None, "rvol": None, "read": "decoupling n/a (need name + factor returns)",
                "flags": [], "events": [], "glossary": {k: divergence_tooltip(k) for k in DIVERGENCE_GLOSSARY}}

    beta_used = b if b is not None else 1.0
    expected = beta_used * fr
    residual = nr - expected
    rvol = (vol / adv_) if (vol is not None and adv_ is not None and adv_ > 0) else None
    explained = (expected / nr) if nr not in (0.0, None) else None
    sign_divergence = (nr > 0.0 > fr) or (nr < 0.0 < fr)

    residual_min, rvol_min = float(cfg["residual_min"]), float(cfg["rvol_min"])
    on_size = rvol is not None and rvol >= rvol_min
    flag = abs(residual) >= residual_min and on_size
    direction = "STRENGTH" if residual > 0 else ("WEAKNESS" if residual < 0 else "—")

    rvol_txt = f"{rvol:.1f}×" if rvol is not None else "rvol n/a"
    read = (f"{name or 'name'} {nr * 100:+.1f}% vs {factor} {fr * 100:+.1f}% "
            f"(β{beta_used:.1f} explains {expected * 100:+.1f}%) → {residual * 100:+.1f}% unexplained on {rvol_txt}")
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
        "rvol": round(rvol, 2) if rvol is not None else None,
        "explained_frac": round(explained, 3) if explained is not None else None,
        "sign_divergence": bool(sign_divergence), "direction": direction, "on_size": bool(on_size),
        "read": read, "flags": flags, "events": events,
        "glossary": {k: divergence_tooltip(k) for k in DIVERGENCE_GLOSSARY},
        "note": "a SENTINEL event, never a trade trigger — the information is in the follow-through",
    }
