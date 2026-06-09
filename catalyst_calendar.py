"""
Catalyst calendar — the shared, time-aware event store every Forge component reads (Forge M1).

A catalyst is a **window, not a point**: "Q3 Nevada drill results" is `[2026-07-01, 2026-09-30]`, not
a single day. A junior re-rates *somewhere inside* that window, so the whole layer reasons over
overlap with "now → now+N days", never an exact date the issuer never actually promised.

This is the foundation milestone: the Sentinel's `no_catalyst_within_days(n)` rule term (M3), the
Council swap's catalyst-lock (M6), and the cockpit's upcoming-catalysts strip all read this one
object. It absorbs the proposed `@thesis-timer` entirely — there is no separate timer, just this
calendar plus the components that query it.

Design (mirrors `living_memory.py` deliberately — one storage idiom for the whole Forge layer):
  * **Append-only & immutable JSONL** at ``data/catalyst_calendar.jsonl``. A correction is a NEW
    entry that ``supersede``s the old one; the original survives in the file (audit trail) but is
    hidden from ``query``. Dates are facts with provenance — you never silently rewrite when one was.
  * **Grounded or silent.** Every entry carries ``source`` + ``source_url``; the macro seeder only
    generates events whose cadence is *rule-deterministic* (COT weekly, NFP first-Friday) as
    ``scheduled``, marks rule-approximate ones (CPI mid-month) ``estimated``, and **refuses to invent
    FOMC dates** (the Fed sets those — they must be written from a source).
  * **Regime-stamped.** Like Living Memory, each entry records the live regime at log time, so a
    catalyst is recallable "under a regime like today's".
  * **Pure stdlib, multi-process safe** (O_APPEND), unit-testable on its own.

The macro corner (FOMC/CPI/COT/NFP) lives here too as ``ticker=None`` entries, so one query can fold
"this name + the macro tape" for the cockpit strip.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

DEFAULT_PATH = "data/catalyst_calendar.jsonl"

#: Name-level catalyst kinds (the junior-mining lifecycle) + the macro catch-all.
KINDS: frozenset = frozenset({
    "drill_result", "assay", "pea", "pfs", "fs", "financing_window",
    "royalty_payment", "permit", "macro",
})
#: Macro sub-kinds (only meaningful when kind == "macro", ticker is None).
MACRO_KINDS: frozenset = frozenset({"fomc", "cpi", "cot_print", "nfp"})
#: How firm the date is — drives the cockpit colour and whether a rule should trust it.
CONFIDENCE: frozenset = frozenset({"scheduled", "guided", "estimated", "rumored"})
#: Lifecycle of a catalyst window.
STATUS: frozenset = frozenset({"pending", "hit", "missed", "delayed", "void"})


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _gen_id() -> str:
    return "cal_" + uuid.uuid4().hex[:12]


def _parse(ts: Any) -> Optional[datetime]:
    """Parse an ISO-ish timestamp into an aware UTC datetime. Tolerant of trailing ``Z``, a bare
    date, or an already-parsed datetime. Returns None on anything unusable (never raises)."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.fromisoformat(s) if fmt is None else datetime.strptime(str(ts)[:len(fmt)+2], fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _now_dt(now: Any = None) -> datetime:
    d = _parse(now)
    return d or datetime.now(timezone.utc)


