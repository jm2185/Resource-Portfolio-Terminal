"""
Inflation-regime monitor — UNBUNDLE the real yield so we know WHY metals face pressure.

The regime board flags an elevated real yield as a flat "headwind for metals." But real yield is just
nominal − expected inflation, and the two drivers mean opposite things for the book:

  • real yield rising because NOMINAL rates are spiking          → classic gold headwind (tighter policy)
  • real yield rising because INFLATION EXPECTATIONS are falling → a deflationary bust (broad risk-off,
                                                                   a different — often worse — regime)
  • real yield FALLING because breakevens are rising            → the debasement tailwind (best for gold)

A single "headwind" read hides which of these you're in. This monitor decomposes the move:
  - **breakeven inflation** = 10Y nominal − 10Y real (FRED DGS10 − DFII10, or T10YIE directly),
  - **attribution** of the latest real-yield move to its nominal vs breakeven legs (Δreal = Δnominal − Δbe),
  - an **inflation-trend** (momentum) read from the change in breakevens,
  - optionally the Heating / Slowing / Stagflation / Goldilocks **quadrant** when a growth axis is given.

One-directional — it ENRICHES the metals-lens real-yield read and adds a breakeven signal; never a
name-level score. Pure + dependency-free; thresholds tunable via /confirm (`inflation_regime.*`);
graceful on thin inputs; no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_INFLATION_CONFIG", "INFLATION_GLOSSARY", "inflation_tooltip",
           "breakeven", "assess"]

DEFAULT_INFLATION_CONFIG: dict[str, Any] = {
    "be_hot": 2.50,        # breakeven ≥ this (%) = inflation expectations elevated → debasement tailwind
    "be_cold": 2.00,       # breakeven ≤ this (%) = disinflation → headwind / deflationary watch
    "move_min": 0.05,      # |Δ| (%, over the window) below this is treated as flat / noise
}

INFLATION_GLOSSARY: dict[str, dict[str, str]] = {
    "breakeven": {
        "what": "10Y breakeven inflation = nominal 10Y − real 10Y (FRED DGS10 − DFII10). The bond market's expected average inflation — the inflation leg of the real-yield identity.",
        "scale": "≥ ~2.5% = expectations elevated (debasement tailwind for metals) · ~2.0–2.5% anchored · ≤ ~2.0% = disinflation (headwind / deflationary watch).",
        "influence": "Metals-lens signal + it unbundles the real-yield read (the WHY behind the headwind). One-directional — never a name score.",
        "edge": "Rising real yields from spiking NOMINALS (gold headwind) is a different regime than rising real yields from COLLAPSING breakevens (deflationary bust). The decomposition tells them apart.",
    },
    "inflation_regime": {
        "what": "The unbundled real-yield read: breakeven level, what drove the latest real-yield move (nominal vs breakeven leg), the inflation trend, and — with a growth axis — the macro quadrant.",
        "scale": "Drivers: NOMINAL-LED (policy/term-premium) vs BREAKEVEN-LED (inflation expectations). Trend: ACCELERATING vs DECELERATING expectations.",
        "influence": "Enriches the metals-lens real-yield read; standalone regime surface. Never a name-level score.",
    },
}


def inflation_tooltip(key: str) -> str:
    e = INFLATION_GLOSSARY.get(key)
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
    cfg = dict(DEFAULT_INFLATION_CONFIG)
    block = (config or {}).get("inflation_regime", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def breakeven(nominal_10y: Any, real_10y: Any) -> Optional[float]:
    """10Y breakeven inflation = nominal − real (both in %). None if either leg is missing."""
    n, r = _num(nominal_10y), _num(real_10y)
    if n is None or r is None:
        return None
    return round(n - r, 3)


def _quadrant(be_rising: Optional[bool], growth_up: Optional[bool]) -> Optional[str]:
    """The classic 2×2 once a growth axis is supplied. Inflation-trend × growth-trend."""
    if be_rising is None or growth_up is None:
        return None
    if growth_up and be_rising:
        return "HEATING (reflation — growth + rising inflation)"
    if growth_up and not be_rising:
        return "GOLDILOCKS (growth + cooling inflation)"
    if (not growth_up) and be_rising:
        return "STAGFLATION (slowing + sticky/rising inflation)"
    return "SLOWING / DEFLATIONARY (slowing + cooling inflation)"


def assess(*, nominal_10y: Any = None, real_10y: Any = None, be: Any = None,
           prev_nominal_10y: Any = None, prev_real_10y: Any = None, prev_be: Any = None,
           growth_trend: Any = None, config: Optional[dict] = None) -> dict:
    """Unbundle the real yield. Supply nominal+real (preferred — derives breakeven and decomposes the
    move) or a precomputed ``be``. Priors (~4 weeks back) enable the attribution + trend; ``growth_trend``
    (signed: + improving / − slowing) optionally places the quadrant. Returns breakeven, the level read,
    the move decomposition, the trend, the metals-lens bias, and (if available) the quadrant. Graceful:
    no breakeven ⇒ ``available=False`` (dormant)."""
    cfg = _cfg(config)
    be_now = _num(be)
    if be_now is None:
        be_now = breakeven(nominal_10y, real_10y)
    available = be_now is not None

    # ---- level read --------------------------------------------------------
    be_hot, be_cold = float(cfg["be_hot"]), float(cfg["be_cold"])
    level_read, bias = "breakeven n/a", "neutral"
    if available:
        if be_now >= be_hot:
            level_read, bias = "Inflation expectations elevated (debasement tailwind)", "risk_on"
        elif be_now <= be_cold:
            level_read, bias = "Disinflation — expectations soft (headwind / deflationary watch)", "risk_off"
        else:
            level_read, bias = "Inflation expectations anchored", "neutral"

    # ---- decomposition of the latest real-yield move -----------------------
    move_min = float(cfg["move_min"])
    be_prev = _num(prev_be)
    if be_prev is None:
        be_prev = breakeven(prev_nominal_10y, prev_real_10y)
    d_nom = (_num(nominal_10y) - _num(prev_nominal_10y)) if (
        _num(nominal_10y) is not None and _num(prev_nominal_10y) is not None) else None
    d_be = (be_now - be_prev) if (be_now is not None and be_prev is not None) else None
    d_real = (d_nom - d_be) if (d_nom is not None and d_be is not None) else None

    driver, decomp_read = None, None
    if d_real is not None:
        ry_dir = "rose" if d_real > move_min else ("fell" if d_real < -move_min else "was flat")
        # which leg dominated the real-yield move?
        if abs(d_nom) >= abs(d_be):
            driver = "NOMINAL-LED"
            leg = f"driven by nominals ({d_nom:+.2f}%)"
            tag = ("classic gold headwind (tighter policy / term premium)" if d_real > move_min
                   else ("policy easing — supportive" if d_real < -move_min else "balanced"))
        else:
            driver = "BREAKEVEN-LED"
            leg = f"driven by inflation expectations ({d_be:+.2f}%)"
            if d_real > move_min:
                tag = "real yield UP on FALLING breakevens — deflationary, broad risk-off"
            elif d_real < -move_min:
                tag = "real yield DOWN on RISING breakevens — the debasement tailwind"
            else:
                tag = "balanced"
        decomp_read = f"Real yield {ry_dir} ({d_real:+.2f}%), {leg} — {tag}"

    # ---- inflation trend (momentum of expectations) ------------------------
    be_rising = None
    if d_be is not None:
        be_rising = True if d_be > move_min else (False if d_be < -move_min else None)
    trend_read = None
    if d_be is not None:
        trend_read = ("Inflation expectations accelerating" if d_be > move_min else
                      ("Inflation expectations decelerating" if d_be < -move_min else
                       "Inflation expectations stable"))

    growth_up = None
    g = _num(growth_trend)
    if g is not None:
        growth_up = g > 0
    quadrant = _quadrant(be_rising, growth_up)

    flags = []
    if available and driver == "BREAKEVEN-LED" and d_real is not None and d_real > move_min:
        flags.append({"id": "deflation_watch", "active": True, "level": "warn",
                      "text": ("REAL YIELD RISING ON COLLAPSING BREAKEVENS — deflationary regime, "
                               "broad risk-off (distinct from a nominal-led gold headwind)")})

    return {
        "available": available,
        "breakeven": be_now,
        "breakeven_pct": be_now,
        "prev_breakeven": be_prev,
        "level_read": level_read,
        "bias": bias,
        "decomposition": {"driver": driver, "d_nominal": (round(d_nom, 3) if d_nom is not None else None),
                          "d_breakeven": (round(d_be, 3) if d_be is not None else None),
                          "d_real_yield": (round(d_real, 3) if d_real is not None else None),
                          "read": decomp_read},
        "driver": driver,
        "decomp_read": decomp_read,
        "trend": trend_read,
        "be_rising": be_rising,
        "quadrant": quadrant,
        "flags": flags,
        "glossary": {k: inflation_tooltip(k) for k in INFLATION_GLOSSARY},
    }
