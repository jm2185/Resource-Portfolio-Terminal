"""
Thesis ledger — the underwriting record's validator + the graveyard/hall-of-fame view (Forge M2).

The ``thesis`` is where the alpha the engine CAN'T see is written down: the idiosyncratic catalyst,
the macro prerequisite, an explicit forensic waiver, the narrative-invalidation line — plus two
machine-checkable spines the Sentinel reads every tick:
  * ``claims[]`` — a human assertion BOUND to an engine metric + operator + threshold (or a ``manual``
    claim only the operator/verifier can flip). Drives the thesis-integrity score (M3).
  * ``rules[]``  — pre-commitment "Ulysses contracts": ``trigger → action``. The trigger is a
    `trigger_grammar` expression; the action is what you agreed, in calm blood, to do when it fires.

This module is the substrate's *consumer*, so (unlike living_memory.py) it may import the grammar:
  * **validate at SAVE** — `validate_thesis` parses every rule trigger and type-checks every claim, so
    a malformed rule is rejected the moment it's written, with a clear error (M2 acceptance).
  * **the Ledger view** — joins each ``thesis`` (including REJECTs) to its realized ``outcome``
    records. No new store; it just widens the calibration sample (the graveyard is data too).

Pure stdlib + trigger_grammar. Fully testable against a temp LivingMemory.
"""
from __future__ import annotations

from typing import Any, Optional

import trigger_grammar as tg

STANCES: frozenset = frozenset({"APPROVE", "CONDITIONAL", "REJECT"})
CLAIM_CHECKS: frozenset = frozenset({"engine", "manual"})
CLAIM_STATUS: frozenset = frozenset({"holds", "broken", "unknown"})
#: what a fired rule may do. Only ``alert`` is auto-actable by the Sentinel; trims/exits PROPOSE.
RULE_ACTIONS: frozenset = frozenset({"trim_to", "add_to", "exit", "alert", "flag", "review"})
_COMPARATORS: frozenset = frozenset({"<", "<=", ">", ">=", "==", "!="})


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- constructors
def new_claim(text: str, *, metric: Optional[str] = None, op: Optional[str] = None,
              threshold: Any = None, check: Optional[str] = None, cid: str = "",
              status: str = "holds") -> dict:
    """Build a well-formed claim. ``check`` defaults to ``engine`` when a metric is given, else
    ``manual``. (Validation happens in ``validate_thesis``; this just shapes the dict.)"""
    if check is None:
        check = "engine" if metric else "manual"
    return {"id": cid, "text": str(text or ""), "metric": metric or None,
            "op": op or None, "threshold": threshold,
            "check": check, "status": status if status in CLAIM_STATUS else "holds"}


def new_rule(trigger: str, action: str, *, arg: Any = None, rid: str = "") -> dict:
    """Build a well-formed pre-commitment rule (unvalidated shape)."""
    return {"id": rid, "trigger": str(trigger or ""), "action": str(action or ""),
            "arg": arg, "fired": False, "acknowledged": False}


def build_thesis(ticker: str, *, archetype: str = "", stance: str = "CONDITIONAL",
                 claims: Optional[list] = None, rules: Optional[list] = None,
                 expected: Optional[dict] = None, intangibles: Optional[dict] = None,
                 linked_calendar: Optional[list] = None, source_urls: Optional[list] = None,
                 entered_at: Optional[str] = None, regime_at_entry: Optional[dict] = None,
                 **intangibles_kw) -> dict:
    """Assemble a thesis dict (the structured body that becomes a ``thesis`` entry's ``meta``).
    Auto-assigns claim ids (c1, c2, …) and rule ids (r1, r2, …) where missing. The §3.2 intangible
    fields (``idiosyncratic_catalyst``, ``macro_prerequisite``, ``forensic_waiver``,
    ``narrative_invalidation``) may be passed either in ``intangibles`` or as plain kwargs."""
    claims = list(claims or [])
    rules = list(rules or [])
    for i, c in enumerate(claims, 1):
        if not c.get("id"):
            c["id"] = f"c{i}"
    for i, r in enumerate(rules, 1):
        if not r.get("id"):
            r["id"] = f"r{i}"
    body = {
        "ticker": str(ticker).upper(), "archetype": archetype,
        "stance": str(stance).upper(), "entered_at": entered_at,
        "regime_at_entry": regime_at_entry or {},
        "claims": claims, "rules": rules,
        "expected": expected or {},
        "linked_calendar": list(linked_calendar or []),
        "source_urls": list(source_urls or []),
    }
    body.update(intangibles or {})
    body.update(intangibles_kw)
    return body


