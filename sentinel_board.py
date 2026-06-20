"""
SENTINEL board (action-plan P2.3) — the single consolidated monitor surface.

One panel that gathers every upstream tell into uniform CARDS — each exposing its current READ, any
active FLAG, and which scenario it feeds (the one-directional hand-off to P3). It consolidates:

  * the NEW monitors — rates dashboard (P2.1), AI-productivity (P2.2), oil-supply-risk (P2.4);
  * the EXISTING macro-tape signals — silver positioning (CFTC), macro regime (DXY · real yield ·
    GSR), copper (Cu/Au);
  * USD/CAD carry + trend (the dry-powder currency tilt, also consumed by P4.3).

It is a PURE consumer (like council.py / sentinel.py): it reads already-computed monitor outputs and
normalizes them — it never re-computes a signal (one-directional flow). Coverage is explicit: a
monitor the plan expects but that isn't wired yet (e.g. the uranium term market) is listed under
``coverage.missing`` rather than silently absent. Pure stdlib; no eval().
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["build", "usdcad_carry"]

#: Monitors action-plan 2.3 expects on the board — used to compute the coverage gap honestly.
EXPECTED = ["rates", "productivity", "oil_supply", "silver_positioning",
            "macro_regime", "copper", "usdcad_carry", "uranium_term"]


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _card(monitor_id: str, label: str, read: str, value: Any, flag: Optional[dict],
          feeds_scenario: str) -> dict:
    """A uniform monitor card: id · label · current read · value · flag (or None) · scenario fed."""
    return {"id": monitor_id, "label": label, "read": read, "value": value,
            "flag": flag if (flag and flag.get("active")) else None,
            "feeds_scenario": feeds_scenario}


def usdcad_carry(us_rate: Any, ca_rate: Any, *, trend: Any = None) -> dict:
    """USD/CAD carry + trend for the dry-powder currency tilt (P2.3 → P4.3). Carry = US − CA policy
    rate (pp): positive ⇒ holding dry powder in USD earns the differential. ``trend`` (optional, the
    recent USDCAD change) tilts the same way when the dollar is also trending up. Pure/graceful."""
    us, ca = _num(us_rate), _num(ca_rate)
    carry = round(us - ca, 3) if (us is not None and ca is not None) else None
    tr = _num(trend)
    tilt = None
    if carry is not None:
        if carry > 0.10 and (tr is None or tr >= 0):
            tilt = "USD"                                   # carry + (non-adverse) trend favour USD powder
        elif carry < -0.10 and (tr is None or tr <= 0):
            tilt = "CAD"
        else:
            tilt = "NEUTRAL"
    read = (f"carry {carry:+.2f}pp (US−CA) → hold dry powder in {tilt}" if carry is not None
            else "carry n/a")
    return {"carry_pp": carry, "us_rate": us, "ca_rate": ca, "trend": tr, "tilt": tilt, "read": read}


def build(*, rates: Optional[dict] = None, productivity: Optional[dict] = None,
          oil: Optional[dict] = None, macro_tape: Optional[dict] = None,
          usdcad: Optional[dict] = None, uranium_term: Optional[dict] = None) -> dict:
    """Assemble the consolidated SENTINEL board from the monitor outputs (all optional). Returns
    ``{monitors, flags, coverage, net_read}`` — one surface where every present monitor shows its
    read + any active flag, and the coverage gap is explicit."""
    cards: list[dict] = []
    flags: list[dict] = []

    def _emit(card: dict, raw_flags: Optional[list] = None):
        cards.append(card)
        for f in (raw_flags or []):
            if f and f.get("active"):
                flags.append({**f, "monitor": card["id"]})

    # ---- NEW monitors --------------------------------------------------------
    if rates:
        bs = rates.get("bear_steepener") or {}
        fd = rates.get("fiscal_dominance") or {}
        rd_flag = next((f for f in (rates.get("flags") or []) if f.get("id") == "bear_steepener"), None)
        read = (f"{fd.get('label', '—')} · bear-steepener {'ACTIVE' if bs.get('active') else bs.get('note', 'dormant')}")
        _emit(_card("rates", "Rates · bear-steepener / fiscal dominance", read,
                    fd.get("score"), rd_flag, "B — disorderly fiscal dominance"),
              rates.get("flags"))
    if productivity:
        cp = productivity.get("scenario_c_pressure") or {}
        pr_flag = next((f for f in (productivity.get("flags") or []) if f.get("id") == "debasement_at_risk"), None)
        _emit(_card("productivity", "AI-productivity · thesis-breaker",
                    productivity.get("zone") or "—", cp.get("score"), pr_flag,
                    "C — AI-productivity muddle-through-WIN"),
              productivity.get("flags"))
    if oil:
        oil_flag = next((f for f in (oil.get("flags") or []) if f.get("id") == "oil_supply_risk"), None)
        _emit(_card("oil_supply", "Oil-supply risk", "ELEVATED" if oil.get("elevated") else "dormant",
                    oil.get("elevated"), oil_flag, "arms 5.4 energy-royalty watch"),
              oil.get("flags"))

    # ---- EXISTING macro-tape signals (consolidated, not recomputed) ----------
    sig = {s.get("key"): s for s in ((macro_tape or {}).get("signals") or [])}

    def _tape_card(key, monitor_id, label, feeds):
        s = sig.get(key)
        if not s:
            return
        _emit(_card(monitor_id, label, s.get("read", "—"), s.get("value"), None, feeds))
    _tape_card("cftc", "silver_positioning", "Silver positioning · CFTC %ile", "A/B — debasement & crisis")
    _tape_card("cu_au", "copper", "Copper · Cu/Au reflation", "C/D — growth without debasement")
    # macro regime: a small composite card from the regime signals + the tape's net tilt
    mt = macro_tape or {}
    if sig.get("real_yield") or sig.get("dxy") or sig.get("gsr"):
        ry = (sig.get("real_yield") or {}).get("value")
        dxy = (sig.get("dxy") or {}).get("value")
        gsr = (sig.get("gsr") or {}).get("value")
        read = (f"{mt.get('net_tilt', '—')} · real yld {ry if ry is not None else '—'} · "
                f"DXY {dxy if dxy is not None else '—'} · GSR {gsr if gsr is not None else '—'}")
        _emit(_card("macro_regime", "Macro regime · DXY / real yield / GSR", read,
                    mt.get("net_tilt"), None, "A — managed debasement / repression"))

    # ---- USD/CAD carry + uranium term ----------------------------------------
    if usdcad:
        _emit(_card("usdcad_carry", "USD/CAD carry + trend", usdcad.get("read", "—"),
                    usdcad.get("carry_pp"), None, "dry-powder currency tilt (P4.3)"))
    if uranium_term:
        ut_flag = uranium_term.get("flag") if (uranium_term.get("flag") or {}).get("active") else None
        _emit(_card("uranium_term", "Uranium term market", uranium_term.get("read", "—"),
                    uranium_term.get("value"), ut_flag, "electrification slot invalidation"),
              [uranium_term.get("flag")] if uranium_term.get("flag") else None)

    present = [c["id"] for c in cards]
    missing = [m for m in EXPECTED if m not in present]
    scenarios_under_pressure = sorted({f.get("monitor") for f in flags if f.get("monitor")})
    net_read = {
        "active_flags": len(flags),
        "monitors_present": len(present),
        "coverage_pct": round(100.0 * len(present) / len(EXPECTED), 0),
        "scenarios_flagged": scenarios_under_pressure,
        "summary": (f"{len(flags)} active flag(s) across {len(present)}/{len(EXPECTED)} monitors"
                    if flags else f"clean — {len(present)}/{len(EXPECTED)} monitors, no active flags"),
    }
    return {
        "monitors": cards,
        "flags": flags,
        "coverage": {"present": present, "missing": missing, "expected": EXPECTED},
        "net_read": net_read,
        "note": "single SENTINEL surface — each monitor shows its read + any flag; all feed scenario weights (P3)",
    }
