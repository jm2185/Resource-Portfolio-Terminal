"""
Rates monitor (action-plan P2.1) — the bear-steepener / fiscal-dominance UPSTREAM tell.

The leading indicator that precedes metals moves: **the long end rising while the Fed holds or
eases the front end.** This is *upstream of* the metals book — it fires weeks/months before
silver/gold respond — so it is framed as a regime signal that feeds scenario weights (P3), never as
a name-level score.

What it tracks (straight-to-source levels; the engine supplies them from FRED / TreasuryDirect):
  * **2s10s** = DGS10 − DGS2 and **5s30s** = DGS30 − DGS5 — the curve spreads.
  * **30Y vs Fed funds** = DGS30 − FEDFUNDS — the term premium the long end demands over policy.
  * **MOVE** — bond-market implied vol; spikes are timeline events.
  * **Treasury auction quality** — tails (stop-vs-when-issued), bid-to-cover; weak auctions are events.

The discrete read:
  * a **"bear-steepener active"** flag — long end rises over the window while the funds rate is
    static/falling (the fiscal-dominance signature, NOT a bull-steepener where the FRONT falls).
  * a composite **"fiscal-dominance pressure"** score (0–100) + label, blended from the steepener,
    the 30Y-funds term premium, the MOVE level, and recent auction stress.
  * **timeline events** for MOVE spikes and auction tails.

Pure + dependency-free (stdlib only) so it is unit-testable; the engine does the live wiring. Every
threshold is a reasoned FIRST CALIBRATION, tunable via the propose/confirm gate (config
``rates_monitor.*``) — not backtested, don't trust blindly. No eval(); robust to missing inputs.
"""
from __future__ import annotations

import time
from typing import Any, Optional

__all__ = [
    "DEFAULT_RATES_CONFIG",
    "RATES_GLOSSARY",
    "rates_tooltip",
    "assess",
]

# --------------------------------------------------------------------------- #
#  Reasoned first calibration — every value tunable via config['rates_monitor'][key] (/confirm).
# --------------------------------------------------------------------------- #
DEFAULT_RATES_CONFIG: dict[str, Any] = {
    # bear-steepener detection (changes measured over the caller's lookback window)
    "long_rise_bps": 20.0,        # the long end (30Y, 10Y fallback) must rise >= this over the window
    "front_static_bps": 5.0,      # ...while the front end (funds, 2Y fallback) is <= this (static/easing)
    # composite "fiscal-dominance pressure" bands + weights
    "term_premium_band": [0.0, 2.5],   # 30Y−funds spread mapped 0..1 across this (pp); high = fiscal pressure
    "move_band": [80.0, 160.0],        # MOVE mapped 0..1 across this band
    "move_spike_level": 120.0,         # MOVE at/above this is a spike event
    "move_spike_jump_bps": 15.0,       # ...or a jump of this many points over the window
    "auction_tail_bps": 1.0,           # a stop >= this many bps above when-issued is a "tail" (weak)
    "auction_weak_btc": 2.20,          # ...or bid-to-cover <= this is a soft auction
    "fiscal_weights": {"steepener": 0.35, "term_premium": 0.25, "move": 0.20, "auction": 0.20},
    "fiscal_bands": [                  # composite score -> label
        [70.0, "ACUTE"], [45.0, "ELEVATED"], [20.0, "BUILDING"], [0.0, "DORMANT"],
    ],
}


