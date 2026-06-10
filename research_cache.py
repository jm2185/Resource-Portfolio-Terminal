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
_HISTORY_CAP = 12          # superseded entries kept per field (oldest dropped past this)


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
            confidence: str = "med", note: str = "") -> dict:
        """Set (or restate) a sourced field. POINT-IN-TIME DISCIPLINE (validation flywheel,
        Phase 4): a restatement never silently rewrites history — the prior entry is pushed onto
        the field's bounded ``history`` list (oldest-first), so ``as_at()`` can reconstruct what
        was known on any date and a later correction is a detectable EVENT, not an overwrite.
        The returned entry carries ``restated: True`` when it replaced a different value."""
        if confidence not in _CONF:
            confidence = "med"
        entry = {"value": value, "source": str(source)[:400], "as_of": str(as_of),
                 "confidence": confidence, "fetched_at": time.time()}
        if note:
            entry["note"] = str(note)[:300]
        bucket = self._d.setdefault(ticker.upper(), {})
        prior = bucket.get(field)
        if isinstance(prior, dict):
            history = list(prior.pop("history", []) or [])
            if prior.get("value") != value:
                entry["restated"] = True
            history.append(prior)                       # the superseded entry survives, dated
            entry["history"] = history[-_HISTORY_CAP:]
        bucket[field] = entry
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

    def as_at(self, ticker: str, field: str, on_date: str) -> dict | None:
        """The entry that was CURRENT on ``on_date`` (YYYY-MM-DD), reconstructed from the live
        entry + its restatement history by ``fetched_at`` — so a replay grades yesterday's
        valuation against yesterday's knowledge, never today's restatement. Returns None when the
        field didn't exist yet on that date."""
        live = self.get(ticker, field)
        if not live:
            return None
        try:
            cutoff = datetime.strptime(str(on_date)[:10], "%Y-%m-%d")
            cutoff_ts = cutoff.timestamp() + 86400.0    # end of that day, local-naive like fetched_at
        except (ValueError, TypeError):
            return None
        versions = list(live.get("history", []) or []) + [live]
        known = [v for v in versions
                 if isinstance(v.get("fetched_at"), (int, float)) and v["fetched_at"] <= cutoff_ts]
        if not known:
            return None
        out = dict(known[-1])
        out.pop("history", None)
        return out

    def tickers(self) -> list:
        return sorted(self._d.keys())
