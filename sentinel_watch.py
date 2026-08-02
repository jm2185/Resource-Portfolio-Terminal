"""
SENTINEL watch registry — the UNDATED half of the tripwire layer.

The Sentinel already covers two shapes of tripwire:
  * a **dated window** — it lives in ``catalyst_calendar`` and, once marked ``hit``, becomes an
    ``event:<kind>`` a pre-commitment rule can fire on;
  * a **live engine metric** — φ/ρ/JSF/price, diffed against the frozen thesis every sweep.

Neither can hold the third shape the desk keeps writing down: **"watch this, it has no date and the
engine cannot see it."** A PPA that may or may not be signed. A secondary block that may or may not
print. A monthly DRAM contract price that is the actual clock on a supply-cycle thesis. Left in prose
these decay into a handoff document nobody sweeps; forced into the calendar they become invented
dates, which the grounded-or-silent rule forbids.

So they live here, as a declarative registry, with three disciplines carried over from the rest of
the layer:

  * **Coverage is explicit** (the ``sentinel_board`` idiom). A watch item that is *approved but
    unwired*, or *awaiting the operator's approval*, is listed as such — never silently absent, and
    never counted as if it were being watched. ``board()["coverage"]`` is the honest read.
  * **Grounded-or-silent.** An ``active`` item must name the ``source`` it is read from. A watch with
    no source is not a watch, it is an intention — it fails validation.
  * **Approval is state, not prose.** A feed whose standing-up costs real resource (a new data
    source, an API budget) sits at ``pending_approval`` until the operator says yes. The registry
    tracks that gate rather than assuming it.

An item optionally declares ``lands_as`` — the ``catalyst_calendar`` kind it becomes WHEN it fires.
That is the hand-off: the undated watch converts into a dated, ``hit``-able window, and only then
does it reach a pre-commitment rule's ``event:<kind>``. The registry itself never fires anything and
never reaches into the engine — it is a pure, sweepable record of what the desk agreed to watch.

Pure stdlib. No engine import, no network, no eval.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

DEFAULT_PATH = "data/sentinel_watch.json"

#: What kind of thing is being watched — a book/eval NAME, or a cross-name THEME (a complex, a
#: cycle, a macro linkage) that no single ticker owns.
SUBJECT_KINDS: frozenset = frozenset({"name", "theme"})

#: Lifecycle of a watch item. ``pending_approval`` is the load-bearing one: it is how a proposed
#: feed is recorded WITHOUT being counted as covered.
STATUSES: frozenset = frozenset({"active", "pending_approval", "retired"})

#: How often the item wants a human/agent look. ``event`` items are not on a clock at all — they are
#: watched continuously and fire when the world moves, so ``due()`` never nags about them.
CADENCES: frozenset = frozenset({"event", "daily", "weekly", "monthly", "quarterly"})

#: Review interval per cadence, in days. ``event`` is absent by design (never falls due).
_CADENCE_DAYS: dict = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 91}


def _parse_date(x: Any) -> Optional[datetime]:
    """Parse ``YYYY-MM-DD`` (or a full ISO stamp) to an aware UTC datetime; None if unparseable."""
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    s = str(x or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _now_dt(now: Any = None) -> datetime:
    return _parse_date(now) or datetime.now(timezone.utc)


# --------------------------------------------------------------------------- shape + validation
def new_watch(watch_id: str, subject: str, label: str, *, signal: str = "", why: str = "",
              subject_kind: str = "name", cadence: str = "event", source: str = "",
              status: str = "active", feeds: Optional[list] = None, lands_as: Optional[str] = None,
              added: str = "", last_review: str = "", note: str = "") -> dict:
    """Build a well-formed watch item (shape only — ``validate`` is the gate)."""
    return {
        "id": str(watch_id or "").strip(),
        "subject": str(subject or "").strip(),
        "subject_kind": str(subject_kind or "name").strip().lower(),
        "label": str(label or "").strip(),
        "signal": str(signal or "").strip(),
        "why": str(why or "").strip(),
        "cadence": str(cadence or "event").strip().lower(),
        "source": str(source or "").strip(),
        "status": str(status or "active").strip().lower(),
        "feeds": [str(f) for f in (feeds or [])],
        "lands_as": (str(lands_as).strip() or None) if lands_as else None,
        "added": str(added or "").strip(),
        "last_review": str(last_review or added or "").strip(),
        "note": str(note or "").strip(),
    }


def validate(item: Any) -> tuple:
    """Validate one watch item. Returns ``(ok: bool, errors: list[str])``.

    The grounded-or-silent gate lives here: an ``active`` item MUST name a ``source``. A
    ``pending_approval`` item need not (naming the source it *would* use is exactly what is being
    approved), so the registry can hold an honest proposal without pretending it is wired."""
    errors: list = []
    if not isinstance(item, dict):
        return False, ["watch item must be an object"]
    if not item.get("id"):
        errors.append("watch.id is required")
    if not item.get("subject"):
        errors.append(f"watch {item.get('id', '?')}: subject is required")
    if not item.get("label"):
        errors.append(f"watch {item.get('id', '?')}: label is required")
    sk = str(item.get("subject_kind") or "").lower()
    if sk not in SUBJECT_KINDS:
        errors.append(f"watch {item.get('id', '?')}: subject_kind {sk!r} must be one of "
                      f"{sorted(SUBJECT_KINDS)}")
    st = str(item.get("status") or "").lower()
    if st not in STATUSES:
        errors.append(f"watch {item.get('id', '?')}: status {st!r} must be one of {sorted(STATUSES)}")
    cad = str(item.get("cadence") or "").lower()
    if cad not in CADENCES:
        errors.append(f"watch {item.get('id', '?')}: cadence {cad!r} must be one of {sorted(CADENCES)}")
    if st == "active" and not str(item.get("source") or "").strip():
        errors.append(f"watch {item.get('id', '?')}: an ACTIVE watch needs a source "
                      f"(grounded-or-silent) — or set status='pending_approval'")
    la = item.get("lands_as")
    if la:
        try:
            import catalyst_calendar as cc
            if str(la) not in cc.KINDS:
                errors.append(f"watch {item.get('id', '?')}: lands_as {la!r} is not a calendar kind "
                              f"({sorted(cc.KINDS)})")
        except ImportError:                                  # registry stays usable standalone
            pass
    return (len(errors) == 0), errors


def validate_registry(items: Any) -> tuple:
    """Validate a whole registry (each item, plus id-uniqueness). ``(ok, errors)``."""
    errors: list = []
    if not isinstance(items, list):
        return False, ["registry must be a list of watch items"]
    seen: set = set()
    for it in items:
        ok, errs = validate(it)
        errors.extend(errs)
        if ok:
            wid = it.get("id")
            if wid in seen:
                errors.append(f"duplicate watch id {wid!r}")
            seen.add(wid)
    return (len(errors) == 0), errors


# --------------------------------------------------------------------------- store
def load(path: str = DEFAULT_PATH) -> list:
    """Load the registry. NEVER raises — a missing or corrupt file yields ``[]`` so every consumer
    degrades to a clean, visible "nothing is being watched" rather than a crash."""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            env = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    items = env.get("watches", []) if isinstance(env, dict) else env
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def save(items: list, path: str = DEFAULT_PATH, *, doc: str = "") -> int:
    """Write the registry (validated first — a bad item never reaches disk). Returns the count."""
    ok, errors = validate_registry(items)
    if not ok:
        raise ValueError("invalid watch registry: " + "; ".join(errors))
    env = {
        "_doc": doc or ("SENTINEL watch registry — undated/ongoing tripwires that have no calendar "
                        "window and no engine metric. See sentinel_watch.py."),
        "watches": items,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(env, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)                                    # atomic — never a half-written registry
    return len(items)


def upsert(items: list, item: dict) -> tuple:
    """Merge ``item`` into ``items`` by id (replace in place, else append). Returns
    ``(items, added: bool)`` — the caller decides whether that counts as a change."""
    out = list(items)
    for i, existing in enumerate(out):
        if existing.get("id") == item.get("id"):
            out[i] = item
            return out, False
    out.append(item)
    return out, True


# --------------------------------------------------------------------------- views
def due(items: list, *, now: Any = None) -> list:
    """Cadence-driven items whose next look has fallen due (``last_review + interval <= now``).

    ``event``-cadence and non-``active`` items are never due: an event watch has no clock, and a
    pending/retired one is not being watched at all. An active clocked item with no ``last_review``
    IS due — it has never been looked at, which is precisely the thing worth surfacing."""
    ref = _now_dt(now)
    out = []
    for it in items:
        if str(it.get("status") or "").lower() != "active":
            continue
        days = _CADENCE_DAYS.get(str(it.get("cadence") or "").lower())
        if days is None:                                     # event-driven: no clock to fall behind
            continue
        last = _parse_date(it.get("last_review"))
        if last is None or (last + timedelta(days=days)) <= ref:
            out.append({**it, "overdue_days": (None if last is None
                                               else max(0, (ref - (last + timedelta(days=days))).days))})
    return out


def board(items: list, *, now: Any = None, subject: Optional[str] = None) -> dict:
    """The consolidated watch surface: items grouped by subject, plus an explicit coverage read.

    ``coverage`` answers the only question that matters when reading a monitor board — *how much of
    what we said we would watch are we actually watching?* — and names the gap two ways: ``pending``
    (awaiting the operator's approval) and ``unsourced_active`` (claims to be active with no source,
    which validation rejects on write but which a hand-edited file could still carry)."""
    rows = [i for i in items if not subject
            or str(i.get("subject", "")).upper() == str(subject).upper()]
    by_subject: dict = {}
    for it in rows:
        by_subject.setdefault(it.get("subject") or "_unassigned", []).append(it)

    counts: dict = {s: 0 for s in sorted(STATUSES)}
    for it in rows:
        st = str(it.get("status") or "").lower()
        counts[st] = counts.get(st, 0) + 1
    watched = counts.get("active", 0)
    considered = watched + counts.get("pending_approval", 0)
    pending = [i for i in rows if str(i.get("status") or "").lower() == "pending_approval"]
    return {
        "as_of": _now_dt(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(rows),
        "by_subject": by_subject,
        "by_status": counts,
        "due": due(rows, now=now),
        "coverage": {
            "active": watched,
            "pending_approval": len(pending),
            "pct_watched": (round(watched / considered, 3) if considered else None),
            "pending": [{"id": i.get("id"), "subject": i.get("subject"), "label": i.get("label"),
                         "source": i.get("source")} for i in pending],
            "unsourced_active": [i.get("id") for i in rows
                                 if str(i.get("status") or "").lower() == "active"
                                 and not str(i.get("source") or "").strip()],
        },
    }


def summary_line(bd: dict) -> str:
    """A compact one-line read of the board, for a memory entry or the cockpit strip."""
    cov = bd.get("coverage") or {}
    parts = [f"WATCH {bd.get('total', 0)} item(s)",
             f"{cov.get('active', 0)} active"]
    if cov.get("pending_approval"):
        parts.append(f"{cov['pending_approval']} pending approval")
    n_due = len(bd.get("due") or [])
    if n_due:
        parts.append(f"{n_due} due for review")
    return " · ".join(parts)