# --------------------------------------------------------------------------- #
#  Educational glossary (the "?" tooltip source, mirroring asymmetry_rating.ASYMMETRY_GLOSSARY).
# --------------------------------------------------------------------------- #
RATES_GLOSSARY: dict[str, dict[str, str]] = {
    "rates_monitor": {
        "what": "The bear-steepener / fiscal-dominance rates tell — the UPSTREAM leading indicator for the metals thesis (long end rising while the Fed holds/eases the front).",
        "scale": "Fiscal-dominance pressure 0–100: DORMANT <20 · BUILDING 20–45 · ELEVATED 45–70 · ACUTE >70.",
        "influence": "Upstream of the book: it feeds scenario weights (a firing bear-steepener raises the disorderly-fiscal-dominance scenario), never a name-level score.",
        "edge": "It fires WEEKS/MONTHS before silver/gold respond — read it early, not as confirmation.",
    },
    "bear_steepener": {
        "what": "Long-end yields RISING while the policy/front rate is static or falling — the fiscal-dominance signature (the market demanding term premium the Fed won't fight).",
        "scale": "Active = Δlong ≥ +20bps over the window AND Δfront ≤ +5bps. NOT a bull-steepener (front falling, long anchored) — that's easing, not fiscal stress.",
        "influence": "The dominant term in the fiscal-dominance composite, and the discrete flag the panel raises.",
        "edge": "Distinct from a flattening/inversion: here the 5s30s and 2s10s STEEPEN because the long end leads.",
    },
    "twos_tens": {
        "what": "2s10s = DGS10 − DGS2 — the classic curve spread.",
        "scale": "Negative = inverted (late-cycle/recession signal); rising/positive = steepening.",
        "influence": "Steepening driven by the long end (not the front falling) corroborates the bear-steepener.",
    },
    "fives_thirties": {
        "what": "5s30s = DGS30 − DGS5 — the long-end curve spread, the cleanest read of term-premium re-pricing.",
        "scale": "Rising = the long end re-pricing higher term premium (fiscal-dominance tell).",
        "influence": "A steepening 5s30s with a static front is the core bear-steepener shape.",
    },
    "thirty_funds": {
        "what": "30Y − Fed funds — how far the long end sits above the policy rate.",
        "scale": "Wide/widening = the market demands term premium over policy (fiscal pressure); near zero/negative = policy still dominates the curve.",
        "influence": "The term-premium term of the fiscal-dominance composite.",
    },
    "move": {
        "what": "MOVE index — bond-market implied volatility (the 'VIX of Treasuries').",
        "scale": "Calm <90 · stressed >120. A spike flags Treasury-market stress / fat-tail repricing.",
        "influence": "A composite term; spikes log as timeline events.",
    },
    "auction_tail": {
        "what": "Treasury auction tail — the stop yield printing ABOVE the when-issued (pre-auction) level, i.e. weak demand; read with bid-to-cover.",
        "scale": "A tail ≥ ~1bp or bid-to-cover ≤ ~2.2 is a soft auction — buyers demanding concession.",
        "influence": "Recent tails lift the auction term of the composite and log as timeline events.",
        "edge": "Repeated tails are the cleanest hard-data sign the long end is struggling to clear — fiscal-dominance made visible.",
    },
}


def rates_tooltip(key: str) -> str:
    """Flatten one glossary entry to a multi-line tooltip string (mirrors asymmetry_rating.tooltip_text)."""
    e = RATES_GLOSSARY.get(key)
    if not e:
        return ""
    order = ("what", "scale", "influence", "edge")
    labels = {"what": "", "scale": "Good vs bad: ", "influence": "Drives: ", "edge": "Note: "}
    return "\n".join(labels[k] + e[k] for k in order if e.get(k))


# --------------------------------------------------------------------------- #
#  Small numeric helpers (no third-party deps).
# --------------------------------------------------------------------------- #
def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _band01(x: Optional[float], lo: float, hi: float) -> Optional[float]:
    if x is None:
        return None
    return _clamp((x - lo) / max(1e-9, hi - lo))


