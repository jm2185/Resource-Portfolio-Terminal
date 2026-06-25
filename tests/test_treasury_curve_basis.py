"""
Tests for the ONE-BASIS treasury curve (engine._fetch_treasury_curve_free + _bill_discount_to_bey).

Audit fix (rates-desk critique): the 3M ^IRX bank-discount quote is converted to a bond-equivalent
yield, and the 2Y prefers CASH (FRED DGS2) over the 2YY=F future — so the 2s10s steepener that drives
the scenario-B tilt is cash-vs-cash, not a cash-vs-futures basis. Pure + offline: the BEY math is a
static function; the cash-primary preference runs with a fake `self` and a stubbed yfinance (no network).
"""
import sys
import types
import unittest

try:                                          # engine pulls heavy deps (yfinance/pandas/fastapi/uvicorn);
    import engine                             # skip cleanly where they're absent — the logic is exercised
    CEM = engine.CommodityExMonitor           # in CI where the project deps are installed.
    _ENGINE_OK = True
except Exception as _e:                       # noqa: BLE001 — any import-time failure means "deps absent"
    _ENGINE_OK = False
    _ENGINE_ERR = _e


@unittest.skipUnless(_ENGINE_OK, "engine import unavailable (heavy deps not installed)")
class BillDiscountToBeyTests(unittest.TestCase):
    def test_known_conversion_uplift(self):
        # 13-week bill at a 4.33% discount → ~4.439% bond-equivalent (≈ +11bp), the standard identity.
        self.assertAlmostEqual(CEM._bill_discount_to_bey(4.33, days=91), 4.439, places=3)

    def test_bey_exceeds_discount_for_positive_rates(self):
        for d in (1.0, 2.5, 4.33, 5.5):
            self.assertGreater(CEM._bill_discount_to_bey(d), d)        # BEY > discount, always

    def test_out_of_range_returns_input_unchanged(self):
        self.assertEqual(CEM._bill_discount_to_bey(0.0), 0.0)          # zero → unchanged
        self.assertEqual(CEM._bill_discount_to_bey(30.0), 30.0)        # >25% band → not transformed
        self.assertEqual(CEM._bill_discount_to_bey(-1.0), -1.0)        # negative → unchanged

    def test_bad_input_is_none_never_crashes(self):
        self.assertIsNone(CEM._bill_discount_to_bey(None))
        self.assertIsNone(CEM._bill_discount_to_bey("abc"))


class _FakeSelf:
    """Minimal stand-in for CommodityExMonitor so the fetch logic runs without constructing the engine.
    Resolves the static converter lazily (call time, not class-definition time) so this module still
    imports where the engine's deps are absent and the live tests are skipped."""

    def __init__(self, dgs2):
        self._dgs2 = dgs2

    def _bill_discount_to_bey(self, *a, **k):
        return CEM._bill_discount_to_bey(*a, **k)

    def _fred_latest(self, series_id):
        return self._dgs2 if series_id == "DGS2" else None


@unittest.skipUnless(_ENGINE_OK, "engine import unavailable (heavy deps not installed)")
class CashPrimary2YTests(unittest.TestCase):
    def setUp(self):
        # Force a fresh fetch (no disk cache) + a no-op save; stub yfinance to return NO tenors so the
        # test isolates the 2Y cash-vs-future preference without any network.
        self._cache_fns = (engine._load_from_disk_cache, engine._save_to_disk_cache)
        engine._load_from_disk_cache = lambda *a, **k: None
        engine._save_to_disk_cache = lambda *a, **k: None
        self._yf_prev = sys.modules.get("yfinance")
        fake = types.ModuleType("yfinance")
        fake.download = lambda *a, **k: types.SimpleNamespace(columns=[])   # no .levels → no yf tenors
        sys.modules["yfinance"] = fake

    def tearDown(self):
        engine._load_from_disk_cache, engine._save_to_disk_cache = self._cache_fns
        if self._yf_prev is not None:
            sys.modules["yfinance"] = self._yf_prev
        else:
            sys.modules.pop("yfinance", None)

    def test_2y_prefers_cash_dgs2_and_tags_basis(self):
        res = CEM._fetch_treasury_curve_free(_FakeSelf(3.97))
        self.assertIsNotNone(res)
        self.assertEqual(res["tenors"]["year2"], 3.97)
        self.assertEqual(res["basis"]["year2"], "cash yield (FRED DGS2)")

    def test_no_cash_no_future_yields_none(self):
        res = CEM._fetch_treasury_curve_free(_FakeSelf(None))
        self.assertIsNone(res)                                          # nothing fetched at all → None


@unittest.skipUnless(_ENGINE_OK, "engine import unavailable (heavy deps not installed)")
class FredLatestOpenBBFirstTests(unittest.TestCase):
    """_fred_latest must be OpenBB-FIRST: it delegates to _fred_recent (OpenBB → CSV fallback) and
    takes the newest point — so a firewalled CSV host can't strand DGS2 (the recurring FRED flakiness)."""

    def test_takes_newest_point_from_fred_recent(self):
        class S:
            def _fred_recent(self, sid, max_rows=12):
                return [("2026-06-01", 3.80), ("2026-06-02", 3.97)]    # oldest→newest
        self.assertEqual(CEM._fred_latest(S(), "DGS2"), 3.97)

    def test_empty_points_yield_none(self):
        class S:
            def _fred_recent(self, sid, max_rows=12):
                return []
        self.assertIsNone(CEM._fred_latest(S(), "DGS2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
