"""The FRED net-liquidity / breakeven fetch must not re-hammer a blocked endpoint every macro cycle:
a failure is negatively cached (~30min) and guarded by a single-series circuit-breaker. This is the
perf-regression fix — un-cached failures + five sequential 10s timeouts were stalling the regime /
holdings build ~50s/cycle when FRED is unreachable."""
import types
import unittest

import engine


class _MemCache:
    """In-memory stand-in for the disk cache (no .cache/ files, no real clock). ``age_hours`` is how
    old the single stored entry is pretended to be, so a TTL load can be simulated."""

    def __init__(self):
        self.store = {}
        self.age_hours = 0.0

    def load(self, key, max_age_hours):
        if key in self.store and self.age_hours < max_age_hours:
            return self.store[key]
        return None

    def save(self, key, data):
        self.store[key] = data
        self.age_hours = 0.0


def _stub(fred_recent):
    o = types.SimpleNamespace()
    o._fred_recent = fred_recent
    o._latest_and_prior = engine.CommodityExMonitor._latest_and_prior   # the staticmethod, unbound
    return o


_FETCH = engine.CommodityExMonitor._fetch_macro_quantities_free


class MacroQuantitiesCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = _MemCache()
        self._saved = (engine._load_from_disk_cache, engine._save_to_disk_cache)
        engine._load_from_disk_cache = self.cache.load
        engine._save_to_disk_cache = self.cache.save

    def tearDown(self):
        engine._load_from_disk_cache, engine._save_to_disk_cache = self._saved

    def test_blocked_fred_probes_once_then_negative_caches(self):
        calls = []

        def fred(series):
            calls.append(series)
            return []                                    # blocked: every series returns empty
        obj = _stub(fred)
        # 1st call: the circuit-breaker probes ONE series, bails, negatively caches
        self.assertIsNone(_FETCH(obj))
        self.assertEqual(calls, ["WALCL"])               # ONE request, not five
        self.assertIsNone(self.cache.store["macro_quantities_free"]["result"])   # negative cached
        # 2nd call inside the retry window: served from the negative cache, NO new request
        self.assertIsNone(_FETCH(obj))
        self.assertEqual(calls, ["WALCL"])               # still just the one

    def test_blocked_retries_after_the_negative_window(self):
        calls = []

        def fred(series):
            calls.append(series)
            return []
        obj = _stub(fred)
        _FETCH(obj)                                      # probe #1 → negative cache
        self.assertEqual(len(calls), 1)
        self.cache.age_hours = 1.0                       # advance past the ~30min negative window
        _FETCH(obj)                                      # re-probes (the endpoint may have recovered)
        self.assertEqual(len(calls), 2)

    def test_success_fetches_all_then_serves_from_cache(self):
        calls = []

        def fred(series):
            calls.append(series)
            return [("2026-06-01", 100.0), ("2026-06-22", 110.0)]    # non-empty → reachable
        obj = _stub(fred)
        res = _FETCH(obj)
        self.assertIsNotNone(res)
        self.assertEqual(set(calls), {"WALCL", "WDTGAL", "RRPONTSYD", "DGS10", "DFII10"})   # all five
        self.assertIsNotNone(self.cache.store["macro_quantities_free"]["result"])
        # within 6h: served from the positive cache, no new requests
        calls.clear()
        self.assertIsNotNone(_FETCH(obj))
        self.assertEqual(calls, [])


class FredPointsParseTests(unittest.TestCase):
    """The OpenBB-first path parses a date-indexed FRED-series DataFrame into (date_str, value) points
    — so Net-Liquidity/Breakeven populate where the raw CSV host is blocked but OpenBB works."""

    def test_parses_date_indexed_frame(self):
        import pandas as pd
        df = pd.DataFrame({"WALCL": [100.0, 110.0, 120.0]},
                          index=pd.to_datetime(["2026-05-01", "2026-06-01", "2026-06-22"]))
        self.assertEqual(engine.CommodityExMonitor._fred_points_from_df(df),
                         [("2026-05-01", 100.0), ("2026-06-01", 110.0), ("2026-06-22", 120.0)])

    def test_empty_or_none_is_empty(self):
        import pandas as pd
        self.assertEqual(engine.CommodityExMonitor._fred_points_from_df(None), [])
        self.assertEqual(engine.CommodityExMonitor._fred_points_from_df(pd.DataFrame()), [])

    def test_tail_caps_rows(self):
        import pandas as pd
        df = pd.DataFrame({"x": list(range(200))}, index=pd.date_range("2020-01-01", periods=200))
        self.assertEqual(len(engine.CommodityExMonitor._fred_points_from_df(df, max_rows=5)), 5)


if __name__ == "__main__":
    unittest.main()
