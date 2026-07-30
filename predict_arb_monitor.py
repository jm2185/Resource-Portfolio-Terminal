"""
PREDICT arb SENTINEL — scan the Kalshi book (Wealthsimple Predict's source venue) for mispriced
probability, from first principles.

Wealthsimple Predict routes every order to Kalshi, so the contracts a Canadian can trade in
Predict ARE Kalshi's contracts — and Kalshi's public book is the ground truth this monitor sweeps.
Three lanes, honestly labeled (the discipline: with ONE executable venue, "arb" must never be
conflated with "value"):

  L1 STRUCTURAL (riskless if net-positive) — probability-axiom violations inside the book itself:
     * parity        buy YES + buy NO on one market pays $1 in every state
                         profit = 1 − (ask_y + ask_n) − fees
     * partition     a mutually-exclusive, exhaustive outcome set {m₁…mₙ}:
                         buy-all-YES pays $1        → profit = 1 − Σ ask_yᵢ − fees
                         buy-all-NO  pays $(n−1)    → profit = (n−1) − Σ ask_nᵢ − fees
     * ladder        threshold contracts "X > k": k₁ < k₂ implies P(>k₁) ≥ P(>k₂), so
                         bid(>k₂) > ask(>k₁) is a dominance violation:
                         buy YES(>k₁) + buy NO(>k₂) pays ≥ $1 in every state
  L2 VALUE (a bet, NOT arb) — market price vs a supplied first-principles probability p̂
     (options-implied · OIS-implied · nowcast · climatology · operator judgment), edge net of
     fees, binary-Kelly sized, capped. Flags only when the price sits OUTSIDE p̂'s uncertainty
     band — a model that isn't sure never generates a signal.

Friction is FIRST-CLASS: every profit is net of the full WS-side stack (WS commission + clearing
+ Kalshi taker fee ceil(rate·P·(1−P)) + the CAD↔USD corridor on cost in and payout out). The fee
fields are conservative PLACEHOLDERS until Predict launches and real fills calibrate them — if
the honest answer is "the fee stack kills L1", this monitor is built to prove it with numbers.

Pure + dependency-free (stdlib only); never raises on thin input; no eval(). The engine leg
(`engine._predict_worker` / `_fire_predict_arb`) only marshals snapshots; ALL math lives here.
Thresholds tunable via /confirm (`predict_arb_monitor.*`).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import monitor_protocol as _mp
from monitor_protocol import num as _num

__all__ = ["DEFAULT_PREDICT_ARB_CONFIG", "PREDICT_ARB_GLOSSARY", "predict_arb_tooltip",
           "friction_per_contract", "kalshi_fee", "walk_book", "build_constraint_graph",
           "structural_opportunities", "market_board", "value_edges", "kelly_fraction",
           "assess_book", "candidate_orderbook_tickers", "select_fresh"]

DEFAULT_PREDICT_ARB_CONFIG: dict[str, Any] = {
    # -- friction (PLACEHOLDERS until launch — calibrate from the first real Predict fills) --
    "fees": {
        "ws_commission_per_contract": 0.02,   # WS per-contract commission (UNDISCLOSED at launch)
        "clearing_fee_per_contract": 0.00,    # the clearing-agent pass-through (undisclosed)
        "kalshi_fee_rate": 0.07,              # Kalshi taker fee ≈ ceil(0.07·P·(1−P)) per contract
        "kalshi_fee_applies": True,
        "fx_spread_oneway": 0.015,            # CAD↔USD corridor each way (WS Trade precedent ~1.5%)
        "fx_applies": True,                   # False if Predict turns out to hold USD balances
    },
    "theta_struct": 0.01,      # min NET profit per $1 basket to flag an L1 structural arb
    "theta_value": 0.05,       # min NET edge to flag an L2 value signal
    "min_size": 10.0,          # contracts fillable at the flagged prices (top-of-book or walked)
    "kelly_cap": 0.10,         # hard cap on the suggested Kelly fraction (satellite lane, never the barbell)
    "min_days_to_settlement": 0.0,
    "max_days_to_settlement": 180.0,   # ignore far-dated books (dead capital; CIRO floor is 30d+)
    "top_n": 12,               # opportunities surfaced (the rest are counted, not listed)
    # -- the fetch worker's knobs (read by engine._predict_worker, not by the pure math) --
    "series": [],              # [] → kalshi_client.DEFAULT_SERIES (the CIRO-shaped universe)
    "scan_interval_s": 300.0,
    "max_orderbooks": 12,      # depth-validate at most this many candidates per cycle
}

PREDICT_ARB_GLOSSARY: dict[str, dict[str, str]] = {
    "predict_arb": {
        "what": ("PREDICT arb SENTINEL — sweeps the Kalshi book (Wealthsimple Predict's source venue) "
                 "for L1 structural Dutch books (parity / partition / ladder-dominance violations, "
                 "riskless if net-positive) and L2 value edges (market price vs a first-principles "
                 "probability p̂), everything NET of the full WS fee + FX stack."),
        "scale": ("L1 flags at net ≥ ~1¢ per $1 basket; L2 flags at net edge ≥ ~5% AND price outside "
                  "p̂'s uncertainty band. Net ≤ 0 after fees = correctly silent."),
        "influence": ("Alerts only — the scanner NEVER executes; the operator trades in the Predict "
                      "app. L2 entries route through record_decision/record_conviction so the "
                      "flywheel Brier-scores the models."),
        "edge": ("The venue asymmetry: Canadians can't trade Kalshi directly (that's what Predict is), "
                 "but Kalshi's book is public — so the scanner prices the source venue and treats the "
                 "WS leg as a friction model. L1 and L2 are labeled and never conflated."),
    },
}


def predict_arb_tooltip(key: str) -> str:
    return _mp.tooltip(PREDICT_ARB_GLOSSARY, key)


def _cfg(config: Optional[dict]) -> dict:
    return _mp.merged_config(DEFAULT_PREDICT_ARB_CONFIG, config, "predict_arb_monitor")


# ---------------------------------------------------------------------------------------------------
# Friction — the fee stack, per contract and per basket
# ---------------------------------------------------------------------------------------------------

def kalshi_fee(price: Any, cfg: Optional[dict] = None) -> float:
    """Kalshi's taker fee for one contract at ``price``: ceil_to_cent(rate · P · (1−P)). Worst case
    ~1.75¢ at P=0.5 with rate 0.07; verify the live schedule at launch (config: fees.kalshi_fee_rate)."""
    c = _cfg(cfg)["fees"]
    if not c.get("kalshi_fee_applies", True):
        return 0.0
    p = _num(price)
    if p is None or p <= 0.0 or p >= 1.0:
        return 0.0
    rate = float(c.get("kalshi_fee_rate", 0.07))
    return math.ceil(rate * p * (1.0 - p) * 100.0) / 100.0


def friction_per_contract(price: Any, cfg: Optional[dict] = None) -> float:
    """The NON-FX per-contract friction for one leg bought at ``price``: WS commission + clearing
    pass-through + the Kalshi taker fee. FX is basket-level (it scales with cost and payout, not
    per contract) — see ``_basket_net``."""
    c = _cfg(cfg)["fees"]
    return (float(c.get("ws_commission_per_contract", 0.0))
            + float(c.get("clearing_fee_per_contract", 0.0))
            + kalshi_fee(price, cfg))


def _basket_net(cost: float, payout: float, legs_fees: float, cfg: dict) -> float:
    """Net profit of a guaranteed-payout basket per 1-contract unit: convert CAD→USD on the cost
    (pay the corridor going in), USD→CAD on the payout (pay it coming out), minus per-leg fees.
    fx_applies=False (a USD-balance Predict) zeroes the corridor."""
    fees = cfg["fees"]
    fx = float(fees.get("fx_spread_oneway", 0.0)) if fees.get("fx_applies", True) else 0.0
    return payout * (1.0 - fx) - cost * (1.0 + fx) - legs_fees


def walk_book(levels: Any, qty: Any) -> Optional[dict]:
    """Average fill price for BUYING ``qty`` contracts against resting complementary bids.
    ``levels`` = the OPPOSITE side's bids as [(price, size), …] best-first — buying YES consumes NO
    bids at cost 1−p, and vice versa. Returns {avg_cost, filled, exhausted}; None on no book."""
    q = _num(qty)
    lv = [(p, s) for p, s in (levels or []) if _num(p) is not None and _num(s) and s > 0]
    if q is None or q <= 0 or not lv:
        return None
    remaining, spent = q, 0.0
    for p, s in lv:                                # best (highest) bid first = cheapest 1−p first
        take = min(remaining, s)
        spent += take * (1.0 - p)
        remaining -= take
        if remaining <= 0:
            break
    filled = q - remaining
    if filled <= 0:
        return None
    return {"avg_cost": round(spent / filled, 4), "filled": round(filled, 2),
            "exhausted": remaining > 0}


# ---------------------------------------------------------------------------------------------------
# The constraint graph — which probability axioms bind which markets
# ---------------------------------------------------------------------------------------------------

def _days_to_close(close_time: str, now_ts: Any) -> Optional[float]:
    """Days from ``now_ts`` to an ISO-8601 close_time ('2026-09-11T12:29:00Z'). None if unparsable."""
    s = str(close_time or "").strip()
    if not s:
        return None
    try:
        import datetime as _dt
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        now = _num(now_ts)
        if now is None:
            return None
        return (dt.timestamp() - now) / 86400.0
    except (ValueError, OSError, OverflowError):
        return None


def _quoted(m: dict) -> bool:
    return _num(m.get("yes_ask")) is not None and _num(m.get("no_ask")) is not None


def build_constraint_graph(events: Any, *, now_ts: Any = None, config: Optional[dict] = None) -> dict:
    """Classify the snapshot's events into the structures the axioms bind: PARTITIONS (an event
    flagged mutually_exclusive whose legs are all quoted — exactly one resolves YES) and LADDERS
    (≥2 quoted 'greater'-strike markets in one event, sorted by strike — P(>k) must be monotone
    non-increasing in k). Markets outside the settlement window or unquoted are counted, not
    forced. Pure; the graph is data, so the sweep AND the tests read the same structure."""
    cfg = _cfg(config)
    lo, hi = float(cfg["min_days_to_settlement"]), float(cfg["max_days_to_settlement"])
    partitions, ladders = [], []
    n_markets = n_quoted = n_window = 0
    for e in (events or []):
        mkts = [m for m in ((e or {}).get("markets") or []) if m.get("ticker")]
        n_markets += len(mkts)
        live = []
        for m in mkts:
            if str(m.get("status") or "active") not in ("active", "open", ""):
                continue
            d = _days_to_close(m.get("close_time"), now_ts)
            if d is not None and not (lo <= d <= hi):
                continue
            n_window += 1
            if _quoted(m):
                live.append(m)
        n_quoted += len(live)
        if not live:
            continue
        base = {"event_ticker": e.get("event_ticker"), "series_ticker": e.get("series_ticker"),
                "title": e.get("title"), "category": e.get("category")}
        # A partition needs EVERY leg quoted — a Dutch book over a subset of an exhaustive set is
        # not riskless (the missing leg can be the one that resolves YES).
        if e.get("mutually_exclusive") and len(mkts) >= 2 and len(live) == len(mkts):
            partitions.append({**base, "markets": live})
        rungs = [m for m in live if m.get("strike_type") == "greater"
                 and _num(m.get("floor_strike")) is not None]
        if len(rungs) >= 2:
            ladders.append({**base, "markets": sorted(rungs, key=lambda m: m["floor_strike"])})
    return {"partitions": partitions, "ladders": ladders,
            "counts": {"markets": n_markets, "in_window": n_window, "quoted": n_quoted}}


# ---------------------------------------------------------------------------------------------------
# L1 — structural sweeps
# ---------------------------------------------------------------------------------------------------

def _leg(m: dict, side: str) -> dict:
    ask = m.get("yes_ask") if side == "yes" else m.get("no_ask")
    # top-of-book size for BUYING this side = the size resting on the complementary bid
    size = m.get("yes_bid_size") if side == "no" else m.get("yes_ask_size")
    return {"ticker": m.get("ticker"), "side": side, "ask": ask, "size": size,
            "sub": m.get("yes_sub_title") or m.get("title")}


def _basket(kind: str, base: dict, legs: list, payout: float, cfg: dict) -> Optional[dict]:
    """Price a guaranteed-payout basket: gross = payout − Σ ask; net = fx-adjusted minus per-leg
    fees; size cap = the thinnest leg's top-of-book. None if any leg is unpriced."""
    asks = [_num(l["ask"]) for l in legs]
    if any(a is None for a in asks):
        return None
    cost = sum(asks)
    legs_fees = sum(friction_per_contract(a, cfg) for a in asks)
    net = _basket_net(cost, payout, legs_fees, cfg)
    sizes = [_num(l.get("size")) for l in legs]
    size_cap = min([s for s in sizes if s is not None], default=None)
    return {"lane": "L1", "kind": kind, **base,
            "id": f"{kind}:{base.get('event_ticker')}:" + "|".join(str(l['ticker']) for l in legs[:4]),
            "legs": legs, "payout": round(payout, 2), "cost": round(cost, 4),
            "gross": round(payout - cost, 4), "fees": round(legs_fees, 4), "net": round(net, 4),
            "size_cap": size_cap}


