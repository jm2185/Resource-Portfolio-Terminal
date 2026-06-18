"""
book_change.py — the CHANGE job's missing OBJECT (Agent Hub "first-principles reframe", job 2).

The reframe's thesis, in one line: *"you hit code because there's no object for a book change —
no propose, no review, no commit, no record."* This module is that object. A book change (cut /
rotate / reweight) becomes a reviewable BEFORE→AFTER **diff** carrying the deltas that actually
matter — weight freed, spear share, book-conviction drift, the min runway you're trading away —
plus the Council verdict and the Bear's preserved invalidation (pulled from Living Memory), a
mandatory pre-mortem, and a deliberate two-step commit. The dangerous act gets the calmest surface.

Discipline / scope:
  * PURE + INJECTED. The book + per-name facts arrive as a snapshot (lift them from the engine
    /state); Living Memory is injected. Nothing here touches WATCH, the cockpit ticker, the matrix,
    or the engine — it is a read-only review object the TUI CHANGE surface (or the agent, in chat)
    renders. Committing is done by the EXISTING gated path (remove_holding / cut_holding / the
    rotation gate), never here.
  * Weight math mirrors dynamic_config._redistribute (AGA-capped pro-rata) so a proposed CUT shows
    the SAME vector remove_holding would actually apply — the diff never lies about the outcome.
  * The 60% spear ceiling is an invariant: a change that would breach it is flagged, never silently
    rendered as fine.
"""
from __future__ import annotations

from typing import Optional, Sequence

SPEAR = "AGA.V"
SPEAR_CEILING = 0.60
KINDS = ("cut", "rotate", "reweight")


# ---- weight math (mirror of dynamic_config._redistribute — one behaviour, kept in lockstep) ------
def _redistribute(weights: dict, add: float) -> dict:
    """Place ``add`` across survivors pro-rata, capping AGA.V at the spear ceiling; renormalize."""
    w = {k: float(v) for k, v in weights.items()}
    def cap(k):
        return SPEAR_CEILING if k == SPEAR else 1.0
    for _ in range(12):
        if add <= 1e-9:
            break
        elig = [k for k in w if cap(k) - w[k] > 1e-9]
        if not elig:
            break
        tot = sum(w[k] for k in elig)
        moved = 0.0
        for k in elig:
            share = add * (w[k] / tot) if tot > 0 else add / len(elig)
            give = min(share, cap(k) - w[k])
            w[k] += give
            moved += give
        add -= moved
        if moved <= 1e-12:
            break
    s = sum(w.values()) or 1.0
    return {k: round(v / s, 6) for k, v in w.items()}


def _role(ticker: str, given: Optional[str] = None) -> str:
    return given or ("spear" if str(ticker).upper() == SPEAR else "ballast")


def _index(book: Sequence[dict]) -> dict:
    """{ticker: {weight, role, conviction, runway}} from a book snapshot (defaults filled)."""
    out = {}
    for b in book or []:
        tk = str(b.get("ticker") or "").upper()
        if not tk:
            continue
        out[tk] = {"weight": float(b.get("weight") or 0.0),
                   "role": _role(tk, b.get("role")),
                   "conviction": b.get("conviction"),
                   "runway": b.get("runway")}
    return out


def _spear_share(rows: dict) -> float:
    return round(sum(v["weight"] for v in rows.values() if v["role"] == "spear"), 6)


def _book_conviction(rows: dict):
    """Weight-weighted mean conviction, or None if any weighted name lacks a conviction."""
    num = den = 0.0
    for v in rows.values():
        c = v.get("conviction")
        if v["weight"] > 0 and c is None:
            return None
        if v["weight"] > 0:
            num += v["weight"] * float(c)
            den += v["weight"]
    return round(num / den, 2) if den else None


def _min_runway(rows: dict):
    vals = [float(v["runway"]) for v in rows.values() if v.get("runway") is not None and v["weight"] > 0]
    return round(min(vals), 1) if vals else None


