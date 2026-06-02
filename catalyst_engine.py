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
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

__all__ = [
    "DEFAULT_CATALYST_CONFIG",
    "summarize_catalysts",
    "build_catalyst_overlays",
    "load_catalyst_feed",
    "merge_catalyst_config",
    "classify_headline",
    "match_ticker",
    "dedupe_events",
]

SCHEMA_VERSION = 1
DEFAULT_FEED_PATH = "data/catalysts.json"

#: Event types we understand. Unknown types degrade to a generic "news" weighting.
EVENT_TYPES = ("drill_result", "grade_beat", "resource_expansion",
               "financing", "permitting", "catalyst", "news")

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
    # per-type weight on the conviction nudge (Q). Drill/grade/resource are routed mostly to V
    # (their natural home) with a smaller Q echo, so the two pillars aren't double-counted.
    "impact_weights": {
        "drill_result": 0.45, "grade_beat": 0.45, "resource_expansion": 0.40,
        "catalyst": 0.85, "permitting": 0.70, "news": 0.50, "financing": 0.30,
    },
    # ---- V-pillar reactivity (Phase 8 follow-up): drill/grade/resource move the upside ----
    "v_impact_weights": {
        "drill_result": 1.0, "grade_beat": 1.0, "resource_expansion": 1.0,
        "catalyst": 0.40, "permitting": 0.30, "news": 0.20, "financing": 0.0,
    },
    "v_softness": 1.2,                 # tanh sensitivity for the V uplift
    "bull_uplift_cap": 0.30,           # max +/- adjustment to the bull scenario target
    "base_uplift_cap": 0.12,           # max +/- adjustment to the base case
    "p_discovery_cap": 0.20,           # bound on the net discovery-probability shift
    "v_move_threshold": 0.02,          # |bull_uplift| above which the card flags "V moved"
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
    v_weights = cfg.get("v_impact_weights", {})

    conv_raw = 0.0            # signed, recency-decayed catalyst sum (drives the conviction nudge, Q)
    v_raw = 0.0               # signed, recency-decayed UPSIDE sum (drives the V scenario uplift)
    p_disc = 0.0
    dilution = 0.0
    permitting_stage = None
    permit_latest = None
    v_drivers: list[tuple] = []
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

        # conviction nudge (Q): signed impact * magnitude * type-weight, decayed by recency.
        # Summed (not averaged) so a fresh strong hit moves more than a stale one and events stack.
        tw = float(weights.get(etype, 0.5))
        conv_raw += impact * magnitude * tw * w

        # upside (V): drill / grade beat / resource expansion (+ a little catalyst) move the
        # scenario bands. Same recency-weighted, signed machinery, separate type weights.
        vtw = float(v_weights.get(etype, 0.0))
        if vtw:
            contrib = impact * magnitude * vtw * w
            v_raw += contrib
            if contrib > 0:
                v_drivers.append((contrib, _event_label(raw)))

        # discovery-probability shift (V): explicit p_discovery_delta on drill/grade/resource,
        # plus a small implicit bump from a positive drill/grade beat lacking an explicit value.
        if etype in ("drill_result", "grade_beat", "resource_expansion"):
            pdd = _num(raw.get("p_discovery_delta"), None)
            if pdd is None and impact > 0:
                pdd = 0.05 * impact * magnitude       # modest implicit discovery bump
            p_disc += (pdd or 0.0) * w

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

    # V uplift: tanh-squashed upside signal -> bounded bull/base scenario adjustments.
    vk = max(1e-6, float(cfg.get("v_softness", 1.2)))
    v_signal = math.tanh(v_raw / vk)
    bull_uplift_pct = round(float(cfg.get("bull_uplift_cap", 0.30)) * v_signal, 4)
    base_uplift_pct = round(float(cfg.get("base_uplift_cap", 0.12)) * v_signal, 4)
    p_cap = float(cfg.get("p_discovery_cap", 0.20))
    p_discovery_delta = round(_clamp(p_disc, -p_cap, p_cap), 4)
    v_moved = abs(bull_uplift_pct) >= float(cfg.get("v_move_threshold", 0.02))
    v_drivers.sort(reverse=True)
    drivers = [lbl for _, lbl in v_drivers[:2]]

    scored.sort(key=lambda e: e["age_days"])           # newest first
    return {
        "conviction_delta": round(conviction_delta, 4),
        "dilution_velocity": round(dilution, 4) if dilution > 0 else None,
        "permitting_stage": permitting_stage,
        "p_discovery_delta": p_discovery_delta,
        "net_signal": round(net_signal, 4),
        # V-pillar reactivity
        "bull_uplift_pct": bull_uplift_pct,
        "base_uplift_pct": base_uplift_pct,
        "v_signal": round(v_signal, 4),
        "v_moved": v_moved,
        "v_drivers": drivers,
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
#  Headline classification / ticker matching / dedup  (for RSS + filings sources)
# --------------------------------------------------------------------------- #
_GRADE_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*g/?\s?t", re.I)          # "1,240 g/t" / "1240gt"
_AMOUNT_RE = re.compile(r"[\$cC]?\s?(\d{1,4}(?:\.\d+)?)\s*(?:million|m\b|mm)", re.I)

# keyword -> (event_type, base_impact, magnitude). Order matters: first match wins.
_RULES: list = [
    ("financing", ("financing", -0.30, 0.5),
     ("bought deal", "bought-deal", "private placement", "non-brokered", "flow-through",
      "offering", "financing", "placement", "units at", "warrants", "capital raise", "raise of")),
    ("permitting", ("permitting", 0.45, 0.6),
     ("plan of operations", "record of decision", "permit", "permitting", "authorization",
      "environmental approval", "eis ", "draft eis", "approval to")),
    ("resource_expansion", ("resource_expansion", 0.50, 0.6),
     ("mineral resource estimate", "resource estimate", "ni 43-101", "maiden resource",
      "resource update", "resource expansion", "increases resource", "expanded resource")),
    ("drill", ("drill_result", 0.45, 0.6),
     ("drill", "intercept", "intersect", "assay", "g/t", "metres", "meters", " m @",
      "hole ", "step-out", "step out", "infill")),
    ("study", ("catalyst", 0.40, 0.5),
     ("pre-feasibility", "feasibility", "pea", "preliminary economic", "metallurg",
      "recovery", "scoping study", "economic assessment", "test work")),
]
_POS_WORDS = ("high-grade", "high grade", "bonanza", "exceptional", "record", "expands",
              "expansion", "increase", "strong", "exceeds", "beat", "discovery", "significant",
              "robust", "positive", "upgrades")
_NEG_WORDS = ("dilut", "delay", "halt", "loss", "lawsuit", "default", "writedown", "write-down",
              "lowered", "cuts", "disappoint", "shortfall", "going concern", "suspend")
_STAGE_WORDS = {"pea": "PEA", "preliminary economic": "PEA", "pre-feasibility": "PFS",
                "prefeasibility": "PFS", "pfs": "PFS", "feasibility": "DFS", "dfs": "DFS",
                "permitted": "PERMITTED", "construction": "CONSTRUCTION", "production": "PRODUCING"}


def classify_headline(title: str, summary: str = "") -> dict[str, Any]:
    """Best-effort, deterministic mapping of a free-text headline to a catalyst event dict
    {type, impact, magnitude, [share_change_pct|stage_to|p_discovery_delta], grade_gpt?}.
    Keyword rules + a high-grade/grade-number boost + a sentiment tilt. Pure & tested."""
    text = f"{title or ''} {summary or ''}".lower()
    etype, impact, magnitude = "news", 0.05, 0.3
    for _, (t, imp, mag), kws in _RULES:
        if any(k in text for k in kws):
            etype, impact, magnitude = t, imp, mag
            break

    # sentiment tilt
    tilt = 0.12 * sum(1 for w in _POS_WORDS if w in text) - 0.15 * sum(1 for w in _NEG_WORDS if w in text)
    out: dict[str, Any] = {"type": etype, "headline": (title or "").strip()}

    if etype in ("drill_result", "grade_beat", "resource_expansion"):
        m = _GRADE_RE.search(text)
        if m:
            try:
                g = float(m.group(1).replace(",", ""))
            except ValueError:
                g = 0.0
            out["grade_gpt"] = g
            # grade band -> stronger upside for high-grade hits; promote to grade_beat
            boost = 0.85 if g >= 500 else 0.65 if g >= 250 else 0.45 if g >= 120 else 0.30
            impact = max(impact, boost)
            if g >= 250 and etype == "drill_result":
                out["type"] = etype = "grade_beat"
            magnitude = max(magnitude, min(1.0, 0.4 + g / 1000.0))
        out["p_discovery_delta"] = round(min(0.12, max(0.0, impact) * 0.08), 4)
    elif etype == "financing":
        if "bought deal" in text or "bought-deal" in text or "dilut" in text:
            impact = -0.45
        am = _AMOUNT_RE.search(text)
        if am:
            try:
                magnitude = min(1.0, 0.3 + float(am.group(1)) / 40.0)   # bigger raise -> bigger dilution
            except ValueError:
                pass
    elif etype == "permitting":
        for kw, stage in _STAGE_WORDS.items():
            if kw in text:
                out["stage_to"] = stage
                break

    impact = _clamp(impact + (tilt if etype not in ("financing",) else min(0.0, tilt)), -1.0, 1.0)
    out["impact"] = round(impact, 3)
    out["magnitude"] = round(_clamp(magnitude, 0.0, 1.0), 3)
    return out


def match_ticker(text: str, aliases: dict[str, list]) -> Optional[str]:
    """Resolve free text to a ticker via case-insensitive alias/symbol substring match.
    ``aliases`` maps ticker -> [name fragments]. Longest alias wins (most specific)."""
    if not text:
        return None
    t = text.lower()
    best, best_len = None, 0
    for ticker, names in (aliases or {}).items():
        for frag in [ticker] + list(names or []):
            f = str(frag).lower().strip()
            if f and f in t and len(f) > best_len:
                best, best_len = ticker, len(f)
    return best


def _norm_headline(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").lower()).strip()


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate the same story arriving from multiple feeds/sources. Two events collide if they
    share a link OR share (ticker, normalized-headline, date) — so the *same* press release picked
    up by two aggregators under different URLs is still merged. On collision keep the highest-trust
    event (``_trust``), then the most-populated."""
    reps: list[dict[str, Any]] = []
    key_to_gid: dict[Any, int] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        keys = []
        if ev.get("link"):
            keys.append(("link", ev["link"]))
        keys.append(("hd", ev.get("ticker"), _norm_headline(ev.get("headline", "")), ev.get("date")))
        gid = next((key_to_gid[k] for k in keys if k in key_to_gid), None)
        if gid is None:
            gid = len(reps)
            reps.append(ev)
        else:
            cur = reps[gid]
            if (ev.get("_trust", 0), len(ev)) > (cur.get("_trust", 0), len(cur)):
                reps[gid] = ev
        for k in keys:
            key_to_gid[k] = gid
    return reps


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
