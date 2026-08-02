"""Mined invariants — ValuationEngine (F1 of docs/FABLE_INTEGRATION.md).

Property tests over the valuation stack: each test states a mathematical claim the output MUST
satisfy for every admissible input, then checks it over seeded randomized sweeps (plain pytest —
deterministic seeds, no hypothesis dependency). A failure here means the valuation math broke a
first-principles property, not that a fixture drifted.

Hermetic: a synthetic config through the ``_config_provider`` hook (the engine's own test seam),
``use_sourced_spear_oz=False`` so no research-cache read can leak in.
"""
import random

import pytest

from engines.valuation import ValuationEngine


def _cfg():
    return {
        "aga_shares_out": 100_000_000,
        "rep_floor_params": {"cash_treasury_m": 10.0, "permitting_infra_premium_m": 5.0,
                             "stressed_resource_per_oz": 0.50, "conservatism_scalar": 0.90},
        "project_buckets_oz_AgEq": {"alpha": 60_000_000, "beta": 40_000_000},
        "dynamic_discovery_v5": {"target_measured_indicated_pct": {"alpha": 0.60, "beta": 0.40},
                                 "use_sourced_spear_oz": False},
        "conservatism_scalar": 0.88,
        "exploration_upside": {"expected_future_oz": 50_000_000,
                               "probability_of_discovery": 0.25, "weight": 0.12},
        "triangulation": {
            "stage_weights": {"explorer": {"cost": 0.30, "market": 0.70, "income": 0.0}},
            "confidence": {"cost": 0.90, "market_base": 0.85, "income_explorer": 0.20}},
        "technical_quality": {
            "enabled": True, "tq_min": 0.55, "tq_max": 1.70,
            "factors": {"grade": {"lo": 0.85, "hi": 1.25, "benchmark_gpt_ageq": 250},
                        "metallurgy": {"lo": 0.90, "hi": 1.10, "rec_lo": 0.70, "rec_hi": 0.95},
                        "jurisdiction": {"lo": 0.90, "hi": 1.10, "fraser_lo": 50, "fraser_hi": 95},
                        "infrastructure": {"lo": 0.92, "hi": 1.08},
                        "depth": {"lo": 0.95, "hi": 1.05}},
            "projects": {"alpha": {"grade_gpt_ageq": 300, "ageq_share_ag": 0.7, "ageq_share_au": 0.3,
                                   "rec_ag": 0.85, "rec_au": 0.92, "fraser": 80,
                                   "infrastructure": 0.6, "depth": 0.5}}},
    }


@pytest.fixture()
def ve():
    v = ValuationEngine("unused-path")
    cfg = _cfg()
    v._config_provider = lambda: cfg
    return v


def _base_kwargs():
    return dict(peer_ev_oz=1.20, spot_ag=38.0, capital_discount_factor=0.85, real_yield=1.8,
                silver_vol=0.30, forensic_penalty=1.0, dynamic_aisc=22.0)


# ------------------------------------------------------------------ smooth curves
def test_jurisdiction_uplift_monotone_and_bounded(ve):
    """Claim: the uplift is a logistic in spot — strictly within (low, high) and non-decreasing."""
    rng = random.Random(1)
    spots = sorted(rng.uniform(1.0, 150.0) for _ in range(60))
    vals = [ve.calculate_jurisdiction_uplift(s) for s in spots]
    assert all(1.15 < v < 1.35 for v in vals)
    assert all(a <= b + 1e-12 for a, b in zip(vals, vals[1:]))


def test_capital_discount_monotone_floored(ve):
    """Claim: the cost-of-capital discount never increases with the 30y yield and never pierces
    its floor; at benign yields it approaches (never meaningfully exceeds) 1.0."""
    rng = random.Random(2)
    ys = sorted(rng.uniform(-1.0, 15.0) for _ in range(80))
    vals = [ve.calculate_capital_discount_factor(y) for y in ys]
    assert all(b <= a + 1e-9 for a, b in zip(vals, vals[1:]))          # non-increasing
    assert all(v >= 0.40 - 1e-9 for v in vals)                          # smooth floor holds
    assert all(v <= 1.0 + 0.05 for v in vals)                           # softplus overshoot bounded