def structural_opportunities(graph: dict, *, config: Optional[dict] = None,
                             all_baskets: bool = False) -> list:
    """Sweep the constraint graph for L1 baskets. Default: only those whose NET profit clears
    theta_struct (the actionable set). ``all_baskets=True`` returns EVERY priced basket with an
    ``actionable`` flag — the near-miss evidence a clean verdict needs to show its work."""
    cfg = _cfg(config)
    theta, min_size = float(cfg["theta_struct"]), float(cfg["min_size"])
    out: list = []

    def _push(opp: Optional[dict]) -> None:
        if opp and (all_baskets or opp["net"] >= theta):
            opp["actionable"] = opp["net"] >= theta
            opp["depth_ok"] = (opp["size_cap"] is None) or (opp["size_cap"] >= min_size)
            out.append(opp)

    for part in (graph or {}).get("partitions") or []:
        mkts = part["markets"]
        base = {k: part.get(k) for k in ("event_ticker", "series_ticker", "title", "category")}
        _push(_basket("partition_yes", base, [_leg(m, "yes") for m in mkts], 1.0, cfg))
        _push(_basket("partition_no", base, [_leg(m, "no") for m in mkts], float(len(mkts) - 1), cfg))
    for lad in (graph or {}).get("ladders") or []:
        mkts = lad["markets"]                       # sorted by strike ascending
        base = {k: lad.get(k) for k in ("event_ticker", "series_ticker", "title", "category")}
        for m in mkts:                              # parity check rides the ladder pass (any market)
            _push(_basket("parity", base, [_leg(m, "yes"), _leg(m, "no")], 1.0, cfg))
        for i in range(len(mkts)):
            for j in range(i + 1, len(mkts)):       # YES(>k_lo) + NO(>k_hi) pays ≥ $1 always
                lo, hi_m = mkts[i], mkts[j]
                opp = _basket("ladder", base, [_leg(lo, "yes"), _leg(hi_m, "no")], 1.0, cfg)
                if opp:
                    opp["strikes"] = [lo.get("floor_strike"), hi_m.get("floor_strike")]
                _push(opp)
    out.sort(key=lambda o: -o["net"])
    return out


