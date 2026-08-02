"""
conclusion_decay.py — verdicts expire when their assumptions die, not on a timer (F3b).

Every Council verdict and pinned insight rests on load-bearing assumptions that were true at write
time; Living Memory keeps the conclusion but nothing re-checks the premises. This module makes the
check mechanical: a verdict written with STRUCTURED claims —

    memory_write(..., meta={"assumptions": [
        {"claim": "financing window > 12mo", "metric": "runway_months", "op": ">", "value": 12},
        {"claim": "still above the stressed floor", "metric": "phi", "op": ">=", "value": 1.0},
    ]})

— can be swept against live engine facts: a **dead** claim flags the whole entry **decayed**. The
sweep MEASURES; superseding the decayed entry stays with the caller (LivingMemory.supersede — the
audit trail is the track record, never edited in place). Free-text assumptions that can't be
structured stay with the dial-gated model pass; this layer is the crystallized, deterministic part.

Metric resolution (``facts`` = ``facts_from_state``'s shape, ``{"book": {...}, "<TICKER>": {...}}``):
the entry's own ticker facts first, then the book block, then a dotted path from the root — so a
name-level claim ("runway_months") and a book-level claim ("mri") both write naturally. A metric
the engine can't currently answer is **unknown**, never dead (grounded-or-silent: absence of
evidence doesn't kill a thesis; it just can't confirm it).

Pure stdlib, plain data in and out.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["evaluate_claim", "facts_from_state", "sweep"]

_OPS = {
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _resolve(metric: str, facts: dict, ticker: Optional[str]) -> Any:
    """Ticker block → book block → dotted path from the root; None when nowhere answers."""
    m = str(metric or "").strip()
    if not m:
        return None
    for scope in ((facts.get(ticker) if ticker else None), facts.get("book")):
        if isinstance(scope, dict) and m in scope:
            return scope[m]
    node: Any = facts
    for part in m.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def evaluate_claim(claim: dict, facts: dict, *, ticker: Optional[str] = None) -> dict:
    """One structured claim against live facts → ``{status: holds|dead|unknown, observed, claim}``.
    Numeric comparisons compare as floats; ==/!= fall back to string equality for labels (e.g.
    ``posture == 'defensive'``). A malformed claim or an unanswerable metric is unknown — the
    sweep never kills on a technicality."""
    c = claim if isinstance(claim, dict) else {}
    op = _OPS.get(str(c.get("op") or "").strip())
    observed = _resolve(c.get("metric"), facts or {}, ticker or c.get("ticker"))
    out = {"claim": c.get("claim") or c.get("metric"), "metric": c.get("metric"),
           "op": c.get("op"), "value": c.get("value"), "observed": observed}
    if op is None or observed is None or c.get("value") is None:
        out["status"] = "unknown"
        return out
    a, b = _num(observed), _num(c.get("value"))
    if a is not None and b is not None:
        ok = op(a, b)
    elif str(c.get("op")).strip() in ("==", "!="):
        ok = op(str(observed).strip().lower(), str(c.get("value")).strip().lower())
    else:
        out["status"] = "unknown"                       # ordered op on non-numeric data
        return out
    out["status"] = "holds" if ok else "dead"
    return out


def facts_from_state(state: Optional[dict]) -> dict:
    """Flatten the engine terminal_state into the sweep's fact table: a ``book`` block (mri,
    posture, cap) + one block per conviction basket (price, floor/base/bull, rho, phi, upside_pct,
    directive, gate_applied, gate_cap, runway_months, dilution_velocity). Only fields the engine
    actually serves — nothing derived, nothing guessed."""
    st = state or {}
    posture = st.get("posture") or {}
    facts: dict = {"book": {"mri": st.get("mri"), "posture": posture.get("code"),
                            "posture_cap": posture.get("cap")}}
    for b in ((st.get("conviction_mode") or {}).get("baskets") or []):
        tk = b.get("ticker") if isinstance(b, dict) else None
        if not tk:
            continue
        ladder = b.get("ladder") or {}
        pillars = (b.get("pillars") or {}).get("V") or {}
        gate = b.get("gate") or {}
        facts[tk] = {
            "price": ladder.get("price"), "floor": ladder.get("floor"),
            "base": ladder.get("base"), "bull": ladder.get("bull"),
            "rho": pillars.get("rho"), "phi": pillars.get("floor_coverage"),
            "upside_pct": pillars.get("upside_pct"),
            "directive": b.get("directive"),
            "gate_applied": gate.get("applied"), "gate_cap": gate.get("cap"),
            "runway_months": b.get("runway_months"),
            "dilution_velocity": b.get("dilution_velocity"),
        }
    return facts


def sweep(entries, facts: dict) -> dict:
    """Every entry carrying ``meta.assumptions`` re-checked against live facts. An entry is
    **decayed** when ≥1 structured claim is dead (the dead claims listed); otherwise it *holds*
    (all answerable claims hold) or is *unchecked* (nothing answerable). Returns findings only —
    the caller supersedes/flags; this layer never mutates memory."""
    decayed, holding, unchecked = [], [], []
    for e in (entries or []):
        if not isinstance(e, dict):
            continue
        claims = ((e.get("meta") or {}).get("assumptions")) or []
        if not isinstance(claims, list) or not claims:
            continue
        results = [evaluate_claim(c, facts, ticker=e.get("ticker")) for c in claims]
        dead = [r for r in results if r["status"] == "dead"]
        answered = [r for r in results if r["status"] != "unknown"]
        row = {"entry_id": e.get("id"), "ticker": e.get("ticker"), "type": e.get("type"),
               "text": (e.get("text") or "")[:120], "results": results}
        if dead:
            row["dead"] = dead
            decayed.append(row)
        elif answered:
            holding.append(row)
        else:
            unchecked.append(row)
    read = (f"{len(decayed)} conclusion(s) DECAYED — a load-bearing assumption died"
            if decayed else
            f"all checked conclusions hold ({len(holding)} holding, {len(unchecked)} unanswerable)"
            if (holding or unchecked) else "nothing carries structured assumptions yet")
    return {"decayed": decayed, "holding": holding, "unchecked": unchecked,
            "n_swept": len(decayed) + len(holding) + len(unchecked), "read": read}
