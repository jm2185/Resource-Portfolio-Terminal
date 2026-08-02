"""
tail_dependence.py — is the ballast still ballast on the WORST days?

``book_factor.factor_concentration`` reads average pairwise ρ — exactly the statistic that lies in a
crash, when ballast correlations converge to 1. This module adds the crash-honest read: the
**empirical lower-tail dependence** λ̂_L between the spear and each ballast name,

    λ̂_L = P( ballast return ≤ its own q-quantile  |  spear return ≤ its q-quantile )

estimated on the reproducible daily-close store (``price_history.py`` — the same ground truth the
replay harness grades against, never a live quote). Under independence λ̂_L ≈ q (~10% of the spear's
worst-decile days); a ballast printing λ̂_L ≫ ρ is a *calm-weather diversifier wearing spear-beta in
stress* — the failure mode average ρ cannot see.

Small-n honesty is structural: with ~250 cached closes and q=0.10 the conditioning set is ~25 tail
days, so every estimate carries its n and the whole read degrades to unavailable (never a guess)
below the observation floors. MEASURES, never sizes — same contract as ``book_factor``.

Pure stdlib (plain math, no numpy/pandas). Tunables under ``book_factor.tail_*`` (proposal-gated,
same block as the sibling gauges).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional

__all__ = ["DEFAULT_TAIL_CONFIG", "align_returns", "pearson", "lower_tail_dependence",
           "book_tail_read", "closes_from_history"]

DEFAULT_TAIL_CONFIG: dict[str, Any] = {
    "tail_q": 0.10,           # tail defined as each name's own worst-decile days
    "tail_min_obs": 120,      # aligned return pairs below this -> estimate withheld (n/a, not a guess)
    "tail_min_tail_n": 10,    # spear tail days below this -> estimate withheld
    "tail_crash_min": 0.50,   # λ̂_L at/above this = crash-correlated (independence predicts ~tail_q)
    "tail_gap_min": 0.25,     # λ̂_L − max(0,ρ) at/above this = stress correlation the calm ρ hides
    "tail_lookback_days": 400,  # calendar window read from the close store (~250 trading days)
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    """Read ``tail_*`` keys from the shared ``book_factor`` config block (or a flat dict)."""
    cfg = dict(DEFAULT_TAIL_CONFIG)
    block = (config or {}).get("book_factor", config or {}) if config else {}
    if isinstance(block, dict):
        for k in cfg:
            if k in block:
                cfg[k] = block[k]
    return cfg


def align_returns(closes_a, closes_b) -> tuple:
    """Simple returns on the DATE-ALIGNED intersection of two ``[(iso_date, close), ...]`` series
    (the ``PriceHistory.window`` shape). Alignment before differencing, so a listing-calendar gap
    (TSX-V vs NYSE holidays) can never pair Tuesday's spear move with Wednesday's ballast move.
    Returns ``(returns_a, returns_b)`` — equal length, possibly empty."""
    a = {d: _num(c) for d, c in (closes_a or [])}
    b = {d: _num(c) for d, c in (closes_b or [])}
    days = sorted(d for d in a if d in b and a[d] is not None and b[d] is not None
                  and a[d] > 0 and b[d] > 0)
    ra, rb = [], []
    for prev, curr in zip(days, days[1:]):
        ra.append(a[curr] / a[prev] - 1.0)
        rb.append(b[curr] / b[prev] - 1.0)
    return ra, rb


def pearson(xs: list, ys: list) -> Optional[float]:
    """Plain Pearson ρ on paired returns — the CALM comparand for the tail estimate, computed on the
    SAME aligned sample so the λ̂_L − ρ gap is apples-to-apples (never the engine's 60d matrix, which
    covers a different window)."""
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    sxx = sum((x - mx) ** 2 for x in xs[:n])
    syy = sum((y - my) ** 2 for y in ys[:n])
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs[:n], ys[:n]))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / ((sxx * syy) ** 0.5)


def _tail_threshold(returns: list, q: float) -> float:
    """The empirical q-quantile by lower rounding: the ceil(q·n)-th smallest value, so the tail set
    {r ≤ threshold} always holds at least ⌈q·n⌉ observations (never an empty conditioning set)."""
    s = sorted(returns)
    k = max(1, math.ceil(q * len(s)))
    return s[min(k, len(s)) - 1]


def lower_tail_dependence(returns_a, returns_b, *, q: float = 0.10,
                          min_obs: int = 120, min_tail_n: int = 10) -> Optional[dict]:
    """Empirical λ̂_L = P(B in its own q-tail | A in its q-tail) on paired returns (A = the
    conditioning series, the spear). Returns ``{lam, q, n_obs, n_tail, n_joint}`` — or ``None``
    when the sample is too thin to say anything honest (below ``min_obs`` pairs or ``min_tail_n``
    conditioning days). Bounded in [0, 1] by construction."""
    xs = [r for r in (returns_a or []) if _num(r) is not None]
    ys = [r for r in (returns_b or []) if _num(r) is not None]
    n = min(len(xs), len(ys))
    if n < max(2, int(min_obs)) or not (0.0 < q < 1.0):
        return None
    xs, ys = xs[:n], ys[:n]
    ta = _tail_threshold(xs, q)
    tb = _tail_threshold(ys, q)
    tail_idx = [i for i, x in enumerate(xs) if x <= ta]
    if len(tail_idx) < max(1, int(min_tail_n)):
        return None
    joint = sum(1 for i in tail_idx if ys[i] <= tb)
    return {"lam": round(joint / len(tail_idx), 3), "q": q,
            "n_obs": n, "n_tail": len(tail_idx), "n_joint": joint}


def closes_from_history(history, tickers, *, lookback_days: int = 400, today=None) -> dict:
    """``{ticker: [(iso_date, close), ...]}`` from a ``PriceHistory`` store over the lookback
    window — the one I/O-adjacent helper, so the engine wiring stays three lines and everything
    above stays pure. Missing tickers map to []."""
    end = today or date.today()
    start = end - timedelta(days=int(lookback_days))
    out = {}
    for t in (tickers or []):
        try:
            out[str(t)] = history.window(t, start, end)
        except Exception:
            out[str(t)] = []
    return out


def book_tail_read(closes_by_ticker: Optional[dict], tickers, *, spear: str = "AGA.V",
                   config: Optional[dict] = None) -> dict:
    """The book-level crash read: each non-spear name's λ̂_L to the spear beside its calm ρ on the
    same aligned sample, with two flag classes —

      * ``crash_correlated``   λ̂_L ≥ tail_crash_min: on the spear's worst-decile days this name is
        in its own worst decile too — it is NOT ballast when it matters;
      * ``stress_gap``         λ̂_L − max(0, ρ) ≥ tail_gap_min: a diversifier in calm wearing
        spear-beta in stress — the exact failure mode average ρ hides.

    Degrades to ``available: False`` (with the reason in ``read``) rather than ever guessing."""
    cfg = _cfg(config)
    closes = closes_by_ticker or {}
    tks = [str(t).strip() for t in (tickers or []) if str(t or "").strip()]
    spear_closes = closes.get(spear) or []
    q = float(cfg["tail_q"])
    min_obs, min_tail = int(cfg["tail_min_obs"]), int(cfg["tail_min_tail_n"])

    per_name, flags, insufficient = {}, [], []
    for t in tks:
        if t == spear:
            continue
        ra, rb = align_returns(spear_closes, closes.get(t) or [])
        est = lower_tail_dependence(ra, rb, q=q, min_obs=min_obs, min_tail_n=min_tail)
        if est is None:
            insufficient.append({"ticker": t, "n_obs": min(len(ra), len(rb))})
            continue
        rho = pearson(ra, rb)
        gap = round(est["lam"] - max(0.0, rho), 3) if rho is not None else None
        row = {"lam": est["lam"], "rho_same_sample": (round(rho, 3) if rho is not None else None),
               "gap": gap, "n_obs": est["n_obs"], "n_tail": est["n_tail"]}
        per_name[t] = row
        if est["lam"] >= float(cfg["tail_crash_min"]):
            flags.append({"id": "crash_correlated", "ticker": t, "level": "warn", "active": True,
                          "lam": est["lam"], "n_tail": est["n_tail"],
                          "text": (f"{t} λL {est['lam']:.2f} to {spear} (n_tail {est['n_tail']}) — "
                                   f"in its own worst decile on the spear's worst days; not ballast in a crash")})
        elif gap is not None and gap >= float(cfg["tail_gap_min"]):
            flags.append({"id": "stress_gap", "ticker": t, "level": "warn", "active": True,
                          "lam": est["lam"], "gap": gap,
                          "text": (f"{t} λL {est['lam']:.2f} vs calm ρ {rho:.2f} (gap {gap:+.2f}) — "
                                   f"diversifier in calm, spear-beta in stress")})

    if per_name:
        worst = max(per_name.items(), key=lambda kv: kv[1]["lam"])
        read = (f"crash λL to {spear}: " + ", ".join(f"{t} {r['lam']:.2f}" for t, r in sorted(per_name.items()))
                + (f" — {worst[0]} co-crashes {worst[1]['lam']:.0%} of the spear's worst days"
                   if worst[1]["lam"] >= float(cfg["tail_crash_min"]) else
                   " — every ballast stays out of the joint tail" if not flags else ""))
    elif insufficient:
        need = ", ".join(f"{r['ticker']} ({r['n_obs']}d)" for r in insufficient)
        read = f"tail read n/a — need ≥{min_obs} aligned closes with the spear (have: {need})"
    else:
        read = "tail read n/a (no non-spear names with cached closes)"

    return {"available": bool(per_name), "spear": spear, "q": q, "per_name": per_name,
            "flags": flags, "insufficient": insufficient, "read": read}