def market_board(events: Any, *, top: int = 12, now_ts: Any = None,
                 config: Optional[dict] = None) -> list:
    """The most ACTIVE quoted contracts in the swept universe (24h volume, then open interest) —
    the desk's standing 'what's trading' board, so a clean sweep still shows the live landscape
    the scanner examined instead of an empty screen. Pure."""
    cfg = _cfg(config)
    lo, hi = float(cfg["min_days_to_settlement"]), float(cfg["max_days_to_settlement"])
    rows: list = []
    for e in (events or []):
        for m in ((e or {}).get("markets") or []):
            if not m.get("ticker") or not _quoted(m):
                continue
            d = _days_to_close(m.get("close_time"), now_ts)
            if d is not None and not (lo <= d <= hi):
                continue
            rows.append({"ticker": m.get("ticker"), "event_ticker": m.get("event_ticker"),
                         "sub": m.get("yes_sub_title") or m.get("title"),
                         "category": (e or {}).get("category"),
                         "yes_bid": m.get("yes_bid"), "yes_ask": m.get("yes_ask"),
                         "days_to_close": round(d, 1) if d is not None else None,
                         "volume_24h": m.get("volume_24h"),
                         "open_interest": m.get("open_interest")})
    rows.sort(key=lambda r: (-(_num(r.get("volume_24h")) or 0.0),
                             -(_num(r.get("open_interest")) or 0.0)))
    return rows[: max(1, int(top))]


