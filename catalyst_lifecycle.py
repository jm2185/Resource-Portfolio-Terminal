"""
Catalyst lifecycle — the unification seam (Forge Phase 1).

The cockpit carried TWO catalyst representations that never spoke to each other:

  * the forward **calendar** (``catalyst_calendar.py``) — windows + identity + a lifecycle
    (``pending → hit/missed/delayed/void``), read by the Sentinel, the rotation catalyst-lock and
    the cockpit strip — but it never moved the rating;
  * the realized **overlay** (``catalyst_engine.py`` / ``data/catalysts.json``) — printed events
    that DO move the Q/V/p_discovery rating — but with no stable identity and no link back to the
    window they resolved.

So a catalyst's life was split across two stores that could not reconcile: you could not tell
whether a *scheduled* "Q3 drill results" window actually delivered, the forward view never informed
the score, and the calibration flywheel could not see a catalyst as a forecastable event.

This module joins them on **one identity** (the calendar entry id) across **one lifecycle**:

  * :func:`reconcile` — drives the calendar lifecycle from realized overlay events. A printed event
    is matched to the pending window it resolves (same ticker · kind-family · realized date inside
    the window ± a grace) and that window is transitioned to ``hit`` with the realized outcome
    stamped on it; windows whose horizon has fully passed unmatched expire to ``missed``.
  * :func:`unified_view` — returns each catalyst as a SINGLE object across its whole life (the
    scheduled window + the realized outcome if any + the thesis it underwrites) — the one truth the
    cockpit, the calibration flywheel and the scenario layer can all read.
  * :func:`link_thesis` — bind a catalyst to the open thesis/decision it underwrites, so the
    flywheel can grade the call when the catalyst resolves.

Grounded-or-silent and immutable, like the rest of the Forge layer: it transitions ONLY via the
calendar's ``supersede`` (the audit trail is preserved), never invents a realized event, and treats
a missing/empty store as a clean no-op. Pure stdlib; the only dependency is ``catalyst_calendar``.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta
from typing import Any, Optional

import catalyst_calendar as cc

DEFAULT_FEED_PATH = "data/catalysts.json"

#: Which calendar KINDS a realized OVERLAY event-type can plausibly resolve. The realized side
#: (``catalyst_engine.EVENT_TYPES``) is coarser than the calendar's lifecycle kinds, so a family
#: map keeps matching honest without forcing a 1:1 vocabulary. ``news`` resolves no specific window.
OVERLAY_TO_KINDS: dict[str, set] = {
    "drill_result": {"drill_result", "assay"},
    "grade_beat": {"drill_result", "assay"},
    "resource_expansion": {"assay", "pea", "pfs", "fs"},
    "permitting": {"permit"},
    "financing": {"financing_window"},
    # metallurgy / recovery / study headlines classify as "catalyst" in catalyst_engine today, so a
    # met-results or economic-study window is resolved through this family.
    "catalyst": {"metallurgy", "pea", "pfs", "fs"},
    "news": set(),
}


def realized_events_from_feed(path: str = DEFAULT_FEED_PATH) -> list[dict[str, Any]]:
    """Load the realized overlay events (``data/catalysts.json`` envelope). Never raises — a
    missing/corrupt feed yields ``[]`` so the lifecycle degrades to a clean no-op."""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            env = json.load(fh)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    events = env.get("events", []) if isinstance(env, dict) else (env if isinstance(env, list) else [])
    return [e for e in events if isinstance(e, dict)]


def _live_pending(calendar: cc.CatalystCalendar) -> list[dict[str, Any]]:
    """All non-superseded, still-``pending`` NAME windows (macro excluded) — including ones whose
    window is already in the past (``query`` hides those, but reconciliation must still resolve or
    expire them)."""
    sup = calendar._superseded_ids()
    return [e for e in calendar.all()
            if e.get("id") not in sup and e.get("status") == "pending" and e.get("ticker")]


def _realized_payload(ev: dict[str, Any], realized_dt) -> dict[str, Any]:
    """The slice of a printed overlay event stamped onto the window it resolved (grounded: the
    issuer headline verbatim, never paraphrased)."""
    return {
        "headline": str(ev.get("headline") or "").strip(),
        "date": realized_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": str(ev.get("type") or "news").lower(),
        "impact": ev.get("impact"),
        "magnitude": ev.get("magnitude"),
        "p_discovery_delta": ev.get("p_discovery_delta"),
        "source_url": str(ev.get("link") or ev.get("source_url") or "").strip(),
    }


def reconcile(calendar: cc.CatalystCalendar, realized_events: Optional[list] = None, *,
              now: Any = None, grace_days: int = 14, expire_to: str = "missed",
              feed_path: str = DEFAULT_FEED_PATH) -> dict[str, Any]:
    """Drive the calendar lifecycle from realized overlay events.

    For each printed event, find the single best pending window it resolves — same ticker, a
    kind in :data:`OVERLAY_TO_KINDS`, and a realized date within ``[window_start - grace,
    window_end + grace]`` — preferring an exact kind match then the nearest window start. That
    window transitions to ``hit`` with the realized outcome stamped on it (one identity, one
    lifecycle). Each window is hit at most once; each event resolves at most one window.

    Pending windows whose ``window_end + grace`` is fully in the past with no match expire to
    ``expire_to`` (default ``missed``) — an honest, auditable "this didn't land" rather than a
    window that lingers ``pending`` forever.

    Idempotent: re-running with the same feed is a no-op (already-``hit`` windows are skipped).
    Returns a report ``{hits, missed, unmatched_realized, pending_remaining, as_of}``.
    """
    if realized_events is None:
        realized_events = realized_events_from_feed(feed_path)
    now_dt = cc._now_dt(now)
    grace = timedelta(days=max(0, grace_days))
    pending = _live_pending(calendar)

    realized = sorted(
        [ev for ev in (realized_events or []) if isinstance(ev, dict) and ev.get("ticker")],
        key=lambda ev: str(ev.get("date") or ""))

    hits: list[dict] = []
    unmatched: list[dict] = []
    used: set = set()

    for ev in realized:
        tk = str(ev.get("ticker")).strip().upper()
        etype = str(ev.get("type") or "news").lower()
        fam = OVERLAY_TO_KINDS.get(etype, set())
        ed = cc._parse(ev.get("date"))
        if not fam or ed is None:
            unmatched.append(ev)
            continue
        cands = []
        for w in pending:
            if w["id"] in used or str(w.get("ticker") or "").upper() != tk or w.get("kind") not in fam:
                continue
            ws = cc._parse(w.get("window_start"))
            we = cc._parse(w.get("window_end")) or ws
            if ws is None:
                continue
            if ws - grace <= ed <= we + grace:
                exact = 0 if w.get("kind") == etype else 1
                cands.append((exact, abs((ed - ws).days), w))
        if not cands:
            unmatched.append(ev)
            continue
        cands.sort(key=lambda c: (c[0], c[1]))
        w = cands[0][2]
        used.add(w["id"])
        payload = _realized_payload(ev, ed)
        # carry the window's own source_url forward if the realized event lacks one (a SCHEDULED
        # window already has one — supersede->write would otherwise reject it).
        src = payload["source_url"] or str(w.get("source_url") or "")
        new = calendar.set_status(w["id"], "hit", realized=payload, source_url=src)
        hits.append({"window_id": w["id"], "new_id": (new or {}).get("id"), "ticker": tk,
                     "kind": w.get("kind"), "title": w.get("title"), "realized": payload})

    missed: list[dict] = []
    for w in pending:
        if w["id"] in used:
            continue
        we = cc._parse(w.get("window_end")) or cc._parse(w.get("window_start"))
        if we is not None and (we + grace) < now_dt:
            new = calendar.set_status(w["id"], expire_to)
            missed.append({"window_id": w["id"], "new_id": (new or {}).get("id"),
                           "ticker": w.get("ticker"), "kind": w.get("kind"), "title": w.get("title")})

    resolved_ids = used | {m["window_id"] for m in missed}
    pending_remaining = sum(1 for w in pending if w["id"] not in resolved_ids)
    return {"hits": hits, "missed": missed, "unmatched_realized": unmatched,
            "pending_remaining": pending_remaining, "as_of": cc._now_iso()}


def _enrich(e: dict[str, Any], now_dt) -> dict[str, Any]:
    ws = cc._parse(e.get("window_start"))
    we = cc._parse(e.get("window_end")) or ws
    return {
        "catalyst_id": e.get("id"),
        "ticker": e.get("ticker"),
        "kind": e.get("kind"),
        "macro_kind": e.get("macro_kind"),
        "title": e.get("title"),
        "window_start": e.get("window_start"),
        "window_end": e.get("window_end"),
        "confidence": e.get("confidence"),
        "grounded": e.get("grounded"),
        "status": e.get("status"),
        "realized": e.get("realized"),
        "linked_thesis": e.get("linked_thesis"),
        "source_url": e.get("source_url"),
        "_days_to_start": max(0, (ws - now_dt).days) if ws else None,
        "_window_open": bool(ws and we and ws <= now_dt <= we),
    }


def unified_view(calendar: cc.CatalystCalendar, realized_events: Optional[list] = None, *,
                 ticker: Optional[str] = None, status: Optional[str] = None,
                 include_macro: bool = False, now: Any = None,
                 include_unplanned: bool = True,
                 feed_path: str = DEFAULT_FEED_PATH) -> list[dict[str, Any]]:
    """Each catalyst as ONE object across its whole lifecycle — the single read surface for the
    cockpit, the calibration flywheel and the scenario layer.

    Folds the calendar (identity · window · lifecycle · realized outcome · linked thesis) with the
    realized overlay feed: any printed event that resolved no scheduled window is surfaced as an
    ``unplanned`` hit (synthetic id) so nothing is lost. Sorted soonest-window first.

    * ``ticker`` filters to a name (``include_macro`` folds the macro tape in);
    * ``status`` optionally narrows (``pending``/``hit``/…); default returns every live status.
    """
    now_dt = cc._now_dt(now)
    sup = calendar._superseded_ids()
    want = str(ticker).upper() if ticker else None

    rows: list[dict] = []
    realized_keys_seen: set = set()
    for e in calendar.all():
        if e.get("id") in sup:
            continue
        etk = e.get("ticker")
        if want is not None and etk != want and not (include_macro and etk is None):
            continue
        if status is not None and e.get("status") != status:
            continue
        rows.append(_enrich(e, now_dt))
        rz = e.get("realized")
        if isinstance(rz, dict):
            realized_keys_seen.add((str(etk or "").upper(),
                                    str(rz.get("headline") or "").lower(),
                                    str(rz.get("date") or "")[:10]))

    if include_unplanned:
        if realized_events is None:
            realized_events = realized_events_from_feed(feed_path)
        for ev in realized_events or []:
            if not isinstance(ev, dict) or not ev.get("ticker"):
                continue
            tk = str(ev.get("ticker")).strip().upper()
            if want is not None and tk != want:
                continue
            ed = cc._parse(ev.get("date"))
            key = (tk, str(ev.get("headline") or "").lower(), (ed.strftime("%Y-%m-%d") if ed else ""))
            if key in realized_keys_seen:
                continue
            if status is not None and status != "hit":
                continue
            rows.append({
                "catalyst_id": "ovl_" + hashlib.md5("|".join(key).encode("utf-8")).hexdigest()[:12],
                "ticker": tk, "kind": str(ev.get("type") or "news").lower(), "macro_kind": None,
                "title": str(ev.get("headline") or "").strip(),
                "window_start": ed.strftime("%Y-%m-%dT%H:%M:%SZ") if ed else None,
                "window_end": ed.strftime("%Y-%m-%dT%H:%M:%SZ") if ed else None,
                "confidence": None, "grounded": bool(str(ev.get("link") or "").strip()),
                "status": "hit", "unplanned": True,
                "realized": _realized_payload(ev, ed) if ed else None,
                "linked_thesis": None, "source_url": str(ev.get("link") or "").strip(),
                "_days_to_start": None, "_window_open": False,
            })

    rows.sort(key=lambda r: str(r.get("window_start") or "~"))   # None sorts last
    return rows


def link_thesis(calendar: cc.CatalystCalendar, catalyst_id: str, thesis_id: str) -> Optional[dict]:
    """Bind a catalyst window to the open thesis/decision it underwrites (the calibration join):
    when the catalyst later resolves, the flywheel can grade the call it was the trigger for.
    A correction via supersede — the prior link survives in the audit trail. Returns the new entry
    (or ``None`` if the id is unknown)."""
    if not calendar.get(catalyst_id):
        return None
    return calendar.supersede(catalyst_id, linked_thesis=str(thesis_id))