def _cfg(config: Optional[dict]) -> dict:
    """Shallow-merge a caller ``rates_monitor`` block over the defaults (one level deep)."""
    cfg = dict(DEFAULT_RATES_CONFIG)
    block = (config or {}).get("rates_monitor", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- #
#  The assessment
# --------------------------------------------------------------------------- #
def _spreads(cur: dict) -> dict:
    d2, d5 = _num(cur.get("dgs2")), _num(cur.get("dgs5"))
    d10, d30 = _num(cur.get("dgs10")), _num(cur.get("dgs30"))
    ff = _num(cur.get("fedfunds"))
    out: dict[str, Any] = {}
    out["2s10s"] = round(d10 - d2, 3) if (d10 is not None and d2 is not None) else None
    out["5s30s"] = round(d30 - d5, 3) if (d30 is not None and d5 is not None) else None
    out["30y_funds"] = round(d30 - ff, 3) if (d30 is not None and ff is not None) else None
    return out


def _change_bps(cur: dict, prior: dict, *primary_then_fallback: str) -> Optional[float]:
    """Δ (in bps) of the first key present in BOTH cur and prior — long end uses dgs30→dgs10, the
    front uses fedfunds→dgs2, so a missing series degrades gracefully to the next-best proxy."""
    for k in primary_then_fallback:
        a, b = _num(cur.get(k)), _num((prior or {}).get(k))
        if a is not None and b is not None:
            return round((a - b) * 100.0, 1)            # rate levels are in %, so ×100 -> bps
    return None


def assess(current: Optional[dict], *, prior: Optional[dict] = None, move: Any = None,
           move_prior: Any = None, auctions: Optional[list] = None,
           config: Optional[dict] = None, now: Optional[str] = None) -> dict:
    """Assess the rates regime from live LEVELS + a lookback ``prior`` snapshot.

    ``current`` / ``prior``: {dgs2, dgs5, dgs10, dgs30, fedfunds} rate levels in PERCENT (prior is the
    same series one window ago — needed to detect "the long end rising over a window"). ``move`` /
    ``move_prior``: the MOVE index now / one window ago. ``auctions``: recent results, each
    {tenor, tail_bps, bid_to_cover, date?}. All inputs optional/graceful — missing data degrades to
    the next-best proxy or drops the term, never fabricates.

    Returns spreads, the window changes, the bear-steepener flag, the MOVE read, parsed auctions, the
    fiscal-dominance composite, a flags list, and a timeline events list.
    """
    cfg = _cfg(config)
    cur = current or {}
    ts = now or _now_iso()
    spreads = _spreads(cur)
    events: list[dict] = []
    flags: list[dict] = []

    # ---- window changes (bps) -------------------------------------------------
    d_long = _change_bps(cur, prior or {}, "dgs30", "dgs10")
    d_front = _change_bps(cur, prior or {}, "fedfunds", "dgs2")
    d_2s10s = None
    d_5s30s = None
    if prior:
        ps = _spreads(prior)
        if spreads.get("2s10s") is not None and ps.get("2s10s") is not None:
            d_2s10s = round((spreads["2s10s"] - ps["2s10s"]) * 100.0, 1)
        if spreads.get("5s30s") is not None and ps.get("5s30s") is not None:
            d_5s30s = round((spreads["5s30s"] - ps["5s30s"]) * 100.0, 1)

    # ---- bear-steepener flag --------------------------------------------------
    long_thr = float(cfg["long_rise_bps"])
    front_thr = float(cfg["front_static_bps"])
    bs_active = bool(d_long is not None and d_front is not None
                     and d_long >= long_thr and d_front <= front_thr)
    bs_assessable = d_long is not None and d_front is not None
    if bs_active:
        note = (f"long end +{d_long:.0f}bps while front {d_front:+.0f}bps (static/easing) — "
                f"market demanding term premium the Fed isn't fighting")
        flags.append({"id": "bear_steepener", "active": True, "level": "warn",
                      "text": f"BEAR-STEEPENER ACTIVE — {note}"})
        events.append({"ts": ts, "type": "bear_steepener", "level": "warn",
                       "text": f"Bear-steepener fired: long {d_long:+.0f}bps / front {d_front:+.0f}bps"})
    bear_steepener = {
        "active": bs_active, "assessable": bs_assessable,
        "long_rise_bps": d_long, "front_change_bps": d_front,
        "d_2s10s_bps": d_2s10s, "d_5s30s_bps": d_5s30s,
        "note": ("not assessable — need a prior-window snapshot of the long & front" if not bs_assessable
                 else ("active" if bs_active else "dormant")),
    }

    # ---- MOVE -----------------------------------------------------------------
    mv = _num(move)
    mv_prior = _num(move_prior)
    spike_level = float(cfg["move_spike_level"])
    spike_jump = float(cfg["move_spike_jump_bps"])
    move_jump = (round(mv - mv_prior, 1) if (mv is not None and mv_prior is not None) else None)
    move_spike = bool(mv is not None and (mv >= spike_level
                      or (move_jump is not None and move_jump >= spike_jump)))
    if move_spike:
        why = (f"MOVE {mv:.0f} ≥ {spike_level:.0f}" if mv >= spike_level
               else f"MOVE jumped +{move_jump:.0f} over the window")
        flags.append({"id": "move_spike", "active": True, "level": "warn",
                      "text": f"MOVE SPIKE — {why} (bond-market stress)"})
        events.append({"ts": ts, "type": "move_spike", "level": "warn", "text": f"MOVE spike: {why}"})
    move_read = {"value": mv, "spike": move_spike, "jump": move_jump,
                 "note": (None if mv is None else ("spike" if move_spike else "calm/contained"))}

    # ---- auctions -------------------------------------------------------------
    tail_thr = float(cfg["auction_tail_bps"])
    btc_thr = float(cfg["auction_weak_btc"])
    parsed_auctions = []
    for a in (auctions or []):
        tail = _num(a.get("tail_bps"))
        btc = _num(a.get("bid_to_cover"))
        weak = bool((tail is not None and tail >= tail_thr) or (btc is not None and btc <= btc_thr))
        rec = {"tenor": a.get("tenor"), "date": a.get("date"), "tail_bps": tail,
               "bid_to_cover": btc, "weak": weak}
        parsed_auctions.append(rec)
        if weak:
            why = []
            if tail is not None and tail >= tail_thr:
                why.append(f"tail {tail:+.1f}bps")
            if btc is not None and btc <= btc_thr:
                why.append(f"b/c {btc:.2f}")
            events.append({"ts": a.get("date") or ts, "type": "auction_tail", "level": "warn",
                           "text": f"Soft {a.get('tenor', 'UST')} auction: {', '.join(why)}"})
    any_weak_auction = any(r["weak"] for r in parsed_auctions)

    # ---- fiscal-dominance composite (0..100) ----------------------------------
    w = cfg["fiscal_weights"]
    tp_lo, tp_hi = cfg["term_premium_band"]
    mv_lo, mv_hi = cfg["move_band"]
    terms, used = [], []
    steep_term = 1.0 if bs_active else (
        # partial credit when the long is outrunning the front but below the hard threshold
        _clamp((d_long - d_front) / max(1e-9, long_thr)) if (d_long is not None and d_front is not None) else None)
    if steep_term is not None:
        terms.append((w["steepener"], steep_term)); used.append("steepener")
    tp_term = _band01(spreads.get("30y_funds"), tp_lo, tp_hi)
    if tp_term is not None:
        terms.append((w["term_premium"], tp_term)); used.append("term_premium")
    mv_term = _band01(mv, mv_lo, mv_hi)
    if mv_term is not None:
        terms.append((w["move"], mv_term)); used.append("move")
    if parsed_auctions:
        terms.append((w["auction"], 1.0 if any_weak_auction else 0.0)); used.append("auction")
    wsum = sum(wt for wt, _ in terms)
    score = (100.0 * sum(wt * v for wt, v in terms) / wsum) if wsum > 0 else None
    label = None
    if score is not None:
        for thr, lab in cfg["fiscal_bands"]:
            if score >= thr:
                label = lab
                break
    fiscal = {"score": (round(score, 1) if score is not None else None), "label": label,
              "drivers": used,
              "note": "upstream of the metals book — fires weeks/months before silver/gold respond"}

    return {
        "as_of": ts,
        "spreads": spreads,
        "bear_steepener": bear_steepener,
        "move": move_read,
        "auctions": parsed_auctions,
        "fiscal_dominance": fiscal,
        "flags": flags,
        "events": events,
        "glossary": {k: rates_tooltip(k) for k in RATES_GLOSSARY},
        "upstream_note": "UPSTREAM of the metals book — a leading regime tell, not a name-level score.",
    }