# --------------------------------------------------------------------------- validation (at SAVE)
def validate_thesis(thesis: dict) -> tuple:
    """Validate a thesis body. Returns ``(ok: bool, errors: list[str])``. Checks the stance, every
    claim's metric/op/threshold (for ``engine`` claims), and PARSES every rule trigger through the
    safe grammar (so a malformed Ulysses contract is rejected before it ever enters the record)."""
    errors: list = []
    if not isinstance(thesis, dict):
        return False, ["thesis must be an object"]
    if not thesis.get("ticker"):
        errors.append("thesis.ticker is required")
    stance = str(thesis.get("stance", "")).upper()
    if stance not in STANCES:
        errors.append(f"stance {stance!r} must be one of {sorted(STANCES)}")

    for c in thesis.get("claims", []) or []:
        cid = c.get("id", "?")
        if not c.get("text"):
            errors.append(f"claim {cid}: text is required")
        check = c.get("check") or ("engine" if c.get("metric") else "manual")
        if check not in CLAIM_CHECKS:
            errors.append(f"claim {cid}: check {check!r} must be engine|manual")
        if check == "engine":
            m = c.get("metric")
            if m not in tg.METRICS:
                errors.append(f"claim {cid}: metric {m!r} is not an engine metric "
                              f"(known: {sorted(tg.METRICS)})")
            if c.get("op") not in _COMPARATORS:
                errors.append(f"claim {cid}: op {c.get('op')!r} must be one of {sorted(_COMPARATORS)}")
            if _num(c.get("threshold")) is None:
                errors.append(f"claim {cid}: threshold must be numeric for an engine claim")

    for r in thesis.get("rules", []) or []:
        rid = r.get("id", "?")
        action = r.get("action")
        if action not in RULE_ACTIONS:
            errors.append(f"rule {rid}: action {action!r} must be one of {sorted(RULE_ACTIONS)}")
        if action in ("trim_to", "add_to"):
            a = _num(r.get("arg"))
            if a is None or not (0.0 < a <= 1.0):
                errors.append(f"rule {rid}: {action} needs a target weight arg in (0, 1]")
        trig = r.get("trigger", "")
        try:
            tg.parse(trig)
        except tg.GrammarError as e:
            errors.append(f"rule {rid}: trigger does not parse — {e}")
    return (len(errors) == 0), errors


def validate_thesis_or_raise(thesis: dict) -> dict:
    ok, errors = validate_thesis(thesis)
    if not ok:
        raise ValueError("invalid thesis: " + "; ".join(errors))
    return thesis


def thesis_summary_line(thesis: dict) -> str:
    """A compact text line for the ``thesis`` entry's ``text`` field."""
    t = thesis.get("ticker", "?")
    st = thesis.get("stance", "?")
    nc, nr = len(thesis.get("claims", []) or []), len(thesis.get("rules", []) or [])
    cat = thesis.get("idiosyncratic_catalyst") or ""
    tail = f" · {cat}" if cat else ""
    return f"THESIS {st} {t} — {nc} claim(s), {nr} rule(s){tail}"


# --------------------------------------------------------------------------- the Ledger view
class Ledger:
    """A read-only view over Living Memory: every ``thesis`` joined to its realized ``outcome``
    records. The graveyard (REJECTs) and the hall of fame (APPROVEs that paid) live side by side —
    no new store, just a join that widens the calibration sample (M7)."""

    def __init__(self, mem):
        self.mem = mem

    def _outcomes_for(self, ticker: str, since_ts: Optional[str]) -> list:
        rows = self.mem.query(ticker=ticker, type="outcome", limit=0, newest_first=True)
        if since_ts:
            rows = [o for o in rows if str(o.get("ts") or "") >= str(since_ts)]
        return rows

    def entries(self, stance: Optional[str] = None) -> list:
        """All theses (optionally filtered by stance), each joined to its post-entry outcomes."""
        out = []
        for t in self.mem.theses(stance=stance, limit=0):
            body = t.get("meta") or {}
            tk = t.get("ticker") or body.get("ticker")
            outcomes = self._outcomes_for(tk, t.get("ts")) if tk else []
            wins = sum(1 for o in outcomes if (o.get("meta") or {}).get("result") == "win")
            losses = sum(1 for o in outcomes if (o.get("meta") or {}).get("result") == "loss")
            out.append({
                "thesis_id": t.get("id"), "ticker": tk,
                "stance": str(body.get("stance", "")).upper(),
                "archetype": body.get("archetype"),
                "entered_at": t.get("ts"),
                "claims": body.get("claims", []), "rules": body.get("rules", []),
                "expected": body.get("expected", {}),
                "idiosyncratic_catalyst": body.get("idiosyncratic_catalyst"),
                "outcomes": outcomes, "wins": wins, "losses": losses,
                "resolved": bool(outcomes),
            })
        return out

    def graveyard(self) -> list:
        """The REJECTs — names you passed on. Tracking them is how you learn what you wrongly skipped."""
        return self.entries(stance="REJECT")

    def hall_of_fame(self) -> list:
        """APPROVEs that produced at least one winning outcome — the process working."""
        return [e for e in self.entries(stance="APPROVE") if e["wins"] > 0]

    def stats(self) -> dict:
        all_e = self.entries()
        by_stance: dict = {}
        for e in all_e:
            by_stance[e["stance"]] = by_stance.get(e["stance"], 0) + 1
        return {"theses": len(all_e), "by_stance": by_stance,
                "resolved": sum(1 for e in all_e if e["resolved"])}
