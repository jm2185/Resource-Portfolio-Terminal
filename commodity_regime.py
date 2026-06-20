"""
Per-commodity macro regime lean ∈ [-1,1] — the COMMODITY-specific tailwind component that
asymmetry_rating._pillar_macro_tailwind blends in (so a gold royalty and a uranium royalty
score different tailwinds while sharing the royalty archetype lean).

FORWARD-STRUCTURAL by definition (action plan P1.1). The tailwind measures the **forward
structural / secular outlook over the multi-year thesis horizon**, NOT recent price action,
momentum, or current-tape sentiment. So `compute()` is built ONLY from structural LEVELS:

  * gold      — the real-yield LEVEL (a monetary/duration asset: falling real yields = debasement
                tailwind). Structural, not the 10-day dollar tape.
  * silver    — gold's monetary driver PLUS its own structural relative-value read (the Gold/Silver
                ratio LEVEL, U-shaped: leadership at low GSR, contrarian-cheap at high GSR).
  * uranium   — its OWN supply/demand STRUCTURE (the term-market / supply-deficit read, fed by the
                SENTINEL uranium term monitor), NOT spot price momentum. Neutral until that monitor
                supplies a structural read — never a momentum stand-in.
  * diversified — a blend (gold + silver), for holdcos with no single metal.

Backward-looking near-term tape (10-day DXY momentum, uranium price momentum, risk-on positioning /
sentiment) is DELIBERATELY excluded from the tailwind. If a near-term momentum read is wanted at all
it lives in `compute_momentum()` as a SEPARATE, LABELED factor and NEVER enters the structural
tailwind / the T pillar. (This is the P1.1 fix: a name with strong secular drivers sitting in a
near-term-weak tape must score HIGH tailwind — e.g. GROY's gold tailwind rises off the real-yield
level instead of being dragged down by recent dollar momentum.)

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


# --------------------------------------------------------------------------- #
#  STRUCTURAL (forward) tailwind — the multi-year secular outlook. LEVELS only.
# --------------------------------------------------------------------------- #
def gold_regime(real_yield: float = 2.0, **_) -> float:
    """Gold's structural tailwind is the real-yield LEVEL: a falling/negative real yield is the
    monetary-debasement tailwind for a duration/monetary asset. Forward-structural — it does NOT
    read the recent dollar tape (that 10-day momentum moved to compute_momentum)."""
    return _clamp((1.0 - real_yield) / 2.0)            # +1 at RY=-1%, 0 at RY=+1%, -1 at RY=+3%


def silver_regime(real_yield: float = 2.0, gsr: float = 80.0, **_) -> float:
    """Silver = gold's structural monetary driver PLUS its own structural relative-value read, the
    Gold/Silver ratio LEVEL.

    GSR is read the way the rest of the engine reads it (the GSR signal at engine.py + its metric
    definition): a U-shape, NOT one-directional mean-reversion. LOW GSR (< 75) = silver LEADERSHIP /
    outperformance = tailwind; very HIGH GSR (> 85) = extreme undervaluation = a (weaker)
    contrarian-accumulation tailwind; the 75–85 band is balanced (≈0).

    The structural read deliberately drops the risk-on positioning term (current-tape sentiment) —
    that near-term industrial/beta lift now lives in compute_momentum(), not in the tailwind.
    """
    base = gold_regime(real_yield=real_yield)
    lead = max(0.0, (75.0 - gsr) / 15.0)               # silver leadership: GSR < 75 (engine risk-on band)
    contra = max(0.0, (gsr - 85.0) / 15.0)             # contrarian-cheap: GSR > 85 (engine accumulation band)
    g = _clamp(lead + contra)                          # both extremes bullish; the 75–85 band is balanced
    return _clamp(0.65 * base + 0.35 * g)


def uranium_regime(uranium_term: float = 0.0, **_) -> float:
    """Uranium's structural tailwind is its OWN supply/demand STRUCTURE — the term-market /
    supply-deficit read (the SENTINEL uranium term monitor), ∈ [-1,1], NOT spot price momentum.

    Until that monitor supplies a structural `uranium_term`, the structural lean is NEUTRAL (0.0)
    rather than a momentum stand-in: a forward tailwind is never fabricated from backward tape. The
    1-month price momentum that used to drive this is now compute_momentum()'s, kept out of T.
    """
    return _clamp(uranium_term)


def diversified_regime(**signals) -> float:
    """A holdco with no single metal — blend gold + silver (structural)."""
    return _clamp(0.5 * gold_regime(**signals) + 0.5 * silver_regime(**signals))


REGIMES = {"gold": gold_regime, "silver": silver_regime, "uranium": uranium_regime,
           "diversified": diversified_regime}


def compute(commodity, **signals):
    """Structural (forward) commodity regime lean ∈ [-1,1], or None for an unknown commodity (the
    rating falls back to the archetype+MRI blend). Built from LEVELS only — momentum/tape inputs in
    ``signals`` (dxy_mom, uranium_mom, risk_on) are accepted for backward-compatible call sites but
    DELIBERATELY ignored here; they belong to ``compute_momentum`` (action plan P1.1)."""
    fn = REGIMES.get(str(commodity or "").lower())
    if fn is None:
        return None
    try:
        return round(_clamp(fn(**signals)), 3)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
#  MOMENTUM (backward, near-term) — a SEPARATE, LABELED factor. NEVER part of
#  the structural tailwind / the T pillar; surfaced for display/context only.
# --------------------------------------------------------------------------- #
def _gold_momentum(dxy_mom: float = 0.0, **_) -> float:
    """Near-term gold momentum: weak-dollar 10-day momentum is a near-term tailwind."""
    return _clamp(-dxy_mom / 2.0)


def _silver_momentum(dxy_mom: float = 0.0, risk_on: float = 0.0, **_) -> float:
    """Near-term silver momentum: weak-dollar momentum + the risk-on industrial/beta tape lift."""
    return _clamp(0.6 * _clamp(-dxy_mom / 2.0) + 0.4 * _clamp(risk_on))


def _uranium_momentum(uranium_mom: float = 0.0, **_) -> float:
    """Near-term uranium momentum: spot/equity 1-month price momentum (its own cycle's tape)."""
    return _clamp(uranium_mom)


def _diversified_momentum(**signals) -> float:
    return _clamp(0.5 * _gold_momentum(**signals) + 0.5 * _silver_momentum(**signals))


MOMENTUM = {"gold": _gold_momentum, "silver": _silver_momentum,
            "uranium": _uranium_momentum, "diversified": _diversified_momentum}


def compute_momentum(commodity, **signals):
    """Near-term MOMENTUM read ∈ [-1,1] for a commodity — a SEPARATE, LABELED factor that is NOT
    part of the structural tailwind (action plan P1.1: momentum must never be blended into the
    forward field). Returns None for an unknown commodity. Surfaced for display/context only; the
    T pillar never consumes it."""
    fn = MOMENTUM.get(str(commodity or "").lower())
    if fn is None:
        return None
    try:
        return round(_clamp(fn(**signals)), 3)
    except (TypeError, ValueError):
        return None
