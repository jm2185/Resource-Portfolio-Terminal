"""tail_dependence — the crash-honest ballast read. Synthetic copulas with KNOWN tail behaviour
(independent → λ̂_L ≈ q; comonotonic → λ̂_L ≈ 1; calm-diversifier/stress-beta mixture in between),
the small-n withhold floors, and the alignment discipline (mismatched listing calendars never pair
different days)."""
import random
from datetime import date, timedelta

import tail_dependence as td


def _dates(n, start=date(2025, 1, 6)):
    """n consecutive weekdays as iso strings."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _series(dates, returns, p0=10.0):
    px, out = p0, []
    for ds, r in zip(dates, returns):
        px *= (1.0 + r)
        out.append((ds, round(px, 6)))
    return out


def _gauss_pair(n, rho, seed, crash_coupled=False):
    """Paired returns: bivariate normal via Cholesky. With crash_coupled, the second series copies
    the first on its worst days — a calm diversifier wearing spear-beta in stress."""
    rng = random.Random(seed)
    xs = [rng.gauss(0, 0.02) for _ in range(n)]
    zs = [rng.gauss(0, 0.02) for _ in range(n)]
    ys = [rho * x + (1 - rho ** 2) ** 0.5 * z for x, z in zip(xs, zs)]
    if crash_coupled:
        # amplified co-crash: on the spear's worst-decile days the ballast falls TWICE as hard, so
        # those days are unambiguously the ballast's own worst decile too (λ_L → 1 by construction)
        cut = sorted(xs)[int(0.10 * n)]
        ys = [2.0 * x if x <= cut else y for x, y in zip(xs, ys)]
    return xs, ys


# ---------------------------------------------------------------- lower_tail_dependence
def test_independent_pair_lambda_near_q():
    xs, ys = _gauss_pair(2000, rho=0.0, seed=7)
    est = td.lower_tail_dependence(xs, ys, q=0.10, min_obs=100, min_tail_n=10)
    assert est is not None
    # independence → P(B tail | A tail) ≈ q; generous band for sampling noise
    assert 0.02 <= est["lam"] <= 0.22
    assert est["n_tail"] >= 190              # ~10% of 2000


def test_comonotonic_pair_lambda_near_one():
    xs = [random.Random(11).gauss(0, 0.02) for _ in range(1000)]
    est = td.lower_tail_dependence(xs, list(xs), q=0.10, min_obs=100, min_tail_n=10)
    assert est is not None and est["lam"] == 1.0


def test_crash_coupled_pair_beats_its_calm_rho():
    """The failure mode the module exists for: modest calm ρ, λ̂_L ≈ 1 (co-crashes every time)."""
    xs, ys = _gauss_pair(2000, rho=0.30, seed=13, crash_coupled=True)
    est = td.lower_tail_dependence(xs, ys, q=0.10, min_obs=100, min_tail_n=10)
    rho = td.pearson(xs, ys)
    assert est is not None and est["lam"] >= 0.95
    assert rho < 0.75                        # the calm read stays far below the tail read
    assert est["lam"] - rho >= 0.25          # the stress gap is visible


def test_lambda_bounded_and_counts_consistent():
    for seed in range(5):
        xs, ys = _gauss_pair(400, rho=random.Random(seed).uniform(-0.5, 0.9), seed=seed)
        est = td.lower_tail_dependence(xs, ys, q=0.10, min_obs=100, min_tail_n=10)
        assert est is not None
        assert 0.0 <= est["lam"] <= 1.0
        assert 0 <= est["n_joint"] <= est["n_tail"] <= est["n_obs"]


def test_small_sample_withheld_not_guessed():
    xs, ys = _gauss_pair(60, rho=0.5, seed=3)
    assert td.lower_tail_dependence(xs, ys, q=0.10, min_obs=120, min_tail_n=10) is None
    # a q so small the conditioning set can't reach min_tail_n is withheld too
    xs, ys = _gauss_pair(200, rho=0.5, seed=4)
    assert td.lower_tail_dependence(xs, ys, q=0.01, min_obs=120, min_tail_n=10) is None


# ---------------------------------------------------------------- alignment
def test_align_returns_intersects_calendars():
    ds = _dates(10)
    a = _series(ds, [0.01] * 10)
    b = _series([d for d in ds if d != ds[4]], [0.02] * 9)   # one holiday gap on b's exchange
    ra, rb = td.align_returns(a, b)
    assert len(ra) == len(rb) == 8           # 9 common dates → 8 return pairs
    for r in ra:
        assert abs(r - 0.01) < 1e-5 or r > 0.019   # the gap-spanning pair compounds two days


def test_align_returns_drops_bad_closes():
    ds = _dates(5)
    a = list(zip(ds, [10, 10.1, None, 10.2, 10.3]))
    b = list(zip(ds, [5, 5.1, 5.2, 0.0, 5.3]))               # None and non-positive both dropped
    ra, rb = td.align_returns(a, b)
    assert len(ra) == len(rb) == 2           # common good dates: d0,d1,d4 → 2 pairs


# ---------------------------------------------------------------- book_tail_read
def _book_closes(n=300, ballast_rho=0.3, crash_coupled=False, seed=21):
    ds = _dates(n + 1)
    xs, ys = _gauss_pair(n, rho=ballast_rho, seed=seed, crash_coupled=crash_coupled)
    return {"AGA.V": _series(ds[: n + 1], [0.0] + xs), "GROY": _series(ds[: n + 1], [0.0] + ys)}


def test_book_read_flags_the_crash_coupled_ballast():
    closes = _book_closes(crash_coupled=True)
    out = td.book_tail_read(closes, ["AGA.V", "GROY"], spear="AGA.V")
    assert out["available"] is True
    assert out["per_name"]["GROY"]["lam"] >= 0.9
    assert any(f["id"] == "crash_correlated" and f["ticker"] == "GROY" for f in out["flags"])


def test_book_read_clean_on_a_genuine_diversifier():
    closes = _book_closes(ballast_rho=0.0, crash_coupled=False)
    out = td.book_tail_read(closes, ["AGA.V", "GROY"], spear="AGA.V")
    assert out["available"] is True
    assert out["per_name"]["GROY"]["lam"] <= 0.3
    assert out["flags"] == []


def test_book_read_degrades_honestly_on_thin_history():
    closes = _book_closes(n=40)
    out = td.book_tail_read(closes, ["AGA.V", "GROY"], spear="AGA.V")
    assert out["available"] is False
    assert out["insufficient"] and out["insufficient"][0]["ticker"] == "GROY"
    assert "n/a" in out["read"]


def test_book_read_empty_inputs():
    out = td.book_tail_read({}, [], spear="AGA.V")
    assert out["available"] is False and out["flags"] == []


def test_config_block_overrides_defaults():
    closes = _book_closes(crash_coupled=True)
    cfg = {"book_factor": {"tail_crash_min": 1.01}}          # unreachable → no crash flag
    out = td.book_tail_read(closes, ["AGA.V", "GROY"], spear="AGA.V", config=cfg)
    assert not any(f["id"] == "crash_correlated" for f in out["flags"])


# ---------------------------------------------------------------- closes_from_history
class _FakeHistory:
    def __init__(self, data):
        self.data = data

    def window(self, ticker, start, end):
        return [(d, c) for d, c in self.data.get(str(ticker).upper(), [])
                if start.isoformat() <= d <= end.isoformat()]


def test_closes_from_history_windows_and_tolerates_missing():
    ds = _dates(5, start=date(2026, 6, 1))
    hist = _FakeHistory({"AGA.V": list(zip(ds, [1, 2, 3, 4, 5]))})
    out = td.closes_from_history(hist, ["AGA.V", "MISSING"], lookback_days=365,
                                 today=date(2026, 8, 1))
    assert len(out["AGA.V"]) == 5 and out["MISSING"] == []