# ---- the proposal ------------------------------------------------------------------------------
def propose_change(change: dict, book: Sequence[dict], mem=None) -> dict:
    """Build a reviewable BookChangeProposal (a plain dict) from a change spec + a book snapshot.

    change:
      {"kind": "cut",      "ticker": "URC.TO"}
      {"kind": "rotate",   "out": "URC.TO", "in": "SILV",
                           "in_facts": {"role": "spear"|"ballast", "conviction": 7.1, "runway": 9}}
      {"kind": "reweight", "weights": {"AGA.V": 0.6, "GROY": 0.4}}      # explicit target vector
    book: [{"ticker","weight","role"?,"conviction"?,"runway"?}, ...]  (current barbell + facts)
    mem:  a Living Memory handle (optional) — attaches the latest council_verdict + bear caveat.
    """
    kind = str(change.get("kind") or "").lower()
    if kind not in KINDS:
        return {"ok": False, "error": f"unknown change kind {kind!r}; expected {KINDS}"}
    cur = _index(book)
    if not cur:
        return {"ok": False, "error": "empty book snapshot"}
    warnings: list = []
    subject = None

    if kind == "cut":
        tk = str(change.get("ticker") or "").upper()
        if tk not in cur:
            return {"ok": False, "error": f"{tk} is not in the book"}
        if tk == SPEAR:
            return {"ok": False, "error": "the spear (AGA.V) is structural — it cannot be cut"}
        if len([k for k in cur if k not in (tk, SPEAR)]) < 1:
            return {"ok": False, "error": "cutting this would leave the book with no ballast"}
        subject = tk
        freed = cur[tk]["weight"]
        survivors = {k: v["weight"] for k, v in cur.items() if k != tk}
        new_w = _redistribute(survivors, freed)
        after = {k: {**cur[k], "weight": new_w.get(k, 0.0)} for k in survivors}

    elif kind == "rotate":
        out_tk = str(change.get("out") or "").upper()
        in_tk = str(change.get("in") or "").upper()
        if out_tk not in cur:
            return {"ok": False, "error": f"{out_tk} is not in the book"}
        if not in_tk:
            return {"ok": False, "error": "rotate needs an incoming ticker ('in')"}
        if out_tk == SPEAR:
            return {"ok": False, "error": "the spear (AGA.V) is structural — rotate it only via a spear-slot swap"}
        subject = in_tk
        freed = cur[out_tk]["weight"]
        facts = change.get("in_facts") or {}
        after = {k: dict(v) for k, v in cur.items() if k != out_tk}
        after[in_tk] = {"weight": round(freed, 6), "role": _role(in_tk, facts.get("role")),
                        "conviction": facts.get("conviction"), "runway": facts.get("runway")}

    else:  # reweight
        weights = change.get("weights") or {}
        try:
            tgt = {str(k).upper(): float(v) for k, v in weights.items()}
        except (TypeError, ValueError):
            return {"ok": False, "error": "reweight weights must be {ticker: number}"}
        if not tgt:
            return {"ok": False, "error": "reweight needs a target weights vector"}
        s = sum(tgt.values())
        if abs(s - 1.0) > 1e-3:
            return {"ok": False, "error": f"reweight must sum to 1.0 (got {s:.4f})"}
        subject = "book"
        after = {}
        for tk, w in tgt.items():
            base = cur.get(tk, {})
            after[tk] = {"weight": round(w, 6), "role": _role(tk, base.get("role")),
                         "conviction": base.get("conviction"), "runway": base.get("runway")}
        freed = round(sum(max(0.0, cur[k]["weight"] - after.get(k, {}).get("weight", 0.0))
                          for k in cur), 6)

    # ---- invariant: the spear ceiling ----
    aga_after = after.get(SPEAR, {}).get("weight", 0.0)
    if aga_after > SPEAR_CEILING + 1e-9:
        warnings.append(f"spear AGA.V {aga_after:.0%} breaches the {SPEAR_CEILING:.0%} ceiling (invariant)")
    spear_after = _spear_share(after)
    if spear_after > SPEAR_CEILING + 1e-9:
        warnings.append(f"total spear share {spear_after:.0%} exceeds the {SPEAR_CEILING:.0%} ceiling")

    def _rows(rows):
        return [{"ticker": k, "role": v["role"], "weight": round(v["weight"], 6)}
                for k, v in rows.items()]

    conv_b, conv_a = _book_conviction(cur), _book_conviction(after)
    rw_b, rw_a = _min_runway(cur), _min_runway(after)
    deltas = {
        "weight_freed": round(freed, 6),
        "spear_share": {"before": _spear_share(cur), "after": spear_after},
        "names": {"before": len(cur), "after": len(after)},
        "book_conviction": ({"before": conv_b, "after": conv_a,
                             "delta": round(conv_a - conv_b, 2)} if (conv_b is not None and conv_a is not None) else None),
        "min_runway": ({"before": rw_b, "after": rw_a,
                        "delta": round(rw_a - rw_b, 1)} if (rw_b is not None and rw_a is not None) else None),
    }

    council = bear = None
    if mem is not None and subject and subject != "book":
        try:
            cv = mem.latest(ticker=subject, type="council_verdict")
            council = {"id": cv.get("id"), "text": cv.get("text")} if cv else None
        except Exception:
            council = None
        try:
            bh = (mem.query(ticker=subject, tag="bear", limit=1) or [None])[0]
            bear = {"id": bh.get("id"), "text": bh.get("text")} if bh else None
        except Exception:
            bear = None

    return {
        "ok": True,
        "kind": kind.upper(),
        "subject": subject,
        "before": _rows(cur),
        "after": _rows(after),
        "deltas": deltas,
        "council": council,
        "bear": bear,                 # the invalidation travels WITH the proposal, never buried
        "premortem_required": True,   # "it's 90 days out and this was wrong — why?" before commit
        "commit": {"steps": 2, "writes_memory": True,
                   "applied_by": {"cut": "remove_holding/cut_holding", "rotate": "/rotate + remove_holding",
                                  "reweight": "set_barbell_weights"}[kind]},
        "warnings": warnings,
    }


