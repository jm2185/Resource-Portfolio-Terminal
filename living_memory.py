"""
Living Memory — the cockpit's central nervous system (Forge Phase 1).

Every view and agent reads from and writes to one shared, typed, append-only store, so research
stops being isolated chat logs and starts compounding: a note you type in the Book reaches the next
Council run; a Council verdict becomes a prior the What-If inherits; a regime snapshot lets you ask
"how did explorers behave under a regime like this one before?".

Design, from first principles + the house values (transparency, auditability, a family-vehicle
track record):
  * **Append-only & immutable.** Entries are never edited in place. A correction is a NEW entry that
    supersedes the old one (``supersede``), so the full reasoning history survives — you can always
    see what you thought and when. This is the audit trail, not a cache.
  * **Structured JSONL.** One human-readable, git-diffable line per entry. At a 4-name book the query
    volume is tiny, so a DB index buys nothing and costs the transparency a binary file would break.
  * **Provenance on every entry.** id, timestamp, type, source (who wrote it), and the live regime
    context at write time — so regime-conditioned recall is a first-class query.
  * **Pure & multi-process safe.** No network, no engine import (the writer passes regime context in).
    Each write opens the file in append mode (POSIX O_APPEND) so the cockpit, the MCP agents, and the
    engine can all write concurrently without a lock.

This module is the substrate only. The Dialectic Council (Phase 2), regime posture (Phase 3), and
the calibration loop (Phase 5) are consumers that hang off it.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional


#: The typed vocabulary of memory entries. Writing an unknown type fails fast — bad data never
#: silently enters the track record.
ENTRY_TYPES: frozenset = frozenset({
    "note",             # a plain-text research observation you (or an agent) recorded
    "thesis",           # the original underwriting thesis for a name (for Thesis-Check re-underwrite)
    "decision",         # a structured decision record (frozen legs, rho/phi/JSF, verdict, price)
    "council_verdict",  # a reconciled Dialectic Council output (verdict + convergence + dissent)
    "scenario_prior",   # a saved What-If result reused as a prior
    "regime_snapshot",  # the macro regime/posture captured at a point in time
    "outcome",          # a realized outcome at a horizon (feeds calibration)
    "catalyst",         # a pinned, decay-aware catalyst
    "pin",              # a pinned insight / badge surfaced on the board
    "thread",           # an imported/rendered research thread (markdown lives alongside)
})

DEFAULT_PATH = "data/living_memory.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _gen_id() -> str:
    # time-ordered prefix + short random suffix: human-scannable, sortable, collision-safe
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]


def regime_similarity(a: Optional[dict], b: Optional[dict], *, mri_scale: float = 12.0) -> float:
    """How alike two regime contexts are, in [0,1]. MRI distance (gaussian over ``mri_scale``)
    times a posture/tilt agreement factor. Used for "under a similar regime" recall. Returns 0.0
    when either side lacks a usable MRI (we never fabricate a match)."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0
    ma, mb = a.get("mri"), b.get("mri")
    try:
        ma, mb = float(ma), float(mb)
    except (TypeError, ValueError):
        return 0.0
    import math
    mri_term = math.exp(-((ma - mb) ** 2) / (2.0 * max(1e-6, mri_scale) ** 2))
    # posture / net-tilt agreement (whichever is present): same -> 1.0, differ -> 0.6, unknown -> 0.85
    def _tag(d):
        return str(d.get("posture") or d.get("net_tilt") or d.get("regime") or "").strip().lower()
    ta, tb = _tag(a), _tag(b)
    if not ta or not tb:
        tilt_term = 0.85
    else:
        tilt_term = 1.0 if ta == tb else 0.6
    return round(mri_term * tilt_term, 4)


