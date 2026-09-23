"""
Oil-supply-risk monitor (action-plan P2.4) — let the TAPE price the geopolitics.

Two supply-side conclusions in the book ("oil is glutted, energy royalties have no commodity
tailwind"; the copper supply read) silently depend on the signed Iran–US MOU *holding*. That
assumption must be MONITORED, not assumed — but via OBJECTIVE proxies the market expresses a
breakdown through, never a model of political intent.

EXPLICIT ANTI-PATTERN (do NOT build): an "Israel intent" / "US posture" score. Intent is
unmeasurable; scoring it is false precision that lets a vivid geopolitical tail pull weight it
doesn't deserve. The market prices intent better than any model we could write — so we read the
market, not the diplomacy. **No component here quantifies intent.**

Objective proxies (all from the tape):
  * **price level break** — WTI/Brent through a set threshold (supply risk re-pricing).
  * **OVX spike** — CBOE crude-oil vol index (the options market pricing a fat oil tail).
  * **term-structure flip to BACKWARDATION** — front richer than deferred (the cleanest tell of
    *physical* supply stress / Hormuz fear).
  * **headline flag** — ceasefire-violation / Hormuz keywords: CONTEXT ONLY, human-read, **never
    scored** — it tells you *why* oil moved (supply vs demand), so the trigger isn't misread.

When the price/vol/term-structure conditions fire TOGETHER → raise **"Middle East oil-supply-risk
elevated"** and **arm the energy-royalty breakdown watch (5.4)**. If the MOU/ceasefire holds and oil
stays glutted, the flag stays dormant and the watch stays unarmed.

Pure + dependency-free; thresholds tunable via /confirm (`oil_supply_monitor.*`). No eval().
"""
from __future__ import annotations

from typing import Any, Optional

import monitor_protocol as _mp
from monitor_protocol import num as _num

__all__ = ["DEFAULT_OIL_CONFIG", "OIL_GLOSSARY", "oil_tooltip", "assess"]

DEFAULT_OIL_CONFIG: dict[str, Any] = {
    "wti_break": 85.0,            # WTI through this ($/bbl) is a price-level break
    "brent_break": 90.0,          # Brent through this
    "ovx_spike": 45.0,            # OVX at/above this is an options-market oil-tail spike
    "backwardation_min": 0.50,    # front − deferred ($/bbl) at/above this = meaningful backwardation
    # keyword set for the CONTEXT-ONLY headline flag (never scored)
    "headline_keywords": ["hormuz", "ceasefire", "strait", "tanker", "strike", "houthi",
                          "hezbollah", "iran", "israel", "embargo", "sanction"],
}

OIL_GLOSSARY: dict[str, dict[str, str]] = {
    "oil_supply_monitor": {
        "what": "Oil-supply-risk watch — OBJECTIVE proxies (price break · OVX vol · backwardation) that arm the energy-royalty breakdown watch (5.4) when they fire together. It reads the MARKET, never political intent.",
        "scale": "Dormant (glut assumption holds) → ELEVATED (the three proxies fire together → energy-royalty watch armed).",
        "influence": "When elevated, arms the energy-royalty breakdown candidate set (5.4) — never an auto-buy, and tagged outside the core circle.",
        "edge": "No component scores intent (the anti-pattern). The headline flag is context only, human-read, never scored.",
    },
    "oil_price_break": {
        "what": "WTI/Brent through a set threshold — the market re-pricing supply risk into the level.",
        "scale": "Break = WTI ≥ ~85 or Brent ≥ ~90 (tunable). Below = glut intact.",
        "influence": "One of the three objective proxies that must fire together.",
    },
    "ovx_spike": {
        "what": "OVX — the CBOE crude-oil implied-vol index (the options market pricing a fat oil tail).",
        "scale": "Spike = OVX ≥ ~45 (tunable). Calm = glut / no tail priced.",
        "influence": "The volatility proxy — the options market's read of an oil tail.",
    },
    "oil_backwardation": {
        "what": "Futures term structure flipping to BACKWARDATION (front richer than deferred) — the cleanest tell of PHYSICAL supply stress / Hormuz fear.",
        "scale": "Backwardation = front − deferred ≥ ~$0.50/bbl. Contango (front cheaper) = glut.",
        "influence": "The physical-stress proxy; with a price break and an OVX spike it arms the watch.",
        "edge": "The hardest-to-fake tell — physical buyers paying up for prompt barrels.",
    },
    "oil_headline": {
        "what": "Ceasefire-violation / Hormuz keyword flag — CONTEXT ONLY, human-read, NEVER scored.",
        "scale": "Present = supply-risk keywords in the feed; tells you WHY oil moved (supply vs demand).",
        "influence": "Renders as context beside the objective trigger; it does NOT move the flag or any score.",
    },
}


def oil_tooltip(key: str) -> str:
    return _mp.tooltip(OIL_GLOSSARY, key)


def _cfg(config: Optional[dict]) -> dict:
    return _mp.merged_config(DEFAULT_OIL_CONFIG, config, "oil_supply_monitor")


def _headline_context(headlines: Optional[list], keywords: list) -> dict:
    """Scan headlines for supply-risk keywords — CONTEXT ONLY. Returns matched keywords + the
    triggering headlines; this NEVER feeds the flag or any score (the anti-pattern guard)."""
    hits, matched = [], set()
    for h in (headlines or []):
        s = str(h or "").lower()
        ks = [k for k in keywords if k in s]
        if ks:
            hits.append(str(h))
            matched.update(ks)
    return {"present": bool(hits), "keywords": sorted(matched), "headlines": hits[:5],
            "scored": False, "note": "context only — human-read, never scored (no intent model)"}