def summarize(p: dict) -> str:
    """A terse, signal-first one-screen review (for the agent to show in chat; the TUI renders richer)."""
    if not p.get("ok"):
        return f"change refused — {p.get('error')}"
    d = p["deltas"]
    before = " · ".join(f"{r['ticker']} {r['weight']*100:.0f}%" for r in p["before"])
    after = " · ".join(f"{r['ticker']} {r['weight']*100:.0f}%" for r in p["after"])
    lines = [f"{p['kind']} · {p['subject']}",
             f"  before: {before}",
             f"  after:  {after}",
             f"  weight freed {d['weight_freed']*100:.0f}% · spear {d['spear_share']['before']*100:.0f}→{d['spear_share']['after']*100:.0f}%"]
    if d.get("book_conviction"):
        bc = d["book_conviction"]; lines.append(f"  book conviction {bc['before']}→{bc['after']} ({bc['delta']:+})")
    if d.get("min_runway"):
        mr = d["min_runway"]; lines.append(f"  min runway {mr['before']}→{mr['after']}mo ({mr['delta']:+}mo)")
    if p.get("council"):
        lines.append(f"  Council: {p['council']['text']}")
    if p.get("bear"):
        lines.append(f"  Bear ★ (invalidation preserved): {p['bear']['text']}")
    if p.get("warnings"):
        lines.append("  ⚑ " + "; ".join(p["warnings"]))
    lines.append("  ⚑ pre-mortem required before commit · commit is two-step · writes a labelled Memory entry")
    return "\n".join(lines)
