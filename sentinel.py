"""
The Sentinel — the book that watches itself (Forge M3, the crown jewel).

For each held name the Sentinel performs a scheduled DIFF of the live engine state against the frozen
thesis, and computes four things — all from the engine's numbers, never re-priced here:

  1. **Liquidity-runway** — the disciplined replacement for the mechanical ADV cap. NOT "no cap": the
     60% structural ceiling stays (Build Spec non-negotiable #1). This is an *additional* gate that
     can only ever TIGHTEN — a position may sit above the soft size band only if it can be liquidated
     inside ``LIQ_RUNWAY_MAX`` days at a tape-respecting participation, with volume stressed down in
     the tails (ES95). Missing ADV ⇒ no exception (fail-safe), never a loosening.
  2. **Financing-window / reflexivity** (the Soros leg, on-thesis for juniors) — is the name in a
     position to raise capital cheaply (above its last placement, above the floor, near 52-wk highs,
     dilution sieve clean)? Plus the **death-spiral** flag: below floor + short runway + sieve failing
     ⇒ forced-dilution risk that impairs the thesis.
  3. **Thesis-integrity %** — of the load-bearing ``claims[]``, how many still hold against live
     metrics? A drop below ``INTEGRITY_FLOOR`` is a flag. Manual claims only the operator flips.
  4. **Pre-commitment rules** — each ``rules[]`` trigger evaluated through the SAFE grammar (M2); a
     fired rule becomes an alert (and, for a trim/exit, a PROPOSAL — the Sentinel auto-acts on alerts
     only, never on exits; Build Spec Open-Decision #5). Alerts are deduped + acknowledgeable.

This module is a PURE consumer (like council.py): it takes resolved inputs + a small calendar-derived
context and returns a structured status. The MCP ``sentinel_sweep`` does the wiring (reads /state,
research_cache, the calendar). Every formula has a hand-checked fixture in test_sentinel.py — the
ES95 unit reconciliation especially (state stores a negative PERCENT; the math wants a fraction).

Pure stdlib. Every coefficient is a REASONED FIRST CALIBRATION for a concentrated, thin-liquidity
junior/multi-commodity book, tunable via the propose/confirm gate (see ``forge.sentinel`` in config).
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Optional

import trigger_grammar as tg

# ---- reasoned first calibration (tunable via forge.sentinel.* through propose/confirm) -------------
LIQ_FREE = 0.05            # ES95 magnitude you treat as "free" before stressing volume (fraction)
LIQ_K = 1.0               # how hard tail-ES throttles liquidatable volume
LIQ_PART = 0.20           # max share of ADV you'll take without moving the tape (a junior-thin book)
LIQ_RUNWAY_MAX = 5.0      # days to clear 90% of the position — the size-band exception gate
STRESS_FLOOR = 0.25       # volume never assumed to dry up past this even in the worst tail
# reflexivity / financing-window weights (renormalized over whatever terms are available)
W_PREM = 0.30             # premium to last placement — the directest reflexivity signal
W_FLOORHEAD = 0.20        # headroom above the REP floor — can they raise at all
W_PCT52 = 0.30            # 52-wk percentile — near highs ⇒ window open
W_DILUTION = 0.20         # dilution sieve clean
WINDOW_OPEN_THRESHOLD = 0.50
INTEGRITY_FLOOR = 0.60     # thesis-integrity below this ⇒ flag
DILUTION_SIEVE_QOQ = 0.02  # >= 2% QoQ dilution fails the sieve (engine glossary)
DEATHSPIRAL_RUNWAY_MONTHS = 6.0
_COMPARATORS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
                ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def _cfg(config: Optional[dict], key: str, default):
    """Read a tunable from ``config['forge']['sentinel'][key]`` with a module-constant fallback."""
    try:
        v = (((config or {}).get("forge") or {}).get("sentinel") or {}).get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _sat(x: float) -> float:
    """Squash a signed ratio (e.g. +30% premium, -10% discount) into [0,1]; 0 → 0.5."""
    return 0.5 * (1.0 + math.tanh(x))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- liquidity runway
def liquidity_runway(adv90: Any, es95_pct: Any, pos_shares: Any, *,
                     config: Optional[dict] = None) -> dict:
    """Days to liquidate 50% / 90% of a position at a stressed participation rate.

    ⚠ ``es95_pct`` is the engine's ``portfolio_stats.expected_shortfall_95`` — a NEGATIVE PERCENT
    (e.g. ``-4.5`` = −4.5%). We divide by 100 to the fraction the formula is written in (STATE_FIELDS
    §2). Volume dries up in tails: ``stress = clamp(1 − k·max(0, −es95_frac − free), STRESS_FLOOR, 1)``.
    """
    adv = _num(adv90)
    shares = _num(pos_shares) or 0.0
    free = _cfg(config, "liq_free", LIQ_FREE)
    k = _cfg(config, "liq_k", LIQ_K)
    part = _cfg(config, "liq_part", LIQ_PART)
    runway_max = _cfg(config, "liq_runway_max", LIQ_RUNWAY_MAX)
    floor = _cfg(config, "stress_floor", STRESS_FLOOR)

    es_frac = (_num(es95_pct) or 0.0) / 100.0                     # negative percent -> negative fraction
    stress = _clamp(1.0 - k * max(0.0, (-es_frac) - free), floor, 1.0)

    if adv is None or adv <= 0:                                   # no ADV ⇒ cannot grant an exception
        return {"adv90": adv, "stress": round(stress, 4), "per_day": None,
                "days_50": None, "days_90": None, "runway_ok": False, "runway_max": runway_max,
                "note": "ADV unavailable — liquidity-runway cannot grant a size-band exception (fail-safe)"}

    per_day = adv * stress * part
    days_50 = 0.50 * shares / max(1.0, per_day)
    days_90 = 0.90 * shares / max(1.0, per_day)
    return {"adv90": adv, "stress": round(stress, 4), "per_day": round(per_day, 1),
            "days_50": round(days_50, 2), "days_90": round(days_90, 2),
            "runway_ok": days_90 <= runway_max, "runway_max": runway_max,
            "note": f"{days_90:.1f}d to clear 90% at {part:.0%} of ADV (stress {stress:.2f})"}


# --------------------------------------------------------------------------- financing window
def financing_window(price: Any, *, last_placement_price: Any = None, rep_floor: Any = None,
                     lo52: Any = None, hi52: Any = None, dilution_ok: Optional[bool] = True,
                     runway_months: Any = None, config: Optional[dict] = None) -> dict:
    """Reflexivity read: can the name raise cheaply right now? A weighted blend over whatever terms
    are available (renormalized), plus the death-spiral flag. Returns raw legs too (for the grammar
    context). ``window_open`` is the boolean; ``score`` the [0,1] blend.

    ``dilution_ok`` is TRI-STATE: True (sieve clean) / False (sieve failing) / None (no share-count
    data). None must NOT be scored clean — that fail-open credited the full dilution weight to
    exactly the names most likely to lack clean data, and made the death-spiral flag structurally
    unable to fire on them. A None drops the term from the renormalized blend, disqualifies the
    death-spiral *clean* verdict (the flag needs KNOWN-failing dilution), and is named in
    provenance."""
    p = _num(price)
    w_prem = _cfg(config, "w_prem", W_PREM)
    w_floor = _cfg(config, "w_floorhead", W_FLOORHEAD)
    w_pct = _cfg(config, "w_pct52", W_PCT52)
    w_dil = _cfg(config, "w_dilution", W_DILUTION)
    thr = _cfg(config, "window_open_threshold", WINDOW_OPEN_THRESHOLD)
    ds_runway = _cfg(config, "deathspiral_runway_months", DEATHSPIRAL_RUNWAY_MONTHS)

    lpp, rf = _num(last_placement_price), _num(rep_floor)
    lo, hi = _num(lo52), _num(hi52)
    prem = (p / lpp - 1.0) if (p and lpp and lpp > 0) else None
    headroom = (p / rf - 1.0) if (p and rf and rf > 0) else None
    pct52 = _clamp((p - lo) / (hi - lo), 0.0, 1.0) if (p is not None and lo is not None
                                                       and hi is not None and hi > lo) else None

    terms, used = [], []
    if prem is not None:
        terms.append((w_prem, _sat(prem)))
        used.append("prem_to_placement")
    if headroom is not None:
        terms.append((w_floor, _sat(headroom)))
        used.append("floor_headroom")
    if pct52 is not None:
        terms.append((w_pct, pct52))
        used.append("pctile_52w")
    if dilution_ok is not None:                                  # None = no data ⇒ no credit either way
        terms.append((w_dil, 1.0 if dilution_ok else 0.0))
        used.append("dilution_ok")

    wsum = sum(w for w, _ in terms) or 1.0
    score = sum(w * v for w, v in terms) / wsum

    rm = _num(runway_months)
    # the death-spiral flag needs KNOWN-failing dilution — missing data neither fires it (no false
    # alarm) nor certifies the name clean (the fail-open this replaces).
    death_spiral = bool(p is not None and rf is not None and p < rf
                        and rm is not None and rm < ds_runway and dilution_ok is False)
    return {
        "score": round(score, 4), "window_open": score >= thr,
        "state": "open" if score >= thr else "closing",
        "prem_to_placement": round(prem, 4) if prem is not None else None,
        "floor_headroom": round(headroom, 4) if headroom is not None else None,
        "pctile_52w": round(pct52, 4) if pct52 is not None else None,
        "dilution_ok": (None if dilution_ok is None else bool(dilution_ok)),
        "death_spiral": death_spiral,
        "death_spiral_assessable": dilution_ok is not None,
        "ds_runway_months": ds_runway,
        "terms_used": used,
        "provenance": ([] if "prem_to_placement" in used else ["last_placement_price missing"])
                      + ([] if "pctile_52w" in used else ["52-wk range missing"])
                      + ([] if dilution_ok is not None
                         else ["dilution data missing — sieve not scored, death-spiral unassessable"]),
    }


# --------------------------------------------------------------------------- thesis integrity
def thesis_integrity(claims: Optional[list], metric_values: dict, *,
                     config: Optional[dict] = None) -> dict:
    """Re-check each engine claim against live metrics (manual claims keep their stored status, only
    the operator/verifier flips them). Returns the integrity fraction + per-claim statuses."""
    claims = claims or []
    floor = _cfg(config, "integrity_floor", INTEGRITY_FLOOR)
    statuses, holds, broken = [], 0, []
    for c in claims:
        cid = c.get("id", "?")
        check = c.get("check") or ("engine" if c.get("metric") else "manual")
        if check == "manual":
            st = c.get("status", "holds")
        else:
            # numeric-coerce BEFORE comparing: a non-numeric metric value (a status string that
            # drifted into the context) passes the None check but makes the comparator raise
            # TypeError — crashing the whole sweep. The contract is "evaluation never raises";
            # anything non-numeric is "unknown" (fail closed), mirroring trigger_grammar._cmp.
            mv = _num(metric_values.get(c.get("metric")))
            op = c.get("op")
            thr = _num(c.get("threshold"))
            cmp = _COMPARATORS.get(op)
            if mv is None or thr is None or cmp is None:
                st = "unknown"                                    # fail closed: don't claim it holds
            else:
                st = "holds" if cmp(mv, thr) else "broken"
        statuses.append({"id": cid, "text": c.get("text"), "check": check, "status": st,
                         "metric": c.get("metric")})
        if st == "holds":
            holds += 1
        elif st == "broken":
            broken.append(cid)
    total = len(claims)
    score = holds / total if total else 1.0
    return {"score": round(score, 4), "holds": holds, "total": total,
            "statuses": statuses, "broken": broken,
            "below_floor": (total > 0 and score < floor), "floor": floor}


# --------------------------------------------------------------------------- rule evaluation + dedupe
_LEVEL_BY_ACTION = {"exit": "risk", "trim_to": "warn", "add_to": "good",
                    "alert": "info", "flag": "warn", "review": "info"}
#: Build-Spec Open-Decision #5: the Sentinel may auto-act on ALERTS, never on exits/trims (those
#: surface as proposals the operator acks). This set is what the runner is allowed to fire unattended.
AUTO_ACTABLE = frozenset({"alert", "flag"})


def evaluate_rules(rules: Optional[list], ctx: dict, *, thesis_id: str = "",
                   open_keys: Optional[set] = None, acknowledged_keys: Optional[set] = None) -> list:
    """Evaluate each pre-commitment rule's trigger via the safe grammar and dedupe against already-open
    / acknowledged alerts. Returns a list of fired-rule dicts with a ``status`` of new|open|acked."""
    out = []
    open_keys = open_keys or set()
    acknowledged_keys = acknowledged_keys or set()
    for r in (rules or []):
        rid = r.get("id", "?")
        fired, notes = tg.safe_eval(r.get("trigger", ""), ctx)
        if not fired:
            continue
        key = f"{thesis_id}:{rid}"
        if key in acknowledged_keys:
            status = "acked"
        elif key in open_keys:
            status = "open"
        else:
            status = "new"
        action = r.get("action", "alert")
        out.append({
            "key": key, "rule_id": rid, "trigger": r.get("trigger"),
            "action": action, "arg": r.get("arg"),
            "level": _LEVEL_BY_ACTION.get(action, "info"),
            "auto_actable": action in AUTO_ACTABLE,
            "proposal": action not in AUTO_ACTABLE,              # trims/exits PROPOSE, never auto-fire
            "status": status, "notes": notes,
            "text": _rule_alert_text(r),
        })
    return out


def _rule_alert_text(rule: dict) -> str:
    a = rule.get("action", "alert")
    arg = rule.get("arg")
    verb = {"trim_to": f"TRIM to {arg}", "add_to": f"ADD to {arg}", "exit": "EXIT",
            "alert": "ALERT", "flag": "FLAG", "review": "REVIEW"}.get(a, a.upper())
    return f"Pre-commitment rule {rule.get('id','?')} fired → {verb}  [{rule.get('trigger','')}]"


# --------------------------------------------------------------------------- the per-name sweep
def sweep_name(*, ticker: str, basket: dict, node: Optional[dict] = None,
               portfolio_stats: Optional[dict] = None, thesis: Optional[dict] = None,
               mri: Any = None, adv90: Any = None, last_placement_price: Any = None,
               lo52: Any = None, hi52: Any = None, runway_months: Any = None,
               at_ceiling: bool = False, catalyst_within_days: Optional[Callable] = None,
               events: Optional[dict] = None, open_keys: Optional[set] = None,
               acknowledged_keys: Optional[set] = None, config: Optional[dict] = None,
               now: Optional[str] = None) -> dict:
    """Diff one held name's live state against its frozen thesis. Pure: the caller resolves the gap
    inputs (adv90/last_placement/52w/runway from research_cache or fundamentals — STATE_FIELDS) and
    binds ``catalyst_within_days`` / ``events`` from the calendar. Returns the full SENTINEL status.

    ``basket`` is the projected conviction basket (asymmetry/ladder/gate/dilution_velocity). ``node``
    carries shares (and price). ``at_ceiling`` says the name is at/over the soft size band — only then
    does the liquidity-runway gate decide whether the size is *permitted*.
    """
    node = node or {}
    asym = basket.get("asymmetry") or {}
    ladder = basket.get("ladder") or {}
    gate = basket.get("gate") or {}

    price = _num(ladder.get("price")) or _num(node.get("price"))
    rep_floor = _num(ladder.get("floor"))
    phi = _num(asym.get("floor_coverage"))
    rho = _num(asym.get("rho"))
    upside_pct = _num(asym.get("upside_pct"))
    gate_cap = _num(gate.get("cap"))
    dil_vel = _num(basket.get("dilution_velocity"))
    rm = _num(runway_months) if runway_months is not None else _num(basket.get("runway_months"))
    pos_shares = _num(node.get("shares")) or 0.0
    es95_pct = _num((portfolio_stats or {}).get("expected_shortfall_95"))
    sieve_qoq = _cfg(config, "dilution_sieve_qoq", DILUTION_SIEVE_QOQ)
    # tri-state: absent share-count data is UNKNOWN (None), never "clean" — financing_window drops
    # the term and the grammar fails closed on the missing metric (the fail-safe discipline).
    dilution_ok = None if dil_vel is None else (dil_vel < sieve_qoq)

    liq = liquidity_runway(adv90, es95_pct, pos_shares, config=config)
    win = financing_window(price, last_placement_price=last_placement_price, rep_floor=rep_floor,
                           lo52=lo52, hi52=hi52, dilution_ok=dilution_ok, runway_months=rm,
                           config=config)

    body = (thesis or {})
    integ = thesis_integrity(body.get("claims"), {
        "phi": phi, "rho": rho, "upside_pct": upside_pct, "runway_months": rm, "mri": _num(mri),
        "jsf": gate_cap, "price": price, "floor": rep_floor, "liq_days_90": liq.get("days_90"),
        "days_90": liq.get("days_90"), "window_open": 1.0 if win["window_open"] else 0.0,
    }, config=config)

    # the grammar context for the pre-commitment rules (es95 as a fraction, per the spec convention)
    ctx = {
        "phi": phi, "rho": rho, "upside_pct": upside_pct, "jsf": gate_cap,
        "runway_months": rm, "mri": _num(mri),
        "es95": (es95_pct / 100.0) if es95_pct is not None else None,
        "price": price, "floor": rep_floor,
        "liq_days_90": liq.get("days_90"), "days_90": liq.get("days_90"),
        "thesis_integrity": integ["score"],
        "window_open": win["window_open"], "dilution_ok": dilution_ok,
        "death_spiral": win["death_spiral"],
        "prem_to_placement": win["prem_to_placement"], "floor_headroom": win["floor_headroom"],
        "pctile_52w": win["pctile_52w"],
        "catalyst_within_days": catalyst_within_days,
        "events": events or {},
    }
    fired = evaluate_rules(body.get("rules"), ctx, thesis_id=(thesis or {}).get("id", "") or ticker,
                           open_keys=open_keys, acknowledged_keys=acknowledged_keys)

    alerts = list(fired)
    # synthetic (non-rule) alerts: death-spiral (high) and integrity break (warn), deduped the same way
    def _synthetic(key_suffix, level, text, priority):
        key = f"{ticker}:{key_suffix}"
        ack = acknowledged_keys or set()
        opn = open_keys or set()
        status = "acked" if key in ack else ("open" if key in opn else "new")
        return {"key": key, "rule_id": None, "action": "alert", "auto_actable": True,
                "proposal": False, "level": level, "priority": priority, "status": status,
                "text": text, "notes": []}
    if win["death_spiral"]:
        alerts.append(_synthetic("death_spiral", "risk",
                                 f"DEATH SPIRAL risk on {ticker}: below floor + runway < "
                                 f"{int(win.get('ds_runway_months', DEATHSPIRAL_RUNWAY_MONTHS))}mo "
                                 f"+ dilution sieve failing — forced-dilution impairs the thesis "
                                 f"(ties to JSF).", "high"))
    if integ["below_floor"]:
        alerts.append(_synthetic("integrity", "warn",
                                 f"THESIS INTEGRITY on {ticker} {integ['holds']}/{integ['total']} "
                                 f"({integ['score']:.0%}) below floor {integ['floor']:.0%} — "
                                 f"broken: {', '.join(integ['broken']) or '—'}.", "warn"))
    # priority on fired rules (exit > trim > alert)
    for a in alerts:
        if "priority" not in a:
            a["priority"] = {"risk": "high", "warn": "warn"}.get(a.get("level"), "info")

    new_alerts = [a for a in alerts if a["status"] == "new"]
    return {
        "ticker": ticker, "as_of": now or _now_iso(),
        "liquidity": liq, "window": win, "death_spiral": win["death_spiral"],
        "integrity": integ,
        "alerts": alerts, "new_alerts": new_alerts,
        "fired_rules": fired,
        # the size gate: if the name is at/over the band, the size is PERMITTED only when runway is ok
        "size_band_exception_allowed": bool(liq.get("runway_ok")),
        "size_gate": ("permitted" if (not at_ceiling) else
                      ("permitted" if liq.get("runway_ok") else "BREACH — over band without runway")),
        "provenance": {"adv90": adv90 is not None or node.get("adv_median_90") is not None,
                       "last_placement_price": last_placement_price is not None,
                       "range_52w": (lo52 is not None and hi52 is not None),
                       "runway_months": rm is not None},
    }


def status_to_memory_text(status: dict) -> str:
    """A compact one-line SENTINEL status for Living Memory."""
    liq = status.get("liquidity") or {}
    integ = status.get("integrity") or {}
    win = status.get("window") or {}
    parts = [f"SENTINEL {status.get('ticker')}"]
    if liq.get("days_90") is not None:
        parts.append(f"runway {liq['days_90']:.0f}d")
    if integ.get("total"):
        parts.append(f"integrity {integ['holds']}/{integ['total']}")
    parts.append(f"window {win.get('state', '—')}")
    if status.get("death_spiral"):
        parts.append("⚠DEATH-SPIRAL")
    n_new = len(status.get("new_alerts") or [])
    if n_new:
        parts.append(f"{n_new} new alert(s)")
    return " · ".join(parts)
