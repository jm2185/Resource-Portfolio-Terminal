"""Mined invariants — the calibration flywheel (F1 of docs/FABLE_INTEGRATION.md).

Property tests over decision grading and Brier scoring: sign conventions, leg-ladder ordering,
probability bounds, and the seed clamp. A failure means the flywheel's math broke a first-principles
property — the track record itself would be corrupted, so these run on every commit.
"""
import random

import calibration as cal


def _decision(rng, side_verdict="ACCUMULATE"):
    p0 = rng.uniform(1.0, 50.0)
    floor = p0 * rng.uniform(0.4, 0.95)
    base = p0 * rng.uniform(1.0, 1.6)
    bull = base * rng.uniform(1.05, 2.5)
    return {"ticker": "T", "price": p0, "verdict": side_verdict, "archetype": "option_convexity",
            "rho": rng.uniform(0.1, 6.0), "phi": rng.uniform(0.3, 2.0),
            "legs": {"floor": floor, "base": base, "bull": bull}}


# ------------------------------------------------------------------ score_outcome
def test_signed_return_sign_convention_by_side():
    """Claim: for a long the signed return IS the realized return; for an avoid it is its negation
    (a fall validates the pass) — and the win/loss/scratch label follows the signed value."""
    rng = random.Random(21)
    for _ in range(60):
        d = _decision(rng)
        rp = d["price"] * rng.uniform(0.3, 3.0)
        long_s = cal.score_outcome(dict(d, side="long"), rp)
        avoid_s = cal.score_outcome(dict(d, side="avoid"), rp)
        assert abs(long_s["signed_return"] + avoid_s["signed_return"]) < 1e-9
        for s in (long_s, avoid_s):
            if s["result"] == "scratch":
                assert abs(s["signed_return"]) < cal.WIN_THRESHOLD
            else:
                assert (s["result"] == "win") == (s["signed_return"] > 0)


def test_leg_hit_respects_the_ladder_order():
    """Claim: leg_hit advances monotonically with the realized price through
    broke_floor → held_floor → above_entry → base → bull, and floor_held agrees with it."""
    order = ["broke_floor", "held_floor", "above_entry", "base", "bull"]
    rng = random.Random(22)
    for _ in range(40):
        d = _decision(rng)
        prices = sorted(d["price"] * rng.uniform(0.2, 3.0) for _ in range(6))
        ranks = []
        for rp in prices:
            s = cal.score_outcome(d, rp)
            ranks.append(order.index(s["leg_hit"]))
            assert s["floor_held"] == (rp >= d["legs"]["floor"])
        assert ranks == sorted(ranks)


def test_implied_breakeven_is_a_probability_decreasing_in_rho():
    """Claim: 1/(1+ρ) ∈ (0, 1] and falls as the asymmetry improves — a better-shaped bet needs a
    LOWER win probability to break even."""
    rng = random.Random(23)
    last = None
    for rho in sorted(rng.uniform(0.0, 10.0) for _ in range(30)):
        d = _decision(rng)
        d["rho"] = rho
        p = cal.score_outcome(d, d["price"] * 1.5)["implied_breakeven_p_vs_floor"]
        assert 0.0 < p <= 1.0
        if last is not None:
            assert p <= last + 1e-9
        last = p


def test_unscorable_decision_is_unscored_never_invented():
    assert cal.score_outcome({"price": None}, 10.0)["status"] == "unscored"
    assert cal.score_outcome({"price": 10.0}, None)["status"] == "unscored"
    assert cal.score_outcome({"price": -1.0}, 10.0)["status"] == "unscored"


# ------------------------------------------------------------------ decision shape
def test_decision_shape_total_and_honest_on_missing():
    """Claim: the shape test is total (never raises) and 'unknown' exactly when NOTHING was frozen
    — a half-frozen bet is judged (thin/well_shaped), not excused."""
    rng = random.Random(24)
    assert cal.decision_shape(None, None) == "unknown"
    for _ in range(50):
        rho = rng.choice([None, rng.uniform(-1, 8)])
        phi = rng.choice([None, rng.uniform(0, 3)])
        out = cal.decision_shape(rho, phi, rng.choice([None, "option_convexity", "junk"]))
        if rho is None and phi is None:
            assert out == "unknown"
        else:
            assert out in ("well_shaped", "thin")


# ------------------------------------------------------------------ brier
def test_brier_bounds_and_perfect_scores():
    """Claim: every Brier component lies in [0, 1]; certainty scored against its own outcome is 0,
    against the opposite outcome 1."""
    rng = random.Random(25)
    for _ in range(60):
        fs = [rng.random() for _ in range(rng.randint(1, 8))]
        out = cal.brier_score(fs, rng.choice(["win", "loss", 1, 0]))
        assert out is not None
        assert 0.0 <= out["brier"] <= 1.0 and 0.0 <= out["final_brier"] <= 1.0
        assert -1.0 <= out["calibration_gap"] <= 1.0
    assert cal.brier_score([1.0], "win")["brier"] == 0.0
    assert cal.brier_score([1.0], "loss")["brier"] == 1.0


def test_brier_refuses_unresolvable_outcomes_and_clamps_forecasts():
    """Claim: a scratch/unknown outcome is unscoreable (None, never a guess); out-of-range
    forecasts are clamped into [0,1] rather than corrupting the score."""
    assert cal.brier_score([0.7], "scratch") is None
    assert cal.brier_score([0.7], None) is None
    assert cal.brier_score([], "win") is None
    out = cal.brier_score([-0.5, 1.7], "win")
    assert 0.0 <= out["brier"] <= 1.0


def test_seed_confidence_always_clamped_and_labeled():
    """Claim: an engine-seeded confidence is always in [0.05, 0.95] and always carries seeded=True —
    a prior can never masquerade as an operator reading or as certainty."""
    rng = random.Random(26)
    for _ in range(40):
        d = {"archetype": rng.choice([None, "junk", "option_convexity", "asset_light_yield"]),
             "rho": rng.choice([None, rng.uniform(0.0, 20.0)])}
        s = cal.seed_confidence(d)
        if s is not None:
            assert 0.05 <= s["confidence"] <= 0.95
            assert s["seeded"] is True and s["basis"].startswith("engine seed")


# ------------------------------------------------------------------ infer_side totality
def test_infer_side_total_and_long_only_default():
    """Claim: every string maps to long or avoid (the book is long-only; unknown → long), so no
    verdict can ever escape grading with an unmapped side."""
    rng = random.Random(27)
    words = ["", None, "ACCUMULATE", "AVOID", "TRIM", "PRESS", "EXIT NOW", "gibberish", "DE-RISK"]
    for w in words + ["".join(rng.choice("ABC XYZ") for _ in range(8)) for _ in range(20)]:
        assert cal.infer_side(w) in ("long", "avoid")
