"""Mined invariants — regime posture + the book-factor lens (F1 of docs/FABLE_INTEGRATION.md).

Property tests: the posture dial's bounds/monotonicity/coherence, and the book-factor gauges'
symmetry, bounds, and conservation. Seeded randomized sweeps, plain pytest.
"""
import random

import book_factor
import regime_posture as rp


def _rand_inputs(rng):
    return dict(
        mri=rng.choice([None, rng.uniform(-20, 120)]),
        net_tilt=rng.choice([None, "", "risk_on", "risk_off", "Risk-On", "garbage", "balanced"]),
        real_yield=rng.choice([None, rng.uniform(-3, 8)]),
        dxy_mom=rng.choice([None, rng.uniform(-5, 5)]),
    )


# ------------------------------------------------------------------ posture
def test_posture_cap_always_bounded_and_headwind_coherent():
    """Claim: for ANY input combination the cap stays in [0.5, 1.25] and the headwind flag is
    exactly cap < 1 — the dial can never leave its rails or contradict its own label."""
    rng = random.Random(11)
    for _ in range(200):
        p = rp.compute(**_rand_inputs(rng))
        assert rp.CAP_FLOOR <= p["cap"] <= rp.CAP_CEIL
        assert p["headwind"] == (p["cap"] < 1.0)
        assert p["code"] in ("spear_exploit", "balanced", "defensive")


def test_posture_cap_monotone_in_each_headwind():
    """Claim: worsening any single regime signal (MRI up, real yield up, dollar bid up) never
    RAISES the cap — the dial only tightens on deterioration."""
    rng = random.Random(12)
    for _ in range(60):
        base = dict(mri=rng.uniform(0, 100), net_tilt=None,
                    real_yield=rng.uniform(-2, 6), dxy_mom=rng.uniform(-3, 3))
        for key, delta in (("mri", rng.uniform(0, 40)), ("real_yield", rng.uniform(0, 3)),
                           ("dxy_mom", rng.uniform(0, 2))):
            worse = dict(base)
            worse[key] = base[key] + delta
            assert rp.compute(**worse)["cap"] <= rp.compute(**base)["cap"] + 1e-9


def test_posture_explicit_tilt_beats_mri_and_neutral_default():
    """Claim: an explicit regime tilt overrides the MRI fallback for the STANCE; no signals at all
    is exactly neutral (BALANCED, 1.0x, no drivers)."""
    assert rp.compute(mri=10.0, net_tilt="risk_off")["code"] == "defensive"
    assert rp.compute(mri=90.0, net_tilt="risk_on")["code"] == "spear_exploit"
    p = rp.compute()
    assert (p["code"], p["cap"], p["drivers"]) == ("balanced", 1.0, [])


def test_posture_defensive_never_carries_a_lifted_cap_from_mri_alone():
    """Claim: when MRI alone drives the read, a DEFENSIVE stance (MRI > 60) implies the MRI cap
    adjustment is negative — stance and dial move together, never argue."""
    rng = random.Random(13)
    for _ in range(50):
        mri = rng.uniform(60.01, 120)
        p = rp.compute(mri=mri)
        assert p["code"] == "defensive"
        mri_drv = next(d for d in p["drivers"] if d["name"] == "MRI")
        assert mri_drv["cap_adj"] < 0


# ------------------------------------------------------------------ factor concentration
def _corr_matrix(rng, tks, orientation="upper"):
    m = {}
    vals = {}
    for i, a in enumerate(tks):
        for b in tks[i + 1:]:
            vals[(a, b)] = round(rng.uniform(-1, 1), 3)
    for (a, b), v in vals.items():
        if orientation == "upper":
            m.setdefault(a, {})[b] = v
        else:
            m.setdefault(b, {})[a] = v
    return m, vals


def test_factor_concentration_orientation_invariant():
    """Claim: the read must not depend on which triangle of the correlation matrix was stored —
    ρ(a,b) is symmetric and the lookup must honour that."""
    rng = random.Random(14)
    tks = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]
    up, _ = _corr_matrix(rng, tks, "upper")
    lo_m, _ = _corr_matrix(random.Random(14), tks, "lower")
    a = book_factor.factor_concentration(up, tks)
    b = book_factor.factor_concentration(lo_m, tks)
    assert a["avg_pairwise"] == b["avg_pairwise"]
    assert a["spear_corr"] == b["spear_corr"]