# ---------------------------------------------------------------------------------------------------
# L2 — model-vs-market value edges (a bet, never called arb)
# ---------------------------------------------------------------------------------------------------

def kelly_fraction(p_hat: Any, cost: Any, *, cap: float = 0.10) -> Optional[float]:
    """Binary Kelly for buying a $1-settling contract at effective ``cost``:
    f* = (p̂ − c) / (1 − c), floored at 0 and hard-capped (this is a satellite lane)."""
    p, c = _num(p_hat), _num(cost)
    if p is None or c is None or not (0.0 < c < 1.0):
        return None
    return round(min(max((p - c) / (1.0 - c), 0.0), float(cap)), 4)


def value_edges(events: Any, fair_values: Any, *, now_ts: Any = None,
                config: Optional[dict] = None) -> list:
    """Compare each quoted market against a supplied first-principles probability
    ``fair_values = {market_ticker: {p_hat, band: [lo, hi], source, as_of}}``. A signal needs BOTH
    net edge ≥ theta_value AND the executable price OUTSIDE the band (an uncertain model stays
    silent). Side: p̂ > price → buy YES at yes_ask; p̂ < price → buy NO at no_ask."""
    cfg = _cfg(config)
    theta, cap = float(cfg["theta_value"]), float(cfg["kelly_cap"])
    fv = fair_values or {}
    if not fv:
        return []
    fees = cfg["fees"]
    fx = float(fees.get("fx_spread_oneway", 0.0)) if fees.get("fx_applies", True) else 0.0
    lo_d, hi_d = float(cfg["min_days_to_settlement"]), float(cfg["max_days_to_settlement"])
    out = []
    for e in (events or []):
        for m in ((e or {}).get("markets") or []):
            f = fv.get(m.get("ticker"))
            if not isinstance(f, dict):
                continue
            p_hat = _num(f.get("p_hat"))
            if p_hat is None or not (0.0 <= p_hat <= 1.0) or not _quoted(m):
                continue
            d = _days_to_close(m.get("close_time"), now_ts)
            if d is not None and not (lo_d <= d <= hi_d):
                continue
            band = f.get("band") if isinstance(f.get("band"), (list, tuple)) else None
            for side, ask, p_win in (("yes", _num(m.get("yes_ask")), p_hat),
                                     ("no", _num(m.get("no_ask")), 1.0 - p_hat)):
                if ask is None or not (0.0 < ask < 1.0):
                    continue
                # effective cost of the leg incl. per-contract fees + the FX corridor both ways
                eff_cost = (ask * (1.0 + fx) + friction_per_contract(ask, cfg)) / max(1e-9, 1.0 - fx)
                edge = p_win - eff_cost
                if edge < theta:
                    continue
                if band and len(band) == 2:        # price inside the model's own band → no signal
                    b_lo, b_hi = _num(band[0]), _num(band[1])
                    px_prob = ask if side == "yes" else 1.0 - ask
                    if b_lo is not None and b_hi is not None and b_lo <= px_prob <= b_hi:
                        continue
                out.append({
                    "lane": "L2", "kind": "value", "id": f"value:{m.get('ticker')}:{side}",
                    "event_ticker": m.get("event_ticker"), "ticker": m.get("ticker"),
                    "title": m.get("title"), "side": side, "ask": ask,
                    "p_hat": round(p_hat, 4), "band": band, "source": f.get("source"),
                    "as_of": f.get("as_of"), "eff_cost": round(eff_cost, 4),
                    "net": round(edge, 4),
                    "kelly": kelly_fraction(p_win, eff_cost, cap=cap),
                    "size_cap": _num(m.get("yes_bid_size") if side == "no" else m.get("yes_ask_size")),
                })
    out.sort(key=lambda o: -o["net"])
    return out


