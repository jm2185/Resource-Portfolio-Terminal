"""CommodityEx Monitor v5.3 — Phase 8: Live Catalyst & Signal Reactivity engine.

Turns real-world junior-miner events — drill results, financings/dilution, permitting
milestones, material catalysts — into bounded **signal overlays** that move the Conviction Mode
TQV rating, plus a clean **recent-catalyst** list for the cards.

Design (consistent with ``asymmetry_rating.py`` and the Phase 6 ingestion seam):
  * Pure-Python, dependency-free (stdlib ``datetime`` only) → importable, testable, frontend-agnostic.
  * **Recency-weighted**: each event decays by an exponential half-life, so a six-month-old hit
    barely moves the needle while last week's assay does.
  * **Bounded & additive**: overlays are clamped (conviction nudge is capped; nothing can run away),
    and they feed the EXISTING rating inputs (conviction → Q, dilution → forensic gate, permitting
    stage → Q lens). No new MPT/sizing machinery.
  * **Graceful**: a missing/stale/corrupt feed is a no-op (neutral overlay), never an exception.

Event schema (one dict per event; every field optional except ``ticker``+``type``):
    {"ticker","date" (ISO),"type","headline","impact" (-1..1),"magnitude" (0..1),
     "share_change_pct" (financing),"stage_to" (permitting),"p_discovery_delta" (drill)}
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

__all__ = [
    "DEFAULT_CATALYST_CONFIG",
    "summarize_catalysts",
    "build_catalyst_overlays",
    "load_catalyst_feed",
    "merge_catalyst_config",
]

SCHEMA_VERSION = 1
DEFAULT_FEED_PATH = "data/catalysts.json"

#: Event types we understand. Unknown types degrade to a generic "news" weighting.
EVENT_TYPES = ("drill_result", "financing", "permitting", "catalyst", "news")

DEFAULT_CATALYST_CONFIG: dict[str, Any] = {
    "enabled": True,
    "feed_path": DEFAULT_FEED_PATH,
    "ttl_seconds": 86400,
    "half_life_days": 45.0,            # recency decay: a 45-day-old event counts half
    "recent_window_days": 180,         # events older than this are ignored entirely
    "max_display": 3,                  # cap surfaced events per basket (calm cards)
    "conviction_delta_cap": 0.35,      # max +/- nudge to the conviction input (Q pillar)
    "delta_softness": 1.0,             # tanh sensitivity: smaller -> reaches the cap faster
    "dilution_lookback_days": 365,     # window over which financings accumulate dilution
    # per-type weight on the conviction nudge (financing handled separately via dilution)
    "impact_weights": {
        "drill_result": 1.0, "catalyst": 0.85, "permitting": 0.70, "news": 0.50, "financing": 0.30,
    },
    "as_of": None,                     # ISO date override for deterministic scoring (else today)
}


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _num(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _parse_date(s: Any) -> Optional[date]:
    if isinstance(s, date):
        return s
    if not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s.strip()[:len(fmt) + 2 if "T" in fmt else 10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def _resolve_as_of(config: dict[str, Any]) -> date:
    aod = _parse_date(config.get("as_of")) if config.get("as_of") else None
    return aod or datetime.now(timezone.utc).date()


def merge_catalyst_config(config: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Shallow-merge a caller ``catalysts`` block over the defaults (one level deep)."""
    cfg = dict(DEFAULT_CATALYST_CONFIG)
    block = (config or {}).get("catalysts", config or {}) if config else {}
    if not isinstance(block, dict):
        return cfg
    for k, v in block.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
        else:
            cfg[k] = v
    return cfg


def _decay(age_days: float, half_life: float) -> float:
    if half_life <= 0:
        return 1.0
    return 0.5 ** (max(0.0, age_days) / half_life)


def _event_label(ev: dict[str, Any]) -> str:
    if ev.get("headline"):
        return str(ev["headline"])
    t = str(ev.get("type", "news")).replace("_", " ")
    return t.upper()


