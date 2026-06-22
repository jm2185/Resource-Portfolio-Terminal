"""
Fed Net Liquidity monitor — the speculative engine the junior-mining spear actually trades on.

The cockpit tracks the COST of money well (Treasury curve, HY/SOFR spreads, real yields) but was
blind to the QUANTITY of money — the raw dollar liquidity sloshing through the system. Junior
explorers (the high-beta convex spear, AGA.V) do NOT trade on earnings; they trade on excess dollar
liquidity. When net liquidity drains, speculative resource equities get crushed even if the gold
price is unchanged. This is the single most relevant macro tell the regime board was missing for the
convex tier — and the DIRECTION matters far more than the level (a draining balance is the headwind;
the absolute level is context).

Net liquidity (the Fed-balance-sheet proxy) = Fed total assets − Treasury General Account − overnight
reverse repo:

    net_liquidity = WALCL − WDTGAL − RRPONTSYD          (all FRED series)

UNIT CARE (the one gotcha, and exactly why this lives in a tested module): WALCL and WDTGAL are quoted
in $MILLIONS on FRED, RRPONTSYD in $BILLIONS. ``assess`` takes them in their native FRED units (named
params) and normalizes to $billions internally, so the unit alignment is itself unit-tested and can
never silently corrupt the number.

One-directional — a regime/scenario tell, never a name-level score. It belongs to the BROAD-market
(risk-appetite / flows) lens, not the metals-environment lens (gold can be fine while liquidity
drains), but it is unusually relevant to the high-beta spear, so the read says so. Pure +
dependency-free; thresholds tunable via /confirm (`liquidity_monitor.*`); graceful on thin inputs;
no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_LIQUIDITY_CONFIG", "LIQUIDITY_GLOSSARY", "liquidity_tooltip",
           "net_liquidity_bn", "assess"]

DEFAULT_LIQUIDITY_CONFIG: dict[str, Any] = {
    # Net liquidity is huge (~$5–6.5T), so these classify the ~4-week ABSOLUTE move in $billions
    # (not a percentage). Draining is the headwind; expanding is the tailwind for spec juniors.
    "expand_min_bn": 50.0,        # 4w change ≥ +this  → EXPANDING (liquidity tailwind)
    "contract_max_bn": -50.0,     # 4w change ≤ this    → CONTRACTING (headwind)
    "sharp_contract_bn": -150.0,  # 4w change ≤ this    → SHARPLY contracting → flag (spear headwind)
}

LIQUIDITY_GLOSSARY: dict[str, dict[str, str]] = {
    "net_liquidity": {
        "what": "Fed Net Liquidity = Fed total assets − Treasury General Account − overnight reverse repo (WALCL − WDTGAL − RRPONTSYD). The raw dollar liquidity in the system — the fuel speculative junior miners trade on.",
        "scale": "EXPANDING (tailwind for the convex spear) · NEUTRAL · CONTRACTING / SHARPLY-CONTRACTING (headwind — spec resource equities get crushed even with gold flat).",
        "influence": "Broad-market (flows) lens signal + a dedicated regime surface. The DIRECTION drives the read; the level is context. One-directional — never a name score.",
        "edge": "Juniors don't trade on earnings, they trade on excess liquidity. A sharp drain is a direct headwind for the high-beta spear even when the gold price is unchanged.",
    },
}


def liquidity_tooltip(key: str) -> str:
    e = LIQUIDITY_GLOSSARY.get(key)
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
    cfg = dict(DEFAULT_LIQUIDITY_CONFIG)
    block = (config or {}).get("liquidity_monitor", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def net_liquidity_bn(walcl_musd: Any, tga_musd: Any, rrp_busd: Any) -> Optional[float]:
    """Fed net liquidity in $BILLIONS, unit-aligned: WALCL and WDTGAL arrive in $millions (FRED),
    RRPONTSYD in $billions. Returns None if ANY leg is missing — never fabricates a partial."""
    w, t, r = _num(walcl_musd), _num(tga_musd), _num(rrp_busd)
    if w is None or t is None or r is None:
        return None
    return round(w / 1000.0 - t / 1000.0 - r, 1)   # $mn → $bn for WALCL/TGA; RRP already $bn


def assess(*, walcl_musd: Any = None, tga_musd: Any = None, rrp_busd: Any = None,
           prev_walcl_musd: Any = None, prev_tga_musd: Any = None, prev_rrp_busd: Any = None,
           prev_net_liq_bn: Any = None, config: Optional[dict] = None) -> dict:
    """Assess Fed net liquidity from the three FRED legs (native units) + a ~4-week-prior reading for
    the trend. Prior can be passed as the three prior legs OR as a precomputed ``prev_net_liq_bn``.
    Returns the level ($bn and $T), the 4-week change, the direction, the lens bias + read, any flag,
    and the component breakdown. Graceful: missing current legs ⇒ ``available=False`` (dormant)."""
    cfg = _cfg(config)
    level_bn = net_liquidity_bn(walcl_musd, tga_musd, rrp_busd)

    prior_bn = _num(prev_net_liq_bn)
    if prior_bn is None:
        prior_bn = net_liquidity_bn(prev_walcl_musd, prev_tga_musd, prev_rrp_busd)

    available = level_bn is not None
    change_bn = round(level_bn - prior_bn, 1) if (level_bn is not None and prior_bn is not None) else None

    # ---- direction / read --------------------------------------------------
    direction, bias, read = "UNKNOWN", "neutral", "net liquidity n/a"
    flags, events = [], []
    if available and change_bn is None:
        direction, bias = "LEVEL-ONLY", "neutral"
        read = f"Net liquidity ${level_bn / 1000.0:.2f}T (trend n/a — no prior reading)"
    elif available:
        if change_bn <= float(cfg["sharp_contract_bn"]):
            direction, bias = "SHARPLY-CONTRACTING", "risk_off"
            read = f"Liquidity draining hard (${change_bn:+.0f}bn/4w) — direct headwind for the convex spear"
            flags.append({"id": "net_liquidity_drain", "active": True, "level": "warn",
                          "text": (f"NET LIQUIDITY DRAINING SHARPLY ({change_bn:+.0f}bn/4w) — "
                                   "speculative juniors get crushed even with gold flat; size the spear down")})
            events.append({"type": "net_liquidity_drain", "level": "warn",
                           "text": f"Net liquidity contracting sharply ({change_bn:+.0f}bn/4w)"})
        elif change_bn <= float(cfg["contract_max_bn"]):
            direction, bias = "CONTRACTING", "risk_off"
            read = f"Liquidity contracting (${change_bn:+.0f}bn/4w) — headwind for spec resource equities"
        elif change_bn >= float(cfg["expand_min_bn"]):
            direction, bias = "EXPANDING", "risk_on"
            read = f"Liquidity expanding (${change_bn:+.0f}bn/4w) — tailwind for the convex spear"
        else:
            direction, bias = "NEUTRAL", "neutral"
            read = f"Liquidity broadly flat (${change_bn:+.0f}bn/4w)"

    return {
        "available": available,
        "net_liquidity_bn": level_bn,
        "net_liquidity_t": round(level_bn / 1000.0, 2) if level_bn is not None else None,
        "prev_net_liquidity_bn": prior_bn,
        "change_4w_bn": change_bn,
        "direction": direction,
        "bias": bias,
        "read": read,
        "components": {"walcl_musd": _num(walcl_musd), "tga_musd": _num(tga_musd),
                       "rrp_busd": _num(rrp_busd)},
        "flags": flags,
        "events": events,
        "glossary": {k: liquidity_tooltip(k) for k in LIQUIDITY_GLOSSARY},
        "note": "WALCL/WDTGAL are $mn, RRPONTSYD is $bn — unit-aligned to $bn internally",
    }
