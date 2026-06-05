"""
Per-commodity macro regime lean ∈ [-1,1] — the COMMODITY-specific tailwind component that
asymmetry_rating._pillar_macro_tailwind blends in (so a gold royalty and a uranium royalty
score different tailwinds while sharing the royalty archetype lean).

Each metal has its OWN drivers:
  * gold      — falling real yields + a weak dollar (a monetary/duration asset).
  * silver    — gold's drivers PLUS its own (cheap vs gold via GSR, risk-on/industrial beta).
  * uranium   — its OWN supply/demand cycle (price momentum), decoupled from precious metals.
  * diversified — a blend (gold + silver), for holdcos with no single metal.

Pure + dependency-free so it is unit-testable; the engine supplies the live macro signals and the
rating layer consumes the result. Unknown commodity or missing data → None (the rating then falls
back to the archetype+MRI blend; never a fabricated tailwind).

These weightings are a reasoned FIRST CALIBRATION, not backtested — tune via tests, don't trust blindly.
"""

from __future__ import annotations


def _clamp(x, lo: float = -1.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return 0.0


def gold_regime(real_yield: float = 2.0, dxy_mom: float = 0.0, **_) -> float:
    """Falling real yields (<1% breakeven) and a weakening dollar are gold tailwinds."""
    ry = _clamp((1.0 - real_yield) / 2.0)              # +1 at RY=-1%, 0 at RY=+1%, -1 at RY=+3%
    dx = _clamp(-dxy_mom / 2.0)                         # weak-dollar momentum is positive
    return _clamp(0.60 * ry + 0.40 * dx)


def silver_regime(real_yield: float = 2.0, dxy_mom: float = 0.0, gsr: float = 80.0,
                  risk_on: float = 0.0, **_) -> float:
    """Gold's monetary drivers, plus silver-specific: cheap vs gold (high GSR) + risk-on industrial beta."""
    base = gold_regime(real_yield=real_yield, dxy_mom=dxy_mom)
    g = _clamp((gsr - 80.0) / 15.0)                     # GSR>80 => silver cheap vs gold => tailwind
    r = _clamp(risk_on)                                # risk-on lifts silver (industrial + high beta)
    return _clamp(0.50 * base + 0.30 * g + 0.20 * r)


def uranium_regime(uranium_mom: float = 0.0, **_) -> float:
    """Uranium runs on its OWN cycle — spot/equity momentum + supply-deficit narrative, not PM drivers."""
    return _clamp(uranium_mom)


def diversified_regime(**signals) -> float:
    """A holdco with no single metal — blend gold + silver."""
    return _clamp(0.5 * gold_regime(**signals) + 0.5 * silver_regime(**signals))


REGIMES = {"gold": gold_regime, "silver": silver_regime, "uranium": uranium_regime,
           "diversified": diversified_regime}


def compute(commodity, **signals):
    """Commodity regime lean ∈ [-1,1], or None for an unknown commodity (rating falls back)."""
    fn = REGIMES.get(str(commodity or "").lower())
    if fn is None:
        return None
    try:
        return round(_clamp(fn(**signals)), 3)
    except (TypeError, ValueError):
        return None