class LivingMemory:
    """Append-only typed memory over a JSONL file. Cache-first reads (mtime-invalidated)."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._cache: Optional[list] = None
        self._mtime: Optional[float] = None

    # ------------------------------------------------------------------ write
    def write(self, type: str, *, text: str = "", ticker: Optional[str] = None,
              tags: Optional[list] = None, regime: Optional[dict] = None,
              meta: Optional[dict] = None, refs: Optional[list] = None,
              source: str = "user", confidence: Optional[str] = None,
              ts: Optional[str] = None) -> dict:
        """Append one entry and return it (with its assigned id). ``type`` must be in ENTRY_TYPES.

        ``regime`` is the live macro context at write time ({mri, posture/net_tilt, ...}) so the
        entry can later be recalled by regime similarity — the writer supplies it (this module never
        reaches into the engine). ``refs`` links to other entry ids (threads, supersession, sources)."""
        t = str(type)
        if t not in ENTRY_TYPES:
            raise ValueError(f"unknown memory type {t!r}; expected one of {sorted(ENTRY_TYPES)}")
        entry = {
            "id": _gen_id(),
            "ts": ts or _now_iso(),
            "type": t,
            "ticker": (str(ticker).strip() or None) if ticker else None,
            "text": str(text or ""),
            "tags": [str(x) for x in (tags or [])],
            "regime": dict(regime) if isinstance(regime, dict) else None,
            "meta": dict(meta) if isinstance(meta, dict) else {},
            "refs": [str(x) for x in (refs or [])],
            "source": str(source or "user"),
            "confidence": confidence,
        }
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as fh:   # O_APPEND -> multi-process safe
            fh.write(line + "\n")
            fh.flush()
        if self._cache is not None:                          # keep the warm cache coherent
            self._cache.append(entry)
            try:
                self._mtime = os.path.getmtime(self.path)
            except OSError:
                self._mtime = None
        return entry

    def supersede(self, old_id: str, type: str, **kw) -> dict:
        """Record a correction as a NEW entry that points back at ``old_id`` (never an in-place
        edit — the prior reasoning stays in the record). The superseded id is tracked in ``refs``
        and ``meta.supersedes``."""
        refs = list(kw.pop("refs", []) or [])
        if old_id and old_id not in refs:
            refs.append(old_id)
        meta = dict(kw.pop("meta", {}) or {})
        meta["supersedes"] = old_id
        return self.write(type, refs=refs, meta=meta, **kw)

    # ------------------------------------------------------------------ read
    def all(self) -> list:
        """Every entry, oldest-first. Cache-first; reloads only when the file changed on disk."""
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self._cache, self._mtime = [], None
            return []
        if self._cache is not None and self._mtime == mtime:
            return self._cache
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
                        continue                              # tolerate a torn/partial line, never crash
        except OSError:
            return self._cache or []
        self._cache, self._mtime = out, mtime
        return out

    def _superseded_ids(self) -> set:
        ids = set()
        for e in self.all():
            sup = (e.get("meta") or {}).get("supersedes")
            if sup:
                ids.add(sup)
        return ids

    def query(self, *, ticker: Optional[str] = None, type: Optional[str] = None,
              tag: Optional[str] = None, contains: Optional[str] = None,
              regime_like: Optional[dict] = None, regime_min: float = 0.55,
              source: Optional[str] = None, since: Optional[str] = None,
              include_superseded: bool = False, limit: int = 50,
              newest_first: bool = True) -> list:
        """Filtered recall. All filters AND together. ``regime_like`` keeps only entries whose
        captured regime is at least ``regime_min`` similar (see ``regime_similarity``) and annotates
        each hit with ``_regime_match``. Superseded entries are hidden unless asked for."""
        sup = set() if include_superseded else self._superseded_ids()
        rows = []
        for e in self.all():
            if e.get("id") in sup:
                continue
            if ticker and (e.get("ticker") or "").upper() != str(ticker).upper():
                continue
            if type and e.get("type") != type:
                continue
            if source and e.get("source") != source:
                continue
            if tag and tag not in (e.get("tags") or []):
                continue
            if contains and contains.lower() not in (e.get("text") or "").lower():
                continue
            if since and str(e.get("ts") or "") < str(since):
                continue
            if regime_like is not None:
                sim = regime_similarity(regime_like, e.get("regime"))
                if sim < regime_min:
                    continue
                e = {**e, "_regime_match": sim}
            rows.append(e)
        rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=newest_first)
        return rows[:limit] if limit else rows

    def latest(self, ticker: Optional[str] = None, type: Optional[str] = None) -> Optional[dict]:
        """Most recent (non-superseded) entry matching the filters, or None."""
        hits = self.query(ticker=ticker, type=type, limit=1, newest_first=True)
        return hits[0] if hits else None

    def thread(self, ticker: str, *, include_superseded: bool = False) -> list:
        """All entries for one name, oldest-first — the name's living research thread."""
        return self.query(ticker=ticker, include_superseded=include_superseded,
                           limit=0, newest_first=False)

    # ------------------------------------------------------------------ management
    # Pin / retract / reaffirm — the operator's control over memory, expressed within the
    # append-only model (nothing is edited in place; corrections supersede, pins are entries).
    def get(self, entry_id: str) -> Optional[dict]:
        """The entry with this id (regardless of supersession), or None."""
        for e in self.all():
            if e.get("id") == entry_id:
                return e
        return None

    def pinned_ids(self) -> set:
        """Ids of entries currently pinned (a live ``pin`` entry references them in ``meta.pins``)."""
        return {(p.get("meta") or {}).get("pins") for p in self.query(type="pin", limit=500)
                if (p.get("meta") or {}).get("pins")}

    def pin(self, entry_id: str, source: str = "user") -> dict:
        """Pin an entry — a first-class ``pin`` entry pointing at it (kept out of decay, sorts first)."""
        e = self.get(entry_id) or {}
        return self.write("pin", text="📌 " + str(e.get("text", ""))[:60], ticker=e.get("ticker"),
                          refs=[entry_id], meta={"pins": entry_id}, source=source)

    def unpin(self, entry_id: str) -> int:
        """Remove the pin(s) on an entry (supersede the pin entries)."""
        n = 0
        for p in self.query(type="pin", limit=500):
            if (p.get("meta") or {}).get("pins") == entry_id:
                self.supersede(p["id"], "pin", text=p.get("text", ""), ticker=p.get("ticker"),
                               meta={"unpinned": entry_id})
                n += 1
        return n

    def retract(self, entry_id: str, source: str = "user") -> Optional[dict]:
        """Retract an entry — supersede it with a tombstone (``meta.retracted``) so it leaves the
        live stream entirely. The record survives (audit trail); readers hide ``meta.retracted``."""
        e = self.get(entry_id)
        if not e:
            return None
        return self.supersede(entry_id, e.get("type", "note"), text="(retracted)",
                              ticker=e.get("ticker"), source=source, meta={"retracted": True})

    def reaffirm(self, entry_id: str, regime: Optional[dict] = None, source: str = "user") -> Optional[dict]:
        """Re-confirm a stale entry — supersede it with a fresh-dated copy (resets decay)."""
        e = self.get(entry_id)
        if not e:
            return None
        return self.supersede(entry_id, e.get("type", "note"), text=e.get("text", ""),
                              ticker=e.get("ticker"), regime=regime, source=source,
                              meta={"reaffirmed": True})

    def stats(self) -> dict:
        """Counts by type and by ticker (book-level entries under '_book') — feeds the matrix view."""
        by_type: dict = {}
        by_ticker: dict = {}
        sup = self._superseded_ids()
        n = 0
        for e in self.all():
            if e.get("id") in sup:
                continue
            n += 1
            by_type[e.get("type")] = by_type.get(e.get("type"), 0) + 1
            k = e.get("ticker") or "_book"
            by_ticker[k] = by_ticker.get(k, 0) + 1
        return {"total": n, "by_type": by_type, "by_ticker": by_ticker, "path": self.path}
