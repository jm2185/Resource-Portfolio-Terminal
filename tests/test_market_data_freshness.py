"""
Tests for market_data.resolve_freshness — the provenance-aware price resolver that fixes the
silent-stale holding-price bug (daily bulk bar lags / goes NaN on the latest session, and the old
df['Close'].dropna().iloc[-1] served a 1-2 day-old close as if LIVE).

Pins the contract:
  * a live intraday quote is preferred and is FRESH;
  * a daily close dated TODAY is fresh; an older one is returned but FLAGGED stale with its real date;
  * the GROY case (latest bar NaN -> dropna yields the prior session) is served STALE, never as live;
  * with no data, last-good cache is used (stale), else price is None (honest absence).
"""
import datetime
import unittest

import market_data as md

TODAY = datetime.date(2026, 6, 17)


class ResolveFreshnessTests(unittest.TestCase):
    def test_intraday_quote_preferred_and_fresh(self):
        r = md.resolve_freshness(daily_closes=[(datetime.date(2026, 6, 15), 2.98)],
                                 intraday=3.05, today=TODAY)
        self.assertEqual(r["price"], 3.05)
        self.assertFalse(r["stale"])
        self.assertEqual(r["source"], "yahoo:intraday")
        self.assertEqual(r["as_of"], "2026-06-17")

    def test_todays_daily_close_is_fresh(self):
        r = md.resolve_freshness(
            daily_closes=[(datetime.date(2026, 6, 16), 0.62), (TODAY, 0.63)],
            intraday=None, today=TODAY)
        self.assertEqual(r["price"], 0.63)
        self.assertFalse(r["stale"])
        self.assertEqual(r["source"], "yahoo:daily")

    def test_groy_case_nan_latest_served_but_flagged_stale(self):
        # GROY: 06-16 Close was NaN -> dropna gives 06-15; no intraday -> usable but STALE, not LIVE.
        r = md.resolve_freshness(
            daily_closes=[(datetime.date(2026, 6, 12), 2.88), (datetime.date(2026, 6, 15), 2.98)],
            intraday=None, today=TODAY)
        self.assertEqual(r["price"], 2.98)
        self.assertTrue(r["stale"])
        self.assertEqual(r["as_of"], "2026-06-15")

    def test_nonpositive_intraday_ignored_falls_to_daily(self):
        r = md.resolve_freshness(daily_closes=[(datetime.date(2026, 6, 15), 2.98)],
                                 intraday=0.0, today=TODAY)
        self.assertEqual(r["price"], 2.98)
        self.assertTrue(r["stale"])           # fell through to the stale daily close

    def test_no_data_uses_last_good_cache_stale(self):
        r = md.resolve_freshness(daily_closes=[], intraday=None,
                                 last_good={"price": 2.90, "as_of": "2026-06-10"}, today=TODAY)
        self.assertEqual(r["price"], 2.90)
        self.assertTrue(r["stale"])
        self.assertEqual(r["source"], "cache:last-good")

    def test_nothing_available_returns_none(self):
        r = md.resolve_freshness(daily_closes=[], intraday=None, last_good=None, today=TODAY)
        self.assertIsNone(r["price"])
        self.assertTrue(r["stale"])
        self.assertEqual(r["source"], "unavailable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