def assess(*, wti: Any = None, brent: Any = None, ovx: Any = None,
           front: Any = None, deferred: Any = None, headlines: Optional[list] = None,
           config: Optional[dict] = None, transits: Optional[dict] = None) -> dict:
    """Assess oil-supply risk from objective proxies. ``front``/``deferred`` are nearby vs deferred
    futures prices ($/bbl) for the backwardation read. ``headlines`` is context only. All optional.

    ``transits`` (optional, manual weekly input): ``{'count_7d': int, 'prior_7d': int,
    'weeks_rising': int}`` — Kpler/Bloomberg Strait of Hormuz vessel counts. The DHT thesis
    kill is de-escalation FASTER than the modeled 1yr half-life decay; this sub-read tracks
    the PHYSICAL pace of normalization against that bar. Headlines lie; vessel counts don't.

    ``elevated`` (and the energy-royalty watch arming) requires the price-break and backwardation
    proxies to be ASSESSABLE and ALL assessable proxies to fire together — never a single signal,
    and never anything derived from intent."""
    cfg = _cfg(config)
    w, b = _num(wti), _num(brent)
    ov = _num(ovx)
    f, d = _num(front), _num(deferred)

    # ---- objective proxies ---------------------------------------------------
    price_break = None
    if w is not None or b is not None:
        price_break = bool((w is not None and w >= float(cfg["wti_break"]))
                           or (b is not None and b >= float(cfg["brent_break"])))
    ovx_spike = (ov >= float(cfg["ovx_spike"])) if ov is not None else None
    backwardation = None
    spread = None
    if f is not None and d is not None:
        spread = round(f - d, 3)
        backwardation = spread >= float(cfg["backwardation_min"])

    proxies = {"price_break": price_break, "ovx_spike": ovx_spike, "backwardation": backwardation}
    assessable = {k: v for k, v in proxies.items() if v is not None}
    # core = the two physical tells must be present; then ALL assessable proxies must fire together.
    core_present = price_break is not None and backwardation is not None
    elevated = bool(core_present and assessable and all(assessable.values()))

    headline = _headline_context(headlines, cfg["headline_keywords"])

    # ---- Hormuz physical-transit sub-read (DHT thesis variable) ------------------
    # Manual weekly input: {'count_7d', 'prior_7d', 'weeks_rising'}. The kill is pace:
    # normalization running FASTER than the modeled decay curve. 2x week-over-week for
    # 2 consecutive weeks = the physical pace has broken above gradual de-escalation.
    tr = transits or {}
    t7, p7 = _num(tr.get("count_7d")), _num(tr.get("prior_7d"))
    rising_weeks = int(tr.get("weeks_rising") or 0)
    fast_normalize = bool(t7 is not None and p7 is not None and p7 > 0
                          and t7 > 2.0 * p7 and rising_weeks >= 2)
    if t7 is None:
        transit_read = "transits n/a — stamp weekly Kpler/Bloomberg count in config['hormuz_transits']"
    elif fast_normalize:
        transit_read = ("NORMALIZING FAST — physical pace implies de-escalation faster than "
                        "the modeled decay; DHT thesis under pressure")
    elif p7 is not None and t7 > p7:
        transit_read = "accelerating — watch pace vs decay"
    else:
        transit_read = "trickle — disruption intact"

    flags, events = [], []
    if fast_normalize:
        flags.append({"id": "hormuz_fast_normalize", "active": True, "level": "warn",
                      "text": ("HORMUZ NORMALIZING FAST — vessel counts 2x+ for 2 weeks: "
                               "de-escalation pace exceeds the modeled decay; DHT thesis review")})
        events.append({"type": "hormuz_fast_normalize", "level": "warn",
                       "text": "Hormuz physical transits normalizing faster than modeled decay"})
    if elevated:
        fired = [k for k, v in assessable.items() if v]
        flags.append({"id": "oil_supply_risk", "active": True, "level": "warn",
                      "text": ("MIDDLE EAST OIL-SUPPLY-RISK ELEVATED — "
                               + ", ".join(fired) + " firing together → energy-royalty watch ARMED (5.4)")})
        events.append({"type": "oil_supply_risk", "level": "warn",
                       "text": "Oil-supply-risk elevated: price + vol + term-structure aligned"})

    return {
        "proxies": {
            "price_break": {"active": price_break, "wti": w, "brent": b,
                            "wti_break": cfg["wti_break"], "brent_break": cfg["brent_break"]},
            "ovx_spike": {"active": ovx_spike, "ovx": ov, "threshold": cfg["ovx_spike"]},
            "backwardation": {"active": backwardation, "spread": spread,
                              "min": cfg["backwardation_min"]},
        },
        "elevated": elevated,
        "armed_energy_royalty_watch": elevated,          # arms 5.4; stays False (unarmed) when dormant
        "headline_context": headline,                    # unscored context
        "hormuz_transits": {"count_7d": t7, "prior_7d": p7, "weeks_rising": rising_weeks,
                            "fast_normalize": fast_normalize, "read": transit_read},
        "flags": flags,
        "events": events,
        "glossary": {k: oil_tooltip(k) for k in OIL_GLOSSARY},
        "anti_pattern_note": "no component scores political intent — objective proxies + the tape only",
    }