# ---------------------------------------------------------------------------------------------------
# Book-level orchestration + firing
# ---------------------------------------------------------------------------------------------------

def candidate_orderbook_tickers(snapshot: Any, *, config: Optional[dict] = None) -> list:
    """Stage-1 output for the two-stage fetch: the market tickers involved in top-of-book L1
    candidates, so the worker depth-validates ONLY what looks mispriced (rate-friendly)."""
    cfg = _cfg(config)
    snap = snapshot or {}
    graph = build_constraint_graph(snap.get("events"), now_ts=snap.get("ts"), config=cfg)
    tks: list = []
    for opp in structural_opportunities(graph, config=cfg):
        for l in opp.get("legs") or []:
            if l.get("ticker") and l["ticker"] not in tks:
                tks.append(l["ticker"])
    return tks[: int(cfg.get("max_orderbooks", 12))]


def _depth_validate(opp: dict, books: dict, cfg: dict) -> dict:
    """Re-cost an L1 basket against real depth for min_size contracts (buying a side consumes the
    complementary side's bids). Books missing → the top-of-book numbers stand, stamped unvalidated."""
    min_size = float(cfg["min_size"])
    walked, ok = [], True
    for l in opp.get("legs") or []:
        book = (books or {}).get(l.get("ticker"))
        if not book:
            return {**opp, "depth_validated": False}
        counter = book.get("no") if l["side"] == "yes" else book.get("yes")
        w = walk_book(counter, min_size)
        if w is None or w["exhausted"]:
            ok = False
            break
        walked.append(w["avg_cost"])
    if not ok:
        return {**opp, "depth_validated": True, "depth_ok": False, "net_at_size": None}
    cost = sum(walked)
    legs_fees = sum(friction_per_contract(c, cfg) for c in walked)
    net = _basket_net(cost, float(opp.get("payout") or 1.0), legs_fees, cfg)
    return {**opp, "depth_validated": True, "depth_ok": net >= float(cfg["theta_struct"]),
            "net_at_size": round(net, 4)}