def test_factor_concentration_bounds_and_flag_threshold():
    """Claim: avg pairwise ρ stays in [-1, 1]; a ballast is flagged iff its spear ρ clears the
    configured threshold — no phantom flags, none missed."""
    rng = random.Random(15)
    tks = ["AGA.V", "GROY", "GMX.TO", "URC.TO"]
    for _ in range(30):
        m, _ = _corr_matrix(rng, tks)
        out = book_factor.factor_concentration(m, tks)
        assert -1.0 <= out["avg_pairwise"] <= 1.0
        flagged = {f["ticker"] for f in out["flags"]}
        expected = {t for t, c in out["spear_corr"].items() if c >= 0.85}
        assert flagged == expected


def test_factor_concentration_degrades_without_data():
    out = book_factor.factor_concentration({}, ["AGA.V", "GROY"])
    assert out["available"] is False and out["avg_pairwise"] is None and out["flags"] == []


# ------------------------------------------------------------------ scenario coverage
def _scenario_result(rng, n_names=4, n_scen=5):
    scen = [chr(ord("A") + i) for i in range(n_scen)]
    raw = [rng.random() for _ in scen]
    tot = sum(raw)
    weights = {s: r / tot for s, r in zip(scen, raw)}
    rankings = [{"ticker": f"T{i}", "book_weight": rng.uniform(0.05, 0.5),
                 "payoffs": {s: rng.uniform(-0.5, 0.8) for s in scen}} for i in range(n_names)]
    return {"weights": weights, "rankings": rankings, "scenarios": {}}


def test_scenario_coverage_conserves_probability_mass():
    """Claim: with scenario weights summing to 1, uncovered + covered = 1 and uncovered equals the
    sum of the holes' own weights — the coverage ledger conserves probability."""
    rng = random.Random(16)
    for _ in range(30):
        sr = _scenario_result(rng)
        out = book_factor.scenario_coverage(sr)
        assert 0.0 <= out["uncovered_weight"] <= 1.0 + 1e-6
        assert abs(out["uncovered_weight"] + out["covered_weight"] - 1.0) <= 2e-3
        assert abs(out["uncovered_weight"] - sum(h["weight"] for h in out["holes"])) <= 2e-3


def test_scenario_coverage_status_consistent_with_payoff():
    """Claim: every scenario's status is exactly the classification of its book payoff against the
    covered threshold (covered ≥ 0.05 > thin ≥ 0 > headwind)."""
    rng = random.Random(17)
    sr = _scenario_result(rng)
    out = book_factor.scenario_coverage(sr)
    for s, row in out["by_scenario"].items():
        bp = row["book_payoff"]
        want = "covered" if bp >= 0.05 else "thin" if bp >= 0 else "headwind"
        assert row["status"] == want


def test_scenario_coverage_empty_book_is_na_not_zero():
    out = book_factor.scenario_coverage({"weights": {"A": 1.0}, "rankings": []})
    assert out["available"] is False and out["covered_weight"] is None


# ------------------------------------------------------------------ coverage depth (width · depth · priority)
def test_scenario_coverage_depth_fields_recompute():
    """Claim: expected_payoff = Σ w·payoff, expected_drag = Σ w·min(0,payoff) (so drag ≤ 0 and
    drag ≤ expected_payoff), and deepest_hole is the scenario with the largest single w·payoff loss."""
    rng = random.Random(18)
    for _ in range(20):
        sr = _scenario_result(rng)
        out = book_factor.scenario_coverage(sr)
        w = sr["weights"]
        exp = sum(w[s] * out["by_scenario"][s]["book_payoff"] for s in w)
        drag = sum(w[s] * min(0.0, out["by_scenario"][s]["book_payoff"]) for s in w)
        assert abs(out["expected_payoff"] - exp) <= 2e-3
        assert abs(out["expected_drag"] - drag) <= 2e-3
        assert out["expected_drag"] <= 0.0 + 1e-9
        assert out["expected_drag"] <= out["expected_payoff"] + 1e-9
        losses = {s: w[s] * min(0.0, out["by_scenario"][s]["book_payoff"]) for s in w}
        if min(losses.values()) < 0:
            assert losses[out["deepest_hole"]] == min(losses.values())
        else:
            assert out["deepest_hole"] is None


def test_scenario_coverage_read_carries_depth_when_holed():
    rng = random.Random(19)
    sr = _scenario_result(rng)
    out = book_factor.scenario_coverage(sr)
    if out["holes"]:
        assert "drag" in out["read"] and "deepest" in out["read"]