# ------------------------------------------------------------------ REP floor
def test_rep_floor_positive_and_monotone(ve):
    """Claim: the stressed floor is positive, decreasing in share count (dilution lowers the
    per-share floor), and non-decreasing in the effective resource base."""
    rng = random.Random(3)
    for _ in range(30):
        sh = rng.uniform(20e6, 500e6)
        oz = rng.uniform(0.0, 300e6)
        f = ve.calculate_rep_floor(sh, effective_oz=oz)
        assert f > 0
        assert ve.calculate_rep_floor(sh * 2.0, effective_oz=oz) < f
        assert ve.calculate_rep_floor(sh, effective_oz=oz + 10e6) >= f


# ------------------------------------------------------------------ ballast fair value
def test_ballast_fair_value_nonnegative_and_degenerate_zero(ve):
    assert ve.calculate_ballast_fair_value(0.0, 10.0, 30.0, 25.0, 1.0) == 0.0
    assert ve.calculate_ballast_fair_value(-5.0, 10.0, 30.0, 25.0, 1.0) == 0.0
    assert ve.calculate_ballast_fair_value(3.0, 10.0, 30.0, 0.0, 1.0) == 0.0
    rng = random.Random(4)
    for _ in range(50):
        fv = ve.calculate_ballast_fair_value(rng.uniform(0.1, 50), rng.uniform(0.5, 20),
                                             rng.uniform(1, 100), rng.uniform(1, 100),
                                             rng.uniform(-2, 3), rng.uniform(0.2, 1.0))
        assert fv >= 0.0


def test_ballast_fair_value_monotone_in_spot_and_linear_in_mult(ve):
    """Claim: fair value never falls when the commodity rises (β ≥ 0), and the base multiple is a
    pure linear scale (fv(2m) = 2·fv(m)) — the price-decoupling contract."""
    rng = random.Random(5)
    for _ in range(30):
        ref, mult, ref_spot, beta = (rng.uniform(1, 30), rng.uniform(0.5, 5),
                                     rng.uniform(10, 60), rng.uniform(0.0, 2.5))
        s1, s2 = sorted((rng.uniform(1, 120), rng.uniform(1, 120)))
        f1 = ve.calculate_ballast_fair_value(ref, mult, s1, ref_spot, beta)
        f2 = ve.calculate_ballast_fair_value(ref, mult, s2, ref_spot, beta)
        assert f1 <= f2 + 1e-9
        fd = ve.calculate_ballast_fair_value(ref, mult * 2, s1, ref_spot, beta)
        assert abs(fd - 2 * f1) < 1e-9


# ------------------------------------------------------------------ peer propagation
def test_peer_ev_margin_scaled_identity_and_monotone():
    """Claim: no silver move → no re-rating; peers re-rate monotonically with the operating margin;
    the floored margin keeps the multiple strictly positive on any drawdown."""
    rng = random.Random(6)
    for _ in range(40):
        peer0 = rng.uniform(0.1, 10)
        spot0 = rng.uniform(5, 80)
        aisc = rng.uniform(0, 60)
        assert abs(ValuationEngine.peer_ev_margin_scaled(peer0, spot0, spot0, aisc) - peer0) < 1e-12
        s1, s2 = sorted((rng.uniform(1, 120), rng.uniform(1, 120)))
        p1 = ValuationEngine.peer_ev_margin_scaled(peer0, spot0, s1, aisc)
        p2 = ValuationEngine.peer_ev_margin_scaled(peer0, spot0, s2, aisc)
        assert p1 <= p2 + 1e-9
        assert p1 > 0


# ------------------------------------------------------------------ option premium
def test_option_premium_nonnegative_capped_weights_normalized(ve):
    """Claim: π_opt ≥ 0 always; the active weights sum to 1 (renormalized when the moneyness term is
    structurally inactive); each term respects its cap, so π_opt ≤ stage_cap · Σ wᵢ·capᵢ."""
    rng = random.Random(7)
    for _ in range(60):
        peer_aisc = rng.choice([None, rng.uniform(10, 40)])
        d = ve.calculate_option_premium(rng.uniform(5, 90), rng.uniform(5, 50),
                                        rng.uniform(0.0, 1.2), rng.uniform(-2.0, 5.0),
                                        stage="explorer", peer_aisc=peer_aisc)
        w = d["weights_used"]
        assert d["pi_opt"] >= 0.0
        assert abs(sum(w.values()) - 1.0) < 1e-6
        cap_bound = d["stage_cap"] * (w["moneyness"] * 1.50 + w["vol"] * 0.40 + w["carry"] * 0.50)
        assert d["pi_opt"] <= cap_bound + 1e-6
        if peer_aisc is None:
            assert d["moneyness_active"] is False and w["moneyness"] == 0.0


