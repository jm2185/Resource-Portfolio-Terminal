"""
Tests for the provenance-aware data layer (market_data.py + research_cache.py).

Offline + deterministic: Yahoo HTTP is monkeypatched and FMP is a stub, so no network is
touched. Asserts the two non-negotiables — every field is provenance-tagged, and a field that
cannot be sourced is ABSENT/unavailable rather than a fabricated default (no hardcodes).
"""
from __future__ import annotations

import os
import tempfile
import unittest

import market_data
import research_cache


class _StubFMP:
    """Minimal FMPClient stand-in: profile() returns the engine's {data: {...}} shape."""

    def __init__(self, data):
        self._data = data

    def profile(self, ticker):
        return {"data": dict(self._data)} if self._data else {"data": None}


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        # canned Yahoo chart payload
        self._yh = {"chart": {"result": [{"meta": {"regularMarketPrice": 0.65, "currency": "CAD",
                                                    "chartPreviousClose": 0.71}}]}}
        market_data._http_json = lambda url, timeout=8.0: self._yh   # monkeypatch network

    def tearDown(self):
        for p in (self.tmp, self.tmp + ".tmp"):
            if os.path.exists(p):
                os.remove(p)

    def test_snapshot_merges_and_tags_provenance(self):
        fmp = _StubFMP({"marketCap": 112_644_909, "beta": 1.24, "range": "0.58-1.34",
                        "sector": "Basic Materials", "exchange": "TSXV", "companyName": "Silver47"})
        md = market_data.MarketData(fmp=fmp, cache_path=self.tmp)
        s = md.snapshot("AGA.V")
        self.assertEqual(s["fields"]["price"], 0.65)
        self.assertEqual(s["sources"]["price"], "yahoo")             # Yahoo primary
        self.assertEqual(s["sources"]["market_cap"], "fmp")          # FMP secondary
        self.assertAlmostEqual(s["fields"]["change_pct"], round((0.65 / 0.71 - 1) * 100, 2))
        self.assertIn("derived", s["sources"]["shares_out"])         # shares = mcap/price, tagged
        self.assertEqual(s["fields"]["shares_out"], round(112_644_909 / 0.65))

    def test_missing_data_is_unavailable_not_faked(self):
        # No FMP coverage + no Yahoo price -> fields absent, sources == 'unavailable' (NO hardcode)
        market_data._http_json = lambda url, timeout=8.0: {"chart": {"result": [{"meta": {}}]}}
        md = market_data.MarketData(fmp=_StubFMP(None), cache_path=self.tmp)
        s = md.snapshot("NONE.V")
        self.assertNotIn("price", s["fields"])
        self.assertEqual(s["sources"]["price"], "unavailable")
        self.assertEqual(s["sources"]["market_cap"], "unavailable")

    def test_momentum_normalized(self):
        # a +10% period move (full_move default) -> +1.0 momentum signal
        market_data._http_json = lambda url, timeout=8.0: {
            "chart": {"result": [{"indicators": {"quote": [{"close": [100.0, 105.0, 110.0]}]}}]}}
        md = market_data.MarketData(cache_path=self.tmp)
        self.assertEqual(md.momentum("URNM"), 1.0)

    def test_cache_first_no_refetch(self):
        calls = {"n": 0}

        def counting(url, timeout=8.0):
            calls["n"] += 1
            return self._yh
        market_data._http_json = counting
        md = market_data.MarketData(fmp=_StubFMP({"marketCap": 1}), cache_path=self.tmp, price_ttl=999)
        md.snapshot("AGA.V"); md.snapshot("AGA.V")
        self.assertEqual(calls["n"], 1)                              # second snapshot served from cache


class ResearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.rc = research_cache.ResearchCache(path=self.tmp)

    def tearDown(self):
        for p in (self.tmp, self.tmp + ".tmp"):
            if os.path.exists(p):
                os.remove(p)

    def test_set_get_provenance(self):
        self.rc.set("AGA.V", "aisc_per_oz", 14.2, "https://sedar/PEA", "2023-06-15", "high", "Red Mtn PEA")
        e = self.rc.get("AGA.V", "aisc_per_oz")
        self.assertEqual(e["value"], 14.2)
        self.assertEqual(e["source"], "https://sedar/PEA")
        self.assertEqual(e["confidence"], "high")
        self.assertIsInstance(self.rc.age_days("AGA.V", "aisc_per_oz"), int)

    def test_absent_returns_none_and_default(self):
        self.assertIsNone(self.rc.get("AGA.V", "nav_per_share"))     # never a fake
        self.assertEqual(self.rc.value("AGA.V", "nav_per_share", default="pending"), "pending")

    def test_bad_confidence_normalized(self):
        self.rc.set("X", "f", 1, "u", "2024-01-01", confidence="bogus")
        self.assertEqual(self.rc.get("X", "f")["confidence"], "med")


if __name__ == "__main__":
    unittest.main()
