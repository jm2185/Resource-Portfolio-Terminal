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


def reconciled_book_value(bvps, total_equity, shares_out, *, goodwill=0.0, tol=2.0):
    """Cross-check a sourced book-value-per-share against (equity − goodwill) ÷ shares — both sourced
    INDEPENDENTLY, so a units/decimal slip in ONE field can't silently pass. This is the guard for the
    GROY 10× book-value error: a stray 0.31 (vs the real 3.13 = $722M equity ÷ 231M shares) collapsed
    the margin-of-safety floor to ~$0.32 on a $2.86 name, and nothing caught it because the floor math
    faithfully used a bad input. Returns ``(value, ok, note)``:

      * agree within a factor of ``tol`` (covers legitimate tangible-vs-total book gaps) → trust the
        direct ``bvps`` (``ok=True``).
      * grossly divergent AND equity+shares are usable → the SELF-CONSISTENT equity÷shares value wins
        (``ok=False``) — a single corrupted field can no longer set the floor.
      * nothing to check against (equity/shares missing) → ``bvps`` unchanged (``ok=True``, unverified).

    Pure — no I/O, no engine state; unit-tested. Callers should surface ``ok=False`` (log / degrade)."""
    def _pos(x):
        try:
            return float(x) if x is not None and float(x) > 0 else None
        except (TypeError, ValueError):
            return None

    bv = _pos(bvps)
    eq, sh = _pos(total_equity), _pos(shares_out)
    try:
        gw = max(0.0, float(goodwill or 0.0))
    except (TypeError, ValueError):
        gw = 0.0
    expected = ((eq - gw) / sh) if (eq is not None and sh is not None and eq - gw > 0) else None

    if bv is None:
        if expected is not None:
            return expected, False, "book_value_per_share missing/invalid — using equity÷shares"
        return None, False, "no book value and no equity÷shares to derive one"
    if expected is None:
        return bv, True, "unverified — no equity÷shares to cross-check"
    ratio = bv / expected
    if (1.0 / tol) <= ratio <= tol:
        return bv, True, "consistent with equity÷shares"
    return (expected, False,
            f"book_value_per_share {bv:g} inconsistent with equity÷shares {expected:g} "
            f"(×{ratio:.2g}) — using the equity-derived value")


_AS_OF_GRACE_S = 86400.0    # a filing dated "today" fetched this morning is not a look-ahead


def pit_violations(data: dict) -> list:
    """Pure point-in-time hygiene scan over a cache dict (2026-07-08 reassessment, TF3 2.2).

    The store's write path (``set()``) coerces confidence and stamps ``fetched_at`` — but entries
    have been hand-edited around it (the 06-27 GROY re-rate rows), leaving an out-of-vocabulary
    confidence and ``as_of`` dates that POSTDATE their own ``fetched_at`` — look-ahead seams in a
    store whose ``as_at()`` reconstructs history by ``fetched_at``. This scan names every such
    violation. It is deliberately NON-FATAL: the cache must keep loading (the data is still the
    desk's best sourced state); the violations are surfaced so the re-write goes through the
    propose→confirm gate, not a crash. Kinds: ``confidence_vocab`` · ``look_ahead_as_of``."""
    out = []
    for ticker, bucket in (data or {}).items():
        if not isinstance(bucket, dict):
            continue
        for field, entry in bucket.items():
            if not isinstance(entry, dict):
                continue
            conf = entry.get("confidence")
            if conf is not None and conf not in _CONF:
                out.append({"ticker": ticker, "field": field, "kind": "confidence_vocab",
                            "detail": f"confidence {conf!r} not in {sorted(_CONF)}"})
            as_of, fetched = entry.get("as_of"), entry.get("fetched_at")
            if isinstance(fetched, (int, float)) and as_of:
                try:
                    as_of_epoch = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").timestamp()
                except ValueError:
                    continue                 # undated/odd formats are a freshness issue, not PIT
                if as_of_epoch > float(fetched) + _AS_OF_GRACE_S:
                    days = (as_of_epoch - float(fetched)) / 86400.0
                    out.append({"ticker": ticker, "field": field, "kind": "look_ahead_as_of",
                                "detail": f"as_of {as_of} postdates fetched_at by {days:.1f}d"})
    return out


class ResearchCache:
    def __init__(self, path: str | None = None):
        self.path = path or _PATH
        self._d = self._load()
        # PIT hygiene is checked on every load and SURFACED, never fatal — see pit_violations().
        self.pit_flags = pit_violations(self._d)
        if self.pit_flags:
            import logging
            logging.getLogger(__name__).warning(
                "research_cache: %d point-in-time violation(s) — %s",
                len(self.pit_flags),
                "; ".join(f"{v['ticker']}.{v['field']}: {v['kind']}" for v in self.pit_flags[:6]))

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