# ------------------------------------------------------------------ technical quality
def test_technical_quality_always_within_band(ve):
    """Claim: TQ is clamped to [tq_min, tq_max] for ANY project inputs — configured, absurd, or
    absent (and the unconfigured fallback is flagged, not silent)."""
    rng = random.Random(8)
    cfg = ve.get_config()
    for _ in range(40):
        cfg["technical_quality"]["projects"]["alpha"] = {
            "grade_gpt_ageq": rng.uniform(0, 3000), "ageq_share_ag": rng.uniform(0, 1),
            "ageq_share_au": rng.uniform(0, 1), "rec_ag": rng.uniform(0, 1),
            "rec_au": rng.uniform(0, 1), "fraser": rng.uniform(0, 100),
            "infrastructure": rng.uniform(0, 1), "depth": rng.uniform(0, 1)}
        d = ve.calculate_technical_quality("alpha")
        assert 0.55 <= d["tq"] <= 1.70
    unconfigured = ve.calculate_technical_quality("never-configured")
    assert 0.55 <= unconfigured["tq"] <= 1.70
    assert unconfigured["project_configured"] is False and unconfigured["defaults_used"]


# ------------------------------------------------------------------ triangulation
def test_spear_intrinsic_is_convex_combination_of_legs(ve):
    """Claim: the triangulation weights are a probability vector, so v_intrinsic lies BETWEEN the
    min and max leg — the blend can never invent value outside its own legs."""
    rng = random.Random(9)
    for _ in range(20):
        kw = _base_kwargs()
        kw.update(peer_ev_oz=rng.uniform(0.2, 5), spot_ag=rng.uniform(10, 80),
                  capital_discount_factor=rng.uniform(0.4, 1.0), real_yield=rng.uniform(-1, 4),
                  silver_vol=rng.uniform(0.1, 0.9), forensic_penalty=rng.uniform(0.5, 1.0))
        d = ve.calculate_spear_intrinsic(**kw)
        ws = d["weights"]
        assert abs(sum(ws.values()) - 1.0) < 2e-3           # rounded to 3dp in the payload
        assert all(v >= 0 for v in ws.values())
        legs = d["legs"]
        assert min(legs.values()) - 1e-6 <= d["v_intrinsic"] <= max(legs.values()) + 1e-6
        assert d["v_intrinsic"] >= 0


def test_spear_intrinsic_monotone_in_peer_multiple(ve):
    """Claim: a richer peer comp can only raise (never lower) intrinsic — the market leg is linear
    in peer EV/oz and every other leg is independent of it."""
    kw = _base_kwargs()
    vals = []
    for peer in (0.4, 0.8, 1.2, 2.0, 3.5):
        kw["peer_ev_oz"] = peer
        vals.append(ve.calculate_spear_intrinsic(**kw)["v_intrinsic"])
    assert all(a <= b + 1e-9 for a, b in zip(vals, vals[1:]))


def test_mos_ledger_cumulative_is_the_product_of_factors(ve):
    """Claim: the margin-of-safety ledger's cumulative column reproduces the running product of its
    own factor column (the gross→net chain audits)."""
    d = ve.calculate_spear_intrinsic(**_base_kwargs())
    cum = 1.0
    for row in d["mos_ledger"]:
        cum *= row["factor"]
        assert abs(row["cumulative"] - cum) <= 0.005 * max(1.0, abs(cum))


def test_scenario_range_orders_bear_base_bull(ve):
    """Claim: every scenario lever (silver, peer multiple, real yield, discovery prob) moves value
    the same direction it moves in, so the composed range must order bear ≤ base ≤ bull — and every
    tornado bar must have low ≤ high."""
    rng = random.Random(10)
    for _ in range(10):
        kw = _base_kwargs()
        kw.update(peer_ev_oz=rng.uniform(0.3, 4), spot_ag=rng.uniform(12, 70),
                  real_yield=rng.uniform(-1, 4), dynamic_aisc=rng.uniform(5, 45))
        r = ve.run_intrinsic_scenarios(kw, silver_vol=rng.uniform(0.15, 0.8))
        assert r["bear"] <= r["base"] + 1e-6 <= r["bull"] + 2e-6
        for bar in r["tornado"]:
            assert bar["low"] <= bar["high"]
