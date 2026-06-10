"""
Provenance-stamped store for filings-derived fundamentals that NO market API provides —
in-ground silver-equivalent ounces (and the M&I/Inferred split), AISC, NAV / book value per
share, peer resource ounces. These are the inputs that used to be hardcoded in v5_config; they
now live here, each populated by the Claude-agent web-search fallback and carrying full
provenance: {value, source, as_of, confidence, fetched_at}.

Contract with the rest of the engine:
  * NO hardcoded valuation inputs in code — read them from here.
  * A field that has never been sourced is simply ABSENT (get() → None). The engine must treat
    that as "pending", widen the confidence ribbon, and flag it — never substitute a fake default.
  * Every value is attributable (source URL) and dated (as_of), so staleness and trust are visible.

Stdlib only; unit-testable on its own. Backing file: data/research_cache.json.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "research_cache.json")
_CONF = {"high", "med", "low"}


def _date_prefix(as_of) -> str | None:
    """The comparable ``YYYY-MM-DD`` prefix of an ISO date/datetime, or ``None`` if undated or
    unparseable. ISO date strings sort chronologically as plain strings, so callers compare the
    prefixes directly — no datetime arithmetic needed for an ordering test."""
    if not as_of:
        return None
    s = str(as_of).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except (ValueError, TypeError):
        return None


class ResearchCache:
    def __init__(self, path: str | None = None):
        self.path = path or _PATH
        self._d = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._d, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    # ---- write (agent web-search fallback populates this) ----
    def set(self, ticker: str, field: str, value, source: str, as_of: str,
            confidence: str = "med", note: str = "", force: bool = False) -> dict:
        """Provenance-stamped write, **as-of-aware** so a stale source cannot silently clobber the
        newer filings-derived inputs the JSF gate eats:
          * an older-dated incoming write is **refused** (returns the kept existing entry annotated
            with ``kept``/``reason``; nothing is written) unless ``force=True`` (operator correcting
            a bad source);
          * an equal/newer write (or one where either side is undated) proceeds, stashing the
            displaced entry one level deep under ``previous`` for cheap provenance (not a chain —
            any prior ``previous`` is dropped)."""
        if confidence not in _CONF:
            confidence = "med"
        entry = {"value": value, "source": str(source)[:400], "as_of": str(as_of),
                 "confidence": confidence, "fetched_at": time.time()}
        if note:
            entry["note"] = str(note)[:300]
        existing = (self._d.get(ticker.upper(), {}) or {}).get(field)
        new_d = _date_prefix(as_of)
        old_d = _date_prefix(existing.get("as_of")) if existing else None
        if existing and not force and new_d and old_d and new_d < old_d:
            kept = dict(existing)                         # copy: never pollute the stored entry
            kept["kept"] = "existing"
            kept["reason"] = f"incoming as_of {new_d} older than {old_d}"
            return kept
        if existing:
            entry["previous"] = {k: v for k, v in existing.items() if k != "previous"}
        self._d.setdefault(ticker.upper(), {})[field] = entry
        self._save()
        return entry

    # ---- read (engine consumes; absent => None, never a fake) ----
    def get(self, ticker: str, field: str) -> dict | None:
        return (self._d.get(ticker.upper(), {}) or {}).get(field)

    def value(self, ticker: str, field: str, default=None):
        e = self.get(ticker, field)
        return e["value"] if e else default

    def provenance(self, ticker: str) -> dict:
        """All sourced fields for a name (for the DATA & TRUST panel)."""
        return dict(self._d.get(ticker.upper(), {}) or {})

    def age_days(self, ticker: str, field: str):
        e = self.get(ticker, field)
        if not e or not e.get("as_of"):
            return None
        try:
            d = datetime.strptime(e["as_of"][:10], "%Y-%m-%d").date()
            return (date.today() - d).days
        except (ValueError, TypeError):
            return None

    def tickers(self) -> list:
        return sorted(self._d.keys())
