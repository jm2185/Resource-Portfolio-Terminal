"""
Stage-normalized peer EV/oz — comparing juniors on a like-for-like footing.

A peer's EV/oz is not a clean read of "what the market pays per ounce" — it bakes in how far
down the **de-risking curve** the project sits. A single-asset developer that has published a
PFS, drilled off its resource, and proven metallurgy (BRC.V — Blackrock, the parcel adjacent to
AGA.V/Hughes, and their sole focus) *earns* a richer EV/oz than a pre-PEA explorer with a large
but inferred resource. Applying that richer multiple straight onto a less-advanced name's ounces
overstates it.

So before blending peers we **normalize each one to the target's stage**: a more-advanced peer is
discounted down toward the target's (earlier) stage; a less-advanced peer is lifted up. The shape
is the classic Lassonde "de-risking premium" curve — relative EV/oz by stage. Only the *ratios*
between stages matter (the anchor cancels), so the absolute level is irrelevant.

Pure stdlib, fully testable offline. Every weight here is a REASONED FIRST CALIBRATION (the spread
of the curve is deliberately wider than the legacy ``stage_multipliers`` block, which compressed a
producer to only ~1.3x an explorer — unrealistically flat for the Lassonde premium). It is NOT
backtested; treat the curve as a tunable, not a truth, and override it from config.
"""
from __future__ import annotations

from typing import Optional


#: Relative EV/oz by de-risking stage (the Lassonde premium). Anchored at PEA = 1.0 purely for
#: readability — normalization uses ratios, so the anchor cancels. Config-overridable.
DEFAULT_STAGE_CURVE: dict[str, float] = {
    "grassroots": 0.30,
    "exploration": 0.45, "explorer": 0.45,
    "delineation": 0.60,
    "pre_pea": 0.75,
    "pea": 1.00,
    "pfs": 1.35, "prefeasibility": 1.35,
    "dfs": 1.60, "feasibility": 1.60, "definitive": 1.60,
    "permitting": 1.75, "permitted": 1.75,
    "construction": 1.45,                       # the "orphan period" funding dip
    "producer": 2.00, "producing": 2.00, "production": 2.00,
}

#: Stage-name synonyms -> canonical curve keys (tolerates config/registry/sub-archetype spellings).
_STAGE_ALIASES: dict[str, str] = {
    "grass_roots": "grassroots", "early_exploration": "exploration",
    "resource": "delineation", "resource_definition": "delineation", "delineation_drilling": "delineation",
    "maiden_resource": "delineation", "resource_expansion": "delineation",
    "pre-pea": "pre_pea", "prepea": "pre_pea", "scoping": "pre_pea",
    "p_e_a": "pea", "preliminary_economic_assessment": "pea",
    "pre_feasibility": "pfs", "pre-feasibility": "pfs",
    "bankable": "dfs", "fs": "dfs",
    "permit": "permitting",
    "build": "construction", "development": "construction",
    "producer_ramp": "producer", "ramp_up": "construction", "operating": "producer",
}


def stage_factor(stage: Optional[str], curve: Optional[dict] = None) -> float:
    """Curve value for a stage label (case/spacing/synonym tolerant). Returns 0.0 for an
    unknown/empty stage so the caller can fall back to a neutral (un-normalized) comparison
    rather than silently inventing a multiple."""
    curve = curve or DEFAULT_STAGE_CURVE
    if not stage:
        return 0.0
    key = str(stage).strip().lower().replace(" ", "_").replace("-", "_")
    key = _STAGE_ALIASES.get(key, key)
    return float(curve.get(key, 0.0))


def normalize_ev_oz(peer_ev_oz: float, peer_stage: Optional[str], target_stage: Optional[str],
                    curve: Optional[dict] = None) -> tuple[float, float]:
    """Bring ``peer_ev_oz`` into ``target_stage``'s frame.

    factor = curve[target] / curve[peer]: a more-advanced peer (curve[peer] > curve[target]) is
    discounted (factor < 1); a less-advanced peer is lifted (factor > 1). If either stage is
    unknown the factor is 1.0 (neutral — we never fabricate a stage gap we can't anchor).

    Returns ``(normalized_ev_oz, factor)``."""
    curve = curve or DEFAULT_STAGE_CURVE
    tp, pp = stage_factor(target_stage, curve), stage_factor(peer_stage, curve)
    if tp <= 0.0 or pp <= 0.0:
        return float(peer_ev_oz), 1.0
    factor = tp / pp
    return float(peer_ev_oz) * factor, factor