def assess_book(snapshot: Any, *, fair_values: Any = None, config: Optional[dict] = None) -> dict:
    """One full sweep over a snapshot (kalshi_client.build_snapshot shape): constraint graph →
    L1 structural + L2 value, ranked by net, with honest coverage counts and monitor-protocol
    flags for the engine's _fire pass. Empty/thin snapshot ⇒ available=False, never a raise."""
    cfg = _cfg(config)
    snap = snapshot or {}
    events = snap.get("events") or []
    if not events:
        return {"available": False, "as_of": snap.get("ts"), "opportunities": [], "flags": [],
                "universe": {"events": 0, "markets": 0, "quoted": 0, "series": snap.get("series") or []},
                "errors": snap.get("errors") or [],
                "summary": "PREDICT scanner: no snapshot yet (worker warming up or feed unreachable)",
                "glossary": {k: predict_arb_tooltip(k) for k in PREDICT_ARB_GLOSSARY}}
    graph = build_constraint_graph(events, now_ts=snap.get("ts"), config=cfg)
    all_l1 = structural_opportunities(graph, config=cfg, all_baskets=True)
    l1 = [_depth_validate(o, snap.get("orderbooks") or {}, cfg)
          for o in all_l1 if o.get("actionable")]
    # The near-miss evidence: the tightest non-actionable baskets (junk beyond −25¢ omitted,
    # ONE best basket per kind+event so six variants of the same ladder don't drown the list) so
    # a clean verdict can SHOW ITS WORK — what came closest and exactly what ate it.
    near_misses, _seen_nm = [], set()
    for o in all_l1:
        if o.get("actionable") or o["net"] <= -0.25:
            continue
        k = (o["kind"], o.get("event_ticker"))
        if k in _seen_nm:
            continue
        _seen_nm.add(k)
        near_misses.append(o)
        if len(near_misses) >= 6:
            break
    l2 = value_edges(events, fair_values, now_ts=snap.get("ts"), config=cfg)
    opps = [o for o in l1 if o.get("depth_ok", True)] + l2
    opps.sort(key=lambda o: -(_num(o.get("net")) or 0.0))
    top = opps[: int(cfg["top_n"])]

    flags = []
    for o in top:
        if o["lane"] == "L1":
            txt = (f"L1 {o['kind']} on {o['event_ticker']}: net {o['net'] * 100:+.1f}¢/$1 basket "
                   f"({len(o.get('legs') or [])} legs, size≤{o.get('size_cap') or '?'}) — riskless if filled; "
                   f"execute in Predict, legs: "
                   + ", ".join(f"{l['side'].upper()} {l['ticker']}@{l['ask']}" for l in (o.get("legs") or [])[:4]))
            level = "good"
        else:
            txt = (f"L2 value on {o['ticker']}: p̂={o['p_hat']:.2f} ({o.get('source') or 'model'}) vs "
                   f"{o['side'].upper()}@{o['ask']:.2f} → net edge {o['net'] * 100:+.1f}%, "
                   f"Kelly≤{o.get('kelly')} — a BET, not arb; route through record_decision")
            level = "info"
        flags.append({"id": o["id"], "lane": o["lane"], "kind": o["kind"], "level": level,
                      "event_ticker": o.get("event_ticker"), "net": o["net"], "text": txt})

    n_l1 = sum(1 for o in top if o["lane"] == "L1")
    counts = graph["counts"]
    if top:
        summary = (f"PREDICT sweep: {len(events)} events / {counts['markets']} markets "
                   f"({counts['quoted']} quoted in window) → {n_l1} structural + "
                   f"{len(top) - n_l1} value signal(s) net of fees")
    else:
        summary = (f"PREDICT sweep: {len(events)} events / {counts['markets']} markets "
                   f"({counts['quoted']} quoted in window) → clean (no net-positive mispricing; "
                   f"fees model: WS {cfg['fees']['ws_commission_per_contract']:.2f} + "
                   f"FX {cfg['fees']['fx_spread_oneway'] * 100:.1f}%/way)")
        if near_misses:                            # the reasoning: what came closest, what ate it
            nm = near_misses[0]
            costs = (nm["gross"] - nm["net"]) * 100.0
            summary += (f" — closest: {nm['kind']} {nm['event_ticker']} gross "
                        f"{nm['gross'] * 100:+.1f}¢, costs eat {costs:.1f}¢ → net "
                        f"{nm['net'] * 100:+.1f}¢")
    return {"available": True, "as_of": snap.get("ts"),
            "universe": {"events": len(events), "markets": counts["markets"],
                         "quoted": counts["quoted"], "in_window": counts["in_window"],
                         "partitions": len(graph["partitions"]), "ladders": len(graph["ladders"]),
                         "series": snap.get("series") or []},
            "opportunities": top, "n_found": len(opps), "flags": flags,
            "near_misses": near_misses,
            "board": market_board(events, now_ts=snap.get("ts"), config=cfg),
            "thresholds": {"theta_struct": float(cfg["theta_struct"]),
                           "theta_value": float(cfg["theta_value"])},
            "fees_model": cfg["fees"], "errors": snap.get("errors") or [],
            "summary": summary,
            "glossary": {k: predict_arb_tooltip(k) for k in PREDICT_ARB_GLOSSARY},
            "note": "alerts only — the scanner never executes; L1 is riskless-if-filled, L2 is a bet"}


def select_fresh(flagged: Any, fired: Optional[dict] = None, *, today: str = "") -> tuple:
    """Dedup the firing: one alert per opportunity per day, keyed on the basket id, RE-firing the
    same day only when the net improves ≥ 1¢ (a widening arb is new information; an unchanged one
    is noise). The loop is monitor_protocol.select_fresh; only these semantics live here."""
    def _state(r: dict) -> dict:
        return {"net": round(_num(r.get("net")) or 0.0, 4)}

    return _mp.select_fresh(flagged, fired, today=today, ticker_field="id", state_fn=_state,
                            is_repeat=lambda prev, st: (st["net"] - (_num(prev.get("net")) or 0.0)) < 0.01)
