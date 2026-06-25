"""
holdco_nav.py — layered NAV for a project-generator / royalty-company HOLDCO.

The cash-flow (royalty) valuation model can't price these names: their worth is a portfolio of mostly
out-of-the-money options plus a thin, growing cash-flow base. So we don't produce a point estimate — we
DECOMPOSE into three layers and report a RANGE:

  1. HARD FLOOR   — producing-royalty cash flow (DCF, net of corporate G&A) + net liquid assets (cash +
                    marketable securities − debt). Defensible, sourceable, conservative. This is the
                    REP-equivalent floor you SIZE AGAINST. Everything above it is upside you're paid to
                    hold, never underwritten.
  2. RISKED NAV   — + the development pipeline at RISKED value (NPV × probability-of-production). Re-rates
                    as projects advance, independent of metal price.
  3. BLUE SKY     — + an exploration/optionality bucket (default 0 — the panel's rule: never put a number
                    on the tail; mark it zero and be pleasantly surprised).

The capital rule falls straight out: **only deploy at/below the HARD FLOOR**, so the pipeline and the
exploration tail come free. Pure + dependency-free; conservatism lives in the INPUTS (use near-term,
sourced cash flow — not blue-sky). Never a buy/sell call; it frames the range and where price sits in it.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["DEFAULT_HOLDCO_NAV_CONFIG", "DEFAULT_STAGE_PROBABILITY", "annuity_pv", "hard_floor_total",
           "stage_probability", "risked_pipeline_from_assets", "optionality_read", "assess"]

DEFAULT_HOLDCO_NAV_CONFIG: dict[str, Any] = {
    "discount_rate": 0.10,     # royalty discount rate for the producing cash-flow stream
    "life_years": 15,          # DCF horizon for the producing stream (a finite annuity, not a perpetuity)
    "growth": 0.0,             # annual growth of the net producing cash flow over the horizon
    "optionality_value": 0.0,  # $ on the exploration tail + management premium — DEFAULT 0 (never underwrite it)
}

# P(reaches production | currently at this stage) — the "Lassonde-curve" CONDITIONAL advance rates that
# turn a development asset's headline NPV into a RISKED contribution to the base/fair-value layer. These
# are deliberately conservative mid-points of the mining-finance norm (an analyst can argue a band); they
# are TUNABLE via config["holdco_nav"]["stage_probability"], and a stage we don't recognize risks at the
# explicit `_default` so an unknown never silently scores 0 OR 1. Keys are matched case/space-insensitively
# on substrings, so "Feasibility Study", "fs", "in construction" all resolve.
DEFAULT_STAGE_PROBABILITY: dict[str, float] = {
    "producing": 1.00, "production": 1.00,
    "construction": 0.90, "permitted": 0.75, "permitting": 0.65,
    "feasibility": 0.50, "fs": 0.50, "dfs": 0.55,
    "pfs": 0.30, "prefeasibility": 0.30,
    "pea": 0.15, "resource": 0.10,
    "drilling": 0.05, "discovery": 0.05, "exploration": 0.03, "grassroots": 0.02,
    "_default": 0.10,
}


def _num(x: Any) -> Optional[float]:
    try:
        f = float(x)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _cfg(config: Optional[dict]) -> dict:
    cfg = dict(DEFAULT_HOLDCO_NAV_CONFIG)
    block = (config or {}).get("holdco_nav", config or {}) if config else {}
    if isinstance(block, dict):
        for k, v in block.items():
            cfg[k] = v
    return cfg


def annuity_pv(annual_cf: Any, *, discount_rate: float = 0.10, life_years: int = 15,
               growth: float = 0.0) -> Optional[float]:
    """Present value of a finite (optionally growing) annual cash-flow stream. ``annual_cf`` MAY be
    negative (a corporate that doesn't yet cover its G&A — its 'producing' leg is a capitalized burn,
    correctly reducing the floor). Returns None on bad inputs. Pure."""
    cf = _num(annual_cf)
    r = _num(discount_rate)
    n = int(life_years) if _num(life_years) else 0
    g = _num(growth) or 0.0
    if cf is None or r is None or r <= -1.0 or n <= 0:
        return None
    pv = 0.0
    for t in range(1, n + 1):
        pv += cf * ((1.0 + g) ** (t - 1)) / ((1.0 + r) ** t)
    return round(pv, 2)


def hard_floor_total(*, producing_royalty_cf: Any = 0.0, corporate_g_and_a: Any = 0.0,
                     net_liquid_assets: Any = 0.0, config: Optional[dict] = None) -> dict:
    """The DEFENSIBLE floor in $ (not per share): DCF of the NET producing cash flow (royalty revenue −
    corporate G&A) + net liquid assets (cash + marketable securities − debt), floored at 0 (equity is
    limited-liability). A young royalty company not yet covering its G&A gets a LOWER floor — by design.
    Returns the floor + its legs. Pure."""
    cfg = _cfg(config)
    rev = _num(producing_royalty_cf) or 0.0
    gna = _num(corporate_g_and_a) or 0.0
    liquid = _num(net_liquid_assets) or 0.0
    net_cf = rev - gna                                   # the corporate net cash the royalties throw off
    producing_pv = annuity_pv(net_cf, discount_rate=cfg["discount_rate"],
                              life_years=cfg["life_years"], growth=cfg["growth"]) or 0.0
    raw = producing_pv + liquid
    floor = max(0.0, raw)                                # a hard floor can't be negative
    return {"hard_floor": round(floor, 2), "producing_net_cf": round(net_cf, 2),
            "producing_pv": round(producing_pv, 2), "net_liquid_assets": round(liquid, 2),
            "self_funding": bool(net_cf >= 0.0), "floored_at_zero": bool(raw < 0.0)}


def stage_probability(stage: Any, table: Optional[dict] = None) -> float:
    """P(reaches production | at ``stage``). Case/space-insensitive substring match against the table
    (so 'Feasibility Study' → feasibility), falling back to ``_default`` for an unrecognized stage —
    never a silent 0 or 1. Pure."""
    tbl = dict(DEFAULT_STAGE_PROBABILITY)
    if isinstance(table, dict):
        tbl.update(table)
    s = str(stage or "").strip().lower()
    if s in tbl:
        return float(tbl[s])
    for key in sorted((k for k in tbl if k != "_default"), key=len, reverse=True):
        if key in s:                         # substring match, longest key first → most specific wins
            return float(tbl[key])
    return float(tbl.get("_default", 0.10))


def risked_pipeline_from_assets(assets: Any, *, config: Optional[dict] = None) -> dict:
    """Turn a list of development pipeline assets ``[{name, npv, stage, probability?}]`` into the RISKED
    pipeline value Σ(npv × P), where P is the asset's explicit ``probability`` if given, else the
    stage-probability. This is the auditable, per-project basis of the base/fair-value layer (the upside
    the floor deliberately omits). Returns the total + a per-asset breakdown. A bad/zero NPV asset
    contributes 0 but is still listed (transparency). Pure."""
    cfg = _cfg(config)
    table = cfg.get("stage_probability") if isinstance(cfg.get("stage_probability"), dict) else None
    total = 0.0
    breakdown: list[dict] = []
    for a in (assets or []):
        if not isinstance(a, dict):
            continue
        npv = _num(a.get("npv"))
        p = _num(a.get("probability"))
        if p is None:
            p = stage_probability(a.get("stage"), table)
        p = max(0.0, min(1.0, p))
        risked = (npv * p) if (npv is not None and npv > 0) else 0.0
        total += risked
        breakdown.append({"name": a.get("name"), "npv": npv, "stage": a.get("stage"),
                          "probability": round(p, 3), "risked": round(risked, 2)})
    return {"risked_pipeline_value": round(total, 2), "assets": breakdown}


def optionality_read(*, price_ps: Any, risked_nav_ps: Any, shares: Any, asset_count: Any = None,
                     ev_per_asset: Any = None) -> dict:
    """The BLUE-SKY layer, two ways — so 'price > risked NAV' is never naively read as 'no upside':

      * IMPLIED (always, no extra data): ``(price − risked NAV) × shares`` = what the MARKET already pays
        for the optionality the risked NAV omits (the carried portfolio + discovery + un-sourced
        pipeline). Reported total, per-asset, and as a % of price. ``implied_per_asset`` lets you sanity-
        check it: a project generator carrying 250+ properties + royalties for a few $/share of premium
        is the market paying ~nothing for the blue sky — often CHEAP, not rich. Negative ⇒ price is
        at/below risked NAV (you aren't paying for blue sky at all).
      * PEER-COMP (when ``ev_per_asset`` given): ``ev_per_asset × asset_count`` = a defensible portfolio
        optionality VALUE → the bull's upper bound; ``blue_sky_ps = risked NAV + that / shares``, and a
        verdict compares the implied per-asset to it (market cheap / fair / rich vs the comp).
    Pure; graceful on missing inputs (returns ``available: False``)."""
    P, rn, sh = _num(price_ps), _num(risked_nav_ps), _num(shares)
    if P is None or rn is None or not (sh and sh > 0) or P <= 0:
        return {"available": False, "read": "optionality n/a (need price, risked NAV, shares)"}
    implied_total = (P - rn) * sh
    n = _num(asset_count)
    out: dict = {
        "available": True, "implied_optionality_total": round(implied_total, 2),
        "implied_pct_of_price": round((P - rn) / P * 100, 1),
        "implied_per_asset": round(implied_total / n, 0) if (n and n > 0) else None,
        "asset_count": int(n) if (n and n > 0) else None,
    }
    evpa = _num(ev_per_asset)
    if evpa is not None and n and n > 0:
        peer_total = evpa * n
        out["peer_comp_optionality_total"] = round(peer_total, 2)
        out["blue_sky_ps"] = round(rn + peer_total / sh, 3)
        implied_pa = implied_total / n
        # cheap = market pays well under the comp for the same portfolio; rich = well over.
        if implied_pa < 0.6 * evpa:
            verdict = "cheap"
        elif implied_pa > 1.4 * evpa:
            verdict = "rich"
        else:
            verdict = "fair"
        out["verdict_vs_peer"] = verdict
        out["read"] = (f"market prices the blue sky at {implied_total/sh:.2f}/sh "
                       f"({implied_total/n:,.0f}/asset across {int(n)}) — {verdict} vs the peer comp "
                       f"{evpa:,.0f}/asset (bull {out['blue_sky_ps']:.2f}/sh)")
    else:
        per = f" ({implied_total/n:,.0f}/asset across {int(n)})" if (n and n > 0) else ""
        out["read"] = (f"market prices the blue sky at {implied_total/sh:.2f}/sh{per} = "
                       f"{out['implied_pct_of_price']:.0f}% of price — feed a peer EV/asset to grade it")
    return out


def assess(*, name: str = "", price: Any = None, shares: Any = None,
           producing_royalty_cf: Any = 0.0, corporate_g_and_a: Any = 0.0, net_liquid_assets: Any = 0.0,
           risked_pipeline_value: Any = 0.0, pipeline_assets: Optional[list] = None,
           optionality_value: Any = None, asset_count: Any = None, ev_per_asset: Any = None,
           sourced: Optional[dict] = None, config: Optional[dict] = None) -> dict:
    """Layered NAV for a holdco/royalty-company, in PER-SHARE terms, plus where price sits in the range
    and the capital read. All $ inputs are TOTALS (company-level); ``shares`` converts to per share.
    ``sourced`` (optional) flags which layers came from filings vs. were assumed — surfaced honestly in
    ``coverage``. Returns the three layers, the margin-of-safety vs the HARD floor, and an entry_read
    that states the panel's rule (deploy only at/below the hard floor). Pure; graceful on missing inputs."""
    cfg = _cfg(config)
    P = _num(price)
    sh = _num(shares)
    hf = hard_floor_total(producing_royalty_cf=producing_royalty_cf, corporate_g_and_a=corporate_g_and_a,
                          net_liquid_assets=net_liquid_assets, config=config)
    # The risked pipeline (the upside/base layer) comes from a per-asset list when given — Σ(NPV ×
    # stage-probability), auditable per project — else the scalar override. This is the value the floor
    # deliberately omits; sourcing it is what gives a holdco/PG a real, non-degraded fair value.
    pipe_breakdown = None
    if pipeline_assets:
        rp = risked_pipeline_from_assets(pipeline_assets, config=config)
        pipeline = max(0.0, rp["risked_pipeline_value"])
        pipe_breakdown = rp["assets"]
    else:
        pipeline = max(0.0, _num(risked_pipeline_value) or 0.0)
    # blue-sky / optionality (the bull): a peer EV-per-asset × asset_count when supplied (a defensible
    # portfolio comp), else the explicit scalar, else the config default (0 — never underwrite the tail).
    evpa, ac = _num(ev_per_asset), _num(asset_count)
    if evpa is not None and ac and ac > 0:
        opt = max(0.0, evpa * ac)
    else:
        opt = _num(optionality_value)
        opt = (cfg["optionality_value"] if opt is None else opt)
        opt = max(0.0, opt)

    floor_total = hf["hard_floor"]
    risked_total = floor_total + pipeline
    blue_total = risked_total + opt

    if not (sh and sh > 0):
        return {"available": False, "name": name, "read": "holdco NAV n/a (shares outstanding missing)",
                "hard_floor_total": floor_total, "legs": hf}

    hf_ps = floor_total / sh
    risked_ps = risked_total / sh
    blue_ps = blue_total / sh

    out: dict = {
        "available": True, "name": name, "price": P, "shares": sh,
        "hard_floor_ps": round(hf_ps, 3), "risked_nav_ps": round(risked_ps, 3),
        "blue_sky_ps": round(blue_ps, 3), "legs": hf,
        # the per-share LADDER the rating wires to: bear=hard floor (downside), base=risked NAV
        # (fair value, incl. probability-weighted pipeline), bull=blue sky (the upside potential).
        "ladder": {"bear": round(hf_ps, 3), "base": round(risked_ps, 3), "bull": round(blue_ps, 3)},
        "pipeline_total": round(pipeline, 2), "optionality_total": round(opt, 2),
        "pipeline_assets": pipe_breakdown,
        # which input layers came from filings vs. were assumed — passed straight through (keyed by the
        # input name) so the feed bridge's per-layer provenance flags surface here unchanged.
        "coverage": {str(k): bool(v) for k, v in sourced.items()} if isinstance(sourced, dict) else {},
    }
    if P is not None and P > 0:
        out["floor_coverage"] = round(hf_ps / P, 3)            # ≥1 ⇒ price at/below the hard floor (φ-equiv)
        out["margin_of_safety_pct"] = round((hf_ps / P - 1.0) * 100, 1)
        paid_over_floor = max(0.0, P - hf_ps)
        out["paid_over_floor_ps"] = round(paid_over_floor, 3)
        if P <= hf_ps:
            read = (f"AT/BELOW HARD FLOOR ({hf_ps:.2f}) — the development pipeline and the exploration "
                    f"tail are FREE. This is the margin-of-safety entry.")
            zone = "below_hard_floor"
        elif P <= risked_ps:
            read = (f"above hard floor {hf_ps:.2f}, below risked NAV {risked_ps:.2f} — paying "
                    f"{paid_over_floor:.2f}/sh for the development pipeline; the exploration tail is free.")
            zone = "in_pipeline_band"
        else:
            read = (f"above risked NAV {risked_ps:.2f} — paying {paid_over_floor:.2f}/sh over the "
                    f"defensible floor for pipeline + optionality/premium. Underwriting the tail.")
            zone = "above_risked_nav"
        out["entry_zone"] = zone
        out["read"] = f"{name or 'name'} {P:.2f} vs hard floor {hf_ps:.2f} · risked {risked_ps:.2f} · blue-sky {blue_ps:.2f} — {read}"
        # the blue-sky read: what the market pays for the optionality the risked NAV omits (implied),
        # per-asset, graded against a peer EV/asset when one is supplied.
        out["optionality"] = optionality_read(price_ps=P, risked_nav_ps=risked_ps, shares=sh,
                                               asset_count=asset_count, ev_per_asset=ev_per_asset)
    else:
        out["read"] = (f"{name or 'name'} hard floor {hf_ps:.2f}/sh · risked {risked_ps:.2f} · "
                       f"blue-sky {blue_ps:.2f} (no live price)")
    out["note"] = "a RANGE, not a point — size against the HARD floor; pipeline + optionality are upside you're paid to hold, never underwritten"
    return out
