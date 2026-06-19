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


class MergeLastGoodTests(unittest.TestCase):
    """The last-good cache carries forward ONLY fresh marks — so a fetch-miss falls back to the last
    REAL price, never the hardcoded fallback. This is what kills the real↔fallback oscillation that
    minted phantom flywheel grades (a stale/fallback mark cached as 'last good' and served back)."""

    def test_fresh_mark_is_recorded(self):
        out = md.merge_last_good({}, {"AGA.V": {"price": 0.57, "stale": False, "as_of": "2026-06-18"}})
        self.assertEqual(out["AGA.V"], {"price": 0.57, "as_of": "2026-06-18"})

    def test_stale_or_fallback_never_overwrites_a_good_mark(self):
        prev = {"AGA.V": {"price": 0.57, "as_of": "2026-06-18"}}
        # a stale daily AND a hardcoded fallback both arrive — neither may clobber the good 0.57
        out = md.merge_last_good(prev, {"AGA.V": {"price": 0.71, "stale": True, "as_of": None}})
        self.assertEqual(out["AGA.V"]["price"], 0.57)            # the oscillation is killed at the source

    def test_a_fresh_mark_updates_the_prior(self):
        prev = {"AGA.V": {"price": 0.57, "as_of": "2026-06-18"}}
        out = md.merge_last_good(prev, {"AGA.V": {"price": 0.60, "stale": False, "as_of": "2026-06-19"}})
        self.assertEqual(out["AGA.V"]["price"], 0.60)           # a real new print does update

    def test_does_not_seed_from_a_stale_first_sight(self):
        # no prior good mark + only a stale/fallback this cycle → last-good stays EMPTY (won't enshrine
        # a fallback as 'good'); the worker still serves the fallback this cycle, flagged stale.
        out = md.merge_last_good({}, {"AGA.V": {"price": 0.71, "stale": True, "as_of": None}})
        self.assertNotIn("AGA.V", out)

    def test_nonpositive_and_missing_are_ignored(self):
        prev = {"GROY": {"price": 3.2, "as_of": "x"}}
        out = md.merge_last_good(prev, {"GROY": {"price": 0.0, "stale": False},
                                        "X": {"price": None, "stale": False}})
        self.assertEqual(out["GROY"]["price"], 3.2)             # bad new values don't corrupt the cache
        self.assertNotIn("X", out)

    def test_none_inputs_are_safe(self):
        self.assertEqual(md.merge_last_good(None, None), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
