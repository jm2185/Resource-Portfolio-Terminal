"""
The discovery bench — a depth-tiered view of every name in the funnel that ISN'T a holding, so the
watchlist tells you at a glance how far a name has been vetted and how much data backs it:

  ◇ RATED      — ◇EVAL names: ingested, sourced, engine-rated (T/Q/V, floor, asymmetry), NOT held.
  ⊙ GRADUATED  — cleared the disconfirmation gauntlet (verifier + anti-scout + forensic), not yet promoted.
  · MONITORED  — scout / screen candidates on the bench (screen inputs + data-gaps + base-rate anchor).
  ✗ PARKED     — screened & killed / dismissed (kept so they aren't re-scouted).

Pure + dependency-free: it classifies from already-assembled state (the rated baskets + the monitored
candidate list + optional graduated/parked sets) so the rail and the ⤢ expanded modal render from ONE
source and can't drift. The engine RATES; this only SORTS. A name appears once, at its furthest stage.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["TIERS", "bench_tiers", "bench_counts", "floor_display"]

#: tier key → (glyph, label), in display order (furthest-vetted first).
TIERS: list[tuple[str, str, str]] = [
    ("rated", "◇", "RATED"),
    ("graduated", "⊙", "GRADUATED"),
    ("monitored", "·", "MONITORED"),
    ("parked", "✗", "PARKED"),
]


def _tk(item: Any) -> str:
    return str((item or {}).get("ticker") or "").strip().upper() if isinstance(item, dict) else ""


def bench_tiers(eval_baskets: Optional[list] = None, monitored: Optional[list] = None, *,
                graduated: Optional[list] = None, parked: Optional[list] = None) -> list[dict]:
    """Group bench names into the funnel tiers, highest-vetted first, deduped across tiers (a name
    counts once, at its FURTHEST stage). ``eval_baskets`` are rated baskets — only those flagged
    ``eval_only`` are taken (a real holding is never bench). Returns an ordered list of NON-empty
    tier dicts: ``{"key", "glyph", "label", "items": [...]}`` (original item dicts preserved)."""
    buckets: dict[str, list] = {k: [] for k, _, _ in TIERS}
    seen: set[str] = set()

    for b in (eval_baskets or []):
        if isinstance(b, dict) and b.get("eval_only"):
            tk = _tk(b)
            if tk and tk not in seen:
                seen.add(tk)
                buckets["rated"].append(b)
    for src, key in ((graduated, "graduated"), (monitored, "monitored"), (parked, "parked")):
        for c in (src or []):
            tk = _tk(c)
            if tk and tk not in seen:
                seen.add(tk)
                buckets[key].append(c)

    return [{"key": k, "glyph": g, "label": lbl, "items": buckets[k]}
            for (k, g, lbl) in TIERS if buckets[k]]


def bench_counts(tiers: list[dict]) -> dict:
    """Per-tier counts + total — the one-glance summary (and a testable contract for the render)."""
    per = {t["key"]: len(t["items"]) for t in (tiers or [])}
    return {"per_tier": per, "total": sum(per.values())}


def floor_display(basket: Any) -> str:
    """Honest floor readout for a rated bench/eval name: a real number when the floor was computed from
    asset-backing inputs, or ``"pending"`` when it's missing or rests on a degraded book/proxy floor —
    never present a placeholder as if it were a real margin of safety (the OGN.V $0.50 lesson)."""
    b = basket if isinstance(basket, dict) else {}
    if b.get("floor_degraded"):
        return "pending"
    f = b.get("floor")
    if f is None and isinstance(b.get("ladder"), dict):    # live baskets carry the floor in the ladder
        f = b["ladder"].get("floor")
    try:
        return f"{float(f):.2f}"
    except (TypeError, ValueError):
        return "pending"