def effective_oz(indicated: float = 0.0, inferred: float = 0.0, *,
                 mi_weight: float = 1.0, inf_weight: float = 0.5) -> float:
    """Confidence-weighted ounces: measured/indicated at full weight, inferred haircut. A pre-PEA
    name with a huge *inferred* resource (AGA.V) is intentionally NOT credited the same as the same
    ounces measured & indicated."""
    return max(0.0, float(indicated or 0.0) * mi_weight + float(inferred or 0.0) * inf_weight)


#: |modified-z| (MAD-based) beyond which a peer's multiple is an OUTLIER — flagged and
#: down-weighted (never silently dropped). 3.5 is the standard Iglewicz–Hoaglin cut.
OUTLIER_MAD_Z = 3.5
#: weight multiplier applied to a flagged outlier (down-weighted, kept visible).
OUTLIER_DOWNWEIGHT = 0.25
#: outlier detection needs a minimum sample — below this every peer is kept at full weight
#: (a 3-peer comp has no robust center to deviate from).
OUTLIER_MIN_N = 4


def _median(vals: list) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _mad(vals: list, med: float) -> float:
    return _median([abs(v - med) for v in vals]) or 0.0


def blended_peer_ev_oz(peers: list, target_stage: Optional[str], *,
                       curve: Optional[dict] = None, default: float = 2.50) -> dict:
    """Stage-normalize a set of peers to ``target_stage`` and weight-average their EV/oz.

    ``peers``: list of dicts with ``ticker``, ``ev_oz`` (raw EV/oz), ``stage``, and an optional
    ``weight`` (relevance/liquidity — e.g. BRC.V pinned to full weight as the adjacent prime comp).
    Missing weights default to 1.0 (equal). Returns the blended EV/oz, the per-peer normalization
    detail (so the desk can audit *why* the multiple moved), and the effective weights.

    Validation flywheel (Phase 5) — the comp made inspectable, never a black box:
      * **Outlier handling** (n ≥ OUTLIER_MIN_N): a peer whose normalized multiple sits beyond
        ``OUTLIER_MAD_Z`` modified-z (median/MAD) is FLAGGED and down-weighted — visible in its
        detail row, never silently dropped.
      * **Dispersion** — median / MAD / relative dispersion across the normalized multiples; the
        relative dispersion is the EMPIRICAL sigma the distributional ribbon uses for the market
        leg (uncertainty.py interlock).
      * **Leave-one-out sensitivity** — how far the blend moves without each peer, naming the
        max-swing peer ("the comp moves −18% without BRC.V").
    Guardrail (V4 stands): nothing here conditions the multiple on the macro regime — the
    archetype layer already applies the regime once, on the tilt leg."""
    curve = curve or DEFAULT_STAGE_CURVE
    rows = []                                          # (ticker, normalized, weight, factor, raw, stage)
    for p in peers:
        ev = p.get("ev_oz")
        if ev is None or float(ev) <= 0.0:
            continue
        norm, factor = normalize_ev_oz(float(ev), p.get("stage"), target_stage, curve)
        w = float(p.get("weight", 1.0) or 0.0)
        if w <= 0.0:
            continue
        rows.append((p.get("ticker", "?"), norm, w, factor, float(ev), p.get("stage")))

    # ---- outlier pass (median + MAD modified-z) — flag + down-weight, never drop ----
    outliers: list = []
    norms = [r[1] for r in rows]
    med = _median(norms)
    if med is not None and len(rows) >= OUTLIER_MIN_N:
        mad = _mad(norms, med)
        if mad > 0:
            for i, (tkr, norm, w, factor, raw, stage) in enumerate(rows):
                mz = 0.6745 * (norm - med) / mad
                if abs(mz) > OUTLIER_MAD_Z:
                    rows[i] = (tkr, norm, w * OUTLIER_DOWNWEIGHT, factor, raw, stage)
                    outliers.append({"ticker": tkr, "normalized_ev_oz": round(norm, 4),
                                     "modified_z": round(mz, 2),
                                     "weight_mult": OUTLIER_DOWNWEIGHT})

    detail, wsum, acc = {}, 0.0, 0.0
    flagged = {o["ticker"] for o in outliers}
    for tkr, norm, w, factor, raw, stage in rows:
        detail[tkr] = {
            "raw_ev_oz": round(raw, 4), "stage": stage,
            "stage_factor": round(factor, 4), "normalized_ev_oz": round(norm, 4),
            "weight": round(w, 4),
        }
        if tkr in flagged:
            detail[tkr]["outlier"] = True
        acc += norm * w
        wsum += w
    blended = acc / wsum if wsum > 0 else float(default)

    out = {
        "blended_ev_oz": round(blended, 4),
        "target_stage": target_stage,
        "n_peers": len(detail),
        "sourced": bool(detail),                  # False -> caller fell back to `default`
        "peers": detail,
    }
    if outliers:
        out["outliers"] = outliers
    # ---- dispersion (the empirical market-leg sigma) ----
    if med is not None and len(norms) >= 2:
        mad = _mad(norms, med)
        out["dispersion"] = {
            "median": round(med, 4), "mad": round(mad, 4),
            # 1.4826·MAD ≈ σ for a normal core; relative to the median = a unitless sigma
            "rel_dispersion": round(1.4826 * mad / med, 4) if med > 0 else None,
            "spread_pct": round((max(norms) - min(norms)) / med * 100.0, 1) if med > 0 else None,
        }
    # ---- leave-one-out sensitivity (name the max-swing peer) ----
    if len(rows) >= 2 and wsum > 0 and blended > 0:
        sens = {}
        for tkr, norm, w, *_ in rows:
            rest_w = wsum - w
            if rest_w <= 0:
                continue
            without = (acc - norm * w) / rest_w
            sens[tkr] = {"blended_without": round(without, 4),
                         "swing_pct": round((without / blended - 1.0) * 100.0, 1)}
        if sens:
            out["sensitivity"] = sens
            out["max_swing_peer"] = max(sens, key=lambda t: abs(sens[t]["swing_pct"]))
    return out