class CatalystCalendar:
    """Append-only typed calendar over a JSONL file. Cache-first reads (mtime-invalidated)."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._cache: Optional[list] = None
        self._mtime: Optional[float] = None

    # ------------------------------------------------------------------ write
    def write(self, *, kind: str, title: str, window_start: str, window_end: Optional[str] = None,
              ticker: Optional[str] = None, macro_kind: Optional[str] = None,
              confidence: str = "estimated", source: str = "manual", source_url: str = "",
              status: str = "pending", linked_thesis: Optional[str] = None,
              regime: Optional[dict] = None, notes: str = "", as_of: Optional[str] = None) -> dict:
        """Append one catalyst window and return it (with its id). ``kind`` must be in KINDS.

        A point event (no ``window_end``) becomes a zero-width window at ``window_start`` — overlap
        logic still works. ``ticker=None`` ⇒ a macro event. The writer supplies the live ``regime``
        (this module never reaches into the engine)."""
        k = str(kind)
        if k not in KINDS:
            raise ValueError(f"unknown catalyst kind {k!r}; expected one of {sorted(KINDS)}")
        ws = _parse(window_start)
        if ws is None:
            raise ValueError(f"window_start {window_start!r} is not a parseable date")
        we = _parse(window_end) or ws
        if we < ws:
            raise ValueError("window_end is before window_start")
        conf = confidence if confidence in CONFIDENCE else "estimated"
        st = status if status in STATUS else "pending"
        mk = macro_kind if (macro_kind in MACRO_KINDS) else None
        # Grounded-or-silent (hard invariant #6): a named-ticker catalyst presented as SCHEDULED —
        # the firmest confidence, the one pre-commitment rules trust — must carry a straight-to-
        # source URL (issuer PR / SEDAR+ / EDGAR). Softer confidences (guided/estimated/rumored)
        # may enter without one but are stamped grounded=False so every reader sees the gap.
        # Macro windows are exempt: the recurring ones are rule-deterministic (COT/NFP), not sourced.
        url = str(source_url or "").strip()
        grounded = None
        if k != "macro" and ticker:
            if conf == "scheduled" and not url:
                raise ValueError(
                    f"a SCHEDULED catalyst for {ticker} needs a source_url (issuer PR / SEDAR+ / "
                    f"EDGAR) — grounded-or-silent; downgrade confidence to 'guided'/'estimated' "
                    f"if you can't source the date")
            grounded = bool(url)
        entry = {
            "id": _gen_id(),
            "ticker": (str(ticker).strip().upper() or None) if ticker else None,
            "kind": k,
            "macro_kind": mk,
            "title": str(title or "")[:200],
            "window_start": ws.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end": we.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "confidence": conf,
            "source": str(source or "manual"),
            "source_url": url[:400],
            "grounded": grounded,
            "status": st,
            "regime_at_log": dict(regime) if isinstance(regime, dict) else None,
            "linked_thesis": linked_thesis or None,
            "as_of": as_of or _now_iso(),
            "notes": str(notes or "")[:300],
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:   # O_APPEND -> multi-process safe
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
        # invalidate (never append-and-restamp): another process may have appended in the same
        # mtime window — a warm cache that misses their entry would serve an incomplete calendar.
        self._cache, self._mtime = None, None
        return entry

    def supersede(self, old_id: str, **kw) -> dict:
        """Record a correction as a NEW entry pointing back at ``old_id`` (never an in-place edit).
        Carry forward any field not overridden in ``kw`` so a one-field fix needn't restate the event."""
        old = self.get(old_id) or {}
        merged = {k: old.get(k) for k in ("kind", "title", "window_start", "window_end", "ticker",
                                          "macro_kind", "confidence", "source", "source_url",
                                          "status", "linked_thesis", "notes")}
        merged = {k: v for k, v in merged.items() if v is not None}
        merged.update(kw)
        new = self.write(**merged)
        # mark the supersession by appending a meta marker line (kept in-band, audit-visible)
        self._mark_superseded(old_id, new["id"])
        return new

    def set_status(self, entry_id: str, status: str, **kw) -> Optional[dict]:
        """Transition a catalyst's status (pending → hit/missed/delayed/void) via supersession."""
        if status not in STATUS:
            raise ValueError(f"unknown status {status!r}")
        if not self.get(entry_id):
            return None
        return self.supersede(entry_id, status=status, **kw)

    def _mark_superseded(self, old_id: str, new_id: str) -> None:
        rec = {"id": "sup_" + uuid.uuid4().hex[:8], "supersedes": old_id, "by": new_id,
               "as_of": _now_iso()}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        if self._cache is not None:
            self._cache.append(rec)

    # ------------------------------------------------------------------ read
    def all(self, *, include_markers: bool = False) -> list:
        """Every entry, file order. Cache-first; reloads only when the file changed on disk.
        Supersession markers are filtered unless ``include_markers``."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._cache, self._mtime = [], None
            return []
        if self._cache is None or self._mtime != mtime:
            out = []
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    for ln in fh:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            out.append(json.loads(ln))
                        except (ValueError, json.JSONDecodeError):
                            continue                      # tolerate a torn line, never crash
            except OSError:
                return self._cache or []
            self._cache, self._mtime = out, mtime
        if include_markers:
            return self._cache
        return [e for e in self._cache if "supersedes" not in e]

    def _superseded_ids(self) -> set:
        return {e["supersedes"] for e in self.all(include_markers=True)
                if "supersedes" in e}

    def get(self, entry_id: str) -> Optional[dict]:
        for e in self.all():
            if e.get("id") == entry_id:
                return e
        return None

    def query(self, ticker: Optional[str] = None, within_days: Optional[int] = None,
              kind: Optional[str] = None, status: Optional[str] = "pending",
              include_macro: bool = False, now: Any = None) -> list:
        """Catalyst windows overlapping ``[now, now + within_days]``, soonest-first.

        * ``ticker`` filters to that name; ``ticker=None`` returns **all** names + macro events.
        * ``include_macro=True`` folds macro (``ticker=None``) events into a *named* query — for the
          cockpit's "this name + the macro tape" strip.
        * ``within_days=None`` ⇒ no upper horizon (everything still open or upcoming).
        * ``status=None`` ⇒ any status (else the given status, default ``pending``). Superseded
          entries are always hidden (the correction is what you see).
        """
        n0 = _now_dt(now)
        horizon = n0 + timedelta(days=within_days) if within_days is not None else None
        sup = self._superseded_ids()
        want_tk = str(ticker).upper() if ticker else None
        rows = []
        for e in self.all():
            if e.get("id") in sup:
                continue
            etk = e.get("ticker")
            if want_tk is not None:
                if etk != want_tk and not (include_macro and etk is None):
                    continue
            if status is not None and e.get("status") != status:
                continue
            if kind is not None and e.get("kind") != kind:
                continue
            ws, we = _parse(e.get("window_start")), _parse(e.get("window_end"))
            if ws is None:
                continue
            we = we or ws
            # interval overlap with [n0, horizon]: not already past, and starts within the horizon
            if we < n0:
                continue
            if horizon is not None and ws > horizon:
                continue
            rows.append({**e, "_days_to_start": max(0, (ws - n0).days),
                         "_window_open": ws <= n0 <= we})
        rows.sort(key=lambda r: str(r.get("window_start") or ""))
        return rows

    def has_within(self, ticker: Optional[str], days: int, *, kinds: Optional[set] = None,
                   include_macro: bool = False, now: Any = None) -> bool:
        """True iff a pending catalyst for ``ticker`` overlaps the next ``days`` (used by the trigger
        grammar's ``catalyst_within_days`` and the swap catalyst-lock). ``kinds`` optionally narrows."""
        hits = self.query(ticker=ticker, within_days=days, include_macro=include_macro, now=now)
        if kinds:
            hits = [h for h in hits if h.get("kind") in kinds]
        return len(hits) > 0

    def next_for(self, ticker: Optional[str], *, include_macro: bool = False,
                 now: Any = None) -> Optional[dict]:
        """The soonest pending catalyst for a name (or None) — for the swap lock's days-to-catalyst."""
        hits = self.query(ticker=ticker, include_macro=include_macro, now=now)
        return hits[0] if hits else None

    def hits_by_kind(self, ticker: Optional[str] = None) -> dict:
        """Map kind/macro_kind → newest hit datetime, for the grammar's ``event:<name>`` /
        ``before(a,b)`` helpers. Only ``status == 'hit'`` entries count as an event having occurred."""
        sup = self._superseded_ids()
        out: dict = {}
        want = str(ticker).upper() if ticker else None
        for e in self.all():
            if e.get("id") in sup or e.get("status") != "hit":
                continue
            if want is not None and e.get("ticker") != want and e.get("ticker") is not None:
                continue
            name = e.get("macro_kind") or e.get("kind")
            when = _parse(e.get("window_end")) or _parse(e.get("window_start"))
            if name and when and (name not in out or when > out[name]):
                out[name] = when
        return out

    def stats(self) -> dict:
        rows = self.all()
        sup = self._superseded_ids()
        live = [e for e in rows if e.get("id") not in sup]
        by_status: dict = {}
        for e in live:
            by_status[e.get("status")] = by_status.get(e.get("status"), 0) + 1
        return {"total": len(live), "by_status": by_status,
                "macro": sum(1 for e in live if e.get("ticker") is None), "path": self.path}


# --------------------------------------------------------------------------- macro seeding
def macro_windows(now: Any = None, horizon_days: int = 90) -> list:
    """Generate the *rule-deterministic* recurring macro windows over the horizon — and ONLY those.

    Grounded-or-silent: a cadence we can derive from the calendar alone is emitted; one we can't is
    not invented here.
      * **COT print** — weekly: as-of each Tuesday, released the following Friday (CFTC's fixed
        schedule). 2-day reporting lag is real → window = [Tuesday, Friday]. ``scheduled``.
      * **NFP** — first Friday of each month (BLS convention). ``scheduled``.
      * **CPI** — mid-month, day varies (~10th–15th). Emitted as an ``estimated`` [10th, 15th] window
        so it shows up, clearly flagged as not-yet-sourced.
      * **FOMC** — NOT generated. The Fed sets the dates; they must be written from a source.
    Returns a list of write()-ready kwarg dicts (caller writes them, deduping on macro_kind+start)."""
    n0 = _now_dt(now)
    end = n0 + timedelta(days=horizon_days)
    out = []

    # COT weekly: every Tuesday (as-of) → Friday (release)
    d = n0 - timedelta(days=7)
    while d <= end:
        if d.weekday() == 1:  # Tuesday
            fri = d + timedelta(days=3)
            if fri >= n0:
                out.append({"kind": "macro", "macro_kind": "cot_print",
                            "title": "CFTC Commitments of Traders (as-of Tue, released Fri)",
                            "window_start": d.strftime("%Y-%m-%d"),
                            "window_end": fri.strftime("%Y-%m-%d"),
                            "confidence": "scheduled", "source": "company_guidance",
                            "notes": "2-business-day reporting lag: Friday's print is Tuesday's data."})
        d += timedelta(days=1)

    # NFP: first Friday of each month in the horizon
    months = set()
    d = n0.replace(day=1)
    while d <= end:
        months.add((d.year, d.month))
        d = (d.replace(day=28) + timedelta(days=7)).replace(day=1)
    for (yr, mo) in sorted(months):
        first = datetime(yr, mo, 1, tzinfo=timezone.utc)
        offset = (4 - first.weekday()) % 7          # weekday 4 == Friday
        nfp = first + timedelta(days=offset)
        if n0 <= nfp <= end:
            out.append({"kind": "macro", "macro_kind": "nfp",
                        "title": "US Nonfarm Payrolls", "window_start": nfp.strftime("%Y-%m-%d"),
                        "window_end": nfp.strftime("%Y-%m-%d"), "confidence": "scheduled",
                        "source": "company_guidance"})
        # CPI estimated window 10th–15th
        cpi_s = datetime(yr, mo, 10, tzinfo=timezone.utc)
        cpi_e = datetime(yr, mo, 15, tzinfo=timezone.utc)
        if cpi_e >= n0 and cpi_s <= end:
            out.append({"kind": "macro", "macro_kind": "cpi",
                        "title": "US CPI (date estimated — confirm to source)",
                        "window_start": cpi_s.strftime("%Y-%m-%d"),
                        "window_end": cpi_e.strftime("%Y-%m-%d"), "confidence": "estimated",
                        "source": "company_guidance"})
    return out


def seed_macro(cal: CatalystCalendar, now: Any = None, horizon_days: int = 90,
               regime: Optional[dict] = None) -> int:
    """Idempotently seed the recurring macro windows into ``cal``. Skips any (macro_kind,
    window_start) already present (so a recurring job can call it every tick safely)."""
    existing = {(e.get("macro_kind"), e.get("window_start")[:10])
                for e in cal.all() if e.get("ticker") is None and e.get("window_start")}
    n = 0
    for kw in macro_windows(now, horizon_days):
        key = (kw["macro_kind"], kw["window_start"][:10])
        if key in existing:
            continue
        cal.write(regime=regime, **kw)
        existing.add(key)
        n += 1
    return n