# --------------------------------------------------------------------------- #
#  Scoring
# --------------------------------------------------------------------------- #
def summarize_catalysts(events: list[dict[str, Any]],
                        config: Optional[dict[str, Any]] = None,
                        as_of: Optional[date] = None) -> dict[str, Any]:
    """Score one ticker's events into a bounded signal overlay + a recent-events list.

    Returns:
        {
          "conviction_delta": float,      # bounded nudge to add to the conviction input (Q)
          "dilution_velocity": float|None,# annualized dilution from recent financings (gate)
          "permitting_stage": str|None,   # latest permitting stage_to (Q permitting lens)
          "p_discovery_delta": float,     # net drill-driven discovery shift (surfaced; V follow-up)
          "net_signal": float,            # overall -1..1 catalyst posture (for a compact indicator)
          "recent": [ {label,type,impact,age_days,when,weight} ],  # newest first, capped
          "count": int,
        }
    """
    cfg = merge_catalyst_config(config)
    aod = as_of or _resolve_as_of(cfg)
    half = float(cfg.get("half_life_days", 45.0))
    window = float(cfg.get("recent_window_days", 180))
    weights = cfg.get("impact_weights", {})

    conv_raw = 0.0            # signed, recency-decayed catalyst sum (drives the conviction nudge)
    p_disc = 0.0
    dilution = 0.0
    permitting_stage = None
    permit_latest = None
    scored: list[dict[str, Any]] = []

    for raw in events or []:
        if not isinstance(raw, dict):
            continue
        ev_date = _parse_date(raw.get("date"))
        age = (aod - ev_date).days if ev_date else 9999.0
        if age < 0:                                   # future-dated -> treat as today
            age = 0.0
        if age > window:
            continue
        etype = str(raw.get("type", "news")).lower()
        if etype not in EVENT_TYPES:
            etype = "news"
        impact = _clamp(_num(raw.get("impact"), 0.0), -1.0, 1.0)
        magnitude = _clamp(_num(raw.get("magnitude"), abs(impact)) or abs(impact), 0.0, 1.0)
        w = _decay(age, half)

        # conviction nudge: signed impact * magnitude * type-weight, decayed by recency.
        # Summed (not averaged) so a fresh strong hit moves more than a stale one and events stack.
        tw = float(weights.get(etype, 0.5))
        conv_raw += impact * magnitude * tw * w

        # drill-driven discovery shift (surfaced; scenario re-run is a follow-up)
        if etype == "drill_result":
            pdd = _num(raw.get("p_discovery_delta"), 0.0) or 0.0
            p_disc += pdd * w

        # financing -> dilution velocity (gate). share_change_pct is the event's share-count step.
        if etype == "financing" and age <= float(cfg.get("dilution_lookback_days", 365)):
            sc = _num(raw.get("share_change_pct"), None)
            if sc is not None and sc > 0:
                dilution += sc                         # accumulate raises within the lookback

        # permitting -> latest stage_to
        if etype == "permitting" and raw.get("stage_to"):
            if permit_latest is None or (ev_date and ev_date >= permit_latest):
                permit_latest = ev_date or permit_latest
                permitting_stage = str(raw["stage_to"]).upper()

        scored.append({
            "label": _event_label(raw), "type": etype, "impact": round(impact, 3),
            "age_days": int(age), "when": ev_date.isoformat() if ev_date else None,
            "weight": round(w, 3),
        })

    cap = float(cfg.get("conviction_delta_cap", 0.35))
    k = max(1e-6, float(cfg.get("delta_softness", 1.0)))
    squashed = math.tanh(conv_raw / k)                      # bounded (-1,1); fades with age, stacks with count
    conviction_delta = round(cap * squashed, 4)
    net_signal = round(squashed, 4)

    scored.sort(key=lambda e: e["age_days"])           # newest first
    return {
        "conviction_delta": round(conviction_delta, 4),
        "dilution_velocity": round(dilution, 4) if dilution > 0 else None,
        "permitting_stage": permitting_stage,
        "p_discovery_delta": round(p_disc, 4),
        "net_signal": round(net_signal, 4),
        "recent": scored[: int(cfg.get("max_display", 3))],
        "count": len(scored),
    }


def build_catalyst_overlays(events: list[dict[str, Any]], tickers: list[str],
                            config: Optional[dict[str, Any]] = None,
                            as_of: Optional[date] = None) -> dict[str, dict[str, Any]]:
    """Group a flat event list by ticker and summarize each requested ticker."""
    cfg = merge_catalyst_config(config)
    aod = as_of or _resolve_as_of(cfg)
    by_ticker: dict[str, list[dict[str, Any]]] = {t: [] for t in tickers}
    for ev in events or []:
        if isinstance(ev, dict) and ev.get("ticker") in by_ticker:
            by_ticker[ev["ticker"]].append(ev)
    return {t: summarize_catalysts(by_ticker[t], cfg, aod) for t in tickers}


# --------------------------------------------------------------------------- #
#  Feed loader (graceful, mirrors load_ingestion_cache)
# --------------------------------------------------------------------------- #
def load_catalyst_feed(path: str = DEFAULT_FEED_PATH, *,
                       max_age_seconds: Optional[float] = None) -> dict[str, Any]:
    """Load the catalyst feed envelope. Always returns a dict with ``events`` (possibly empty)
    and a ``status`` in {live, stale, missing, error} — never raises."""
    if not path or not os.path.exists(path):
        return {"status": "missing", "events": [], "reason": "no feed file"}
    try:
        with open(path, "r") as f:
            env = json.load(f)
    except Exception as e:                              # corrupt JSON -> graceful empty
        return {"status": "error", "events": [], "reason": str(e)}

    events = env.get("events", []) if isinstance(env, dict) else []
    if not isinstance(events, list):
        events = []
    status = "live"
    gen = env.get("generated_at") if isinstance(env, dict) else None
    ttl = max_age_seconds if max_age_seconds is not None else (
        env.get("ttl_seconds", 86400) if isinstance(env, dict) else 86400)
    if gen:
        try:
            gen_ts = datetime.fromisoformat(str(gen).replace("Z", "")).timestamp()
            if ttl and (time.time() - gen_ts) > float(ttl):
                status = "stale"
        except ValueError:
            pass
    return {"status": status, "events": events,
            "generated_at": gen, "source": (env.get("source") if isinstance(env, dict) else None),
            "schema_version": (env.get("schema_version") if isinstance(env, dict) else None)}