def comp_audit(peer_details: dict) -> Optional[dict]:
    """Dispersion + leave-one-out audit over the ENGINE's live peer-comp detail dict
    (``PeerEngine.peer_data_cache``: {ticker: {adjusted_ev_oz, weight_used, ...}}). Returns
    {median, mad, rel_dispersion, sensitivity, max_swing_peer} or None when fewer than two peers
    speak. ``rel_dispersion`` is the empirical sigma the distributional ribbon (uncertainty.py)
    uses for the spear's market leg — measured comp disagreement, not an assumed band."""
    rows = []
    for tkr, d in (peer_details or {}).items():
        try:
            ev = float(d.get("adjusted_ev_oz"))
            w = float(d.get("weight_used", d.get("relevance_weight", 1.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        if ev > 0 and w > 0:
            rows.append((tkr, ev, w))
    if len(rows) < 2:
        return None
    evs = [r[1] for r in rows]
    med = _median(evs)
    mad = _mad(evs, med)
    wsum = sum(w for _, _, w in rows)
    blended = sum(ev * w for _, ev, w in rows) / wsum if wsum > 0 else None
    out = {"n_peers": len(rows), "median": round(med, 4), "mad": round(mad, 4),
           "rel_dispersion": round(1.4826 * mad / med, 4) if med > 0 else None}
    if blended and blended > 0:
        sens = {}
        for tkr, ev, w in rows:
            rest_w = wsum - w
            if rest_w <= 0:
                continue
            without = (sum(e * x for _, e, x in rows) - ev * w) / rest_w
            sens[tkr] = round((without / blended - 1.0) * 100.0, 1)
        if sens:
            out["sensitivity_pct"] = sens
            out["max_swing_peer"] = max(sens, key=lambda t: abs(sens[t]))
    return out
