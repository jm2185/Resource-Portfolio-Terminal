"""merger_arb — the fixed-ratio deal on the spear becomes engine facts (2026-09-02, TF2 #1)."""
import unittest

import merger_arb as ma

TERMS = {"acquirer": "BNKR.TO", "ratio": 0.1724, "announced": "2026-08-21",
         "undisturbed_close": 0.67, "vote_by": "2026-11-15", "source": "newsfilecorp 310697"}


class MathTests(unittest.TestCase):
    def test_announcement_arithmetic_reproduces_the_pr(self):
        # 0.1724 × BNKR 5.38 = C$0.9275 ≈ the PR's C$0.93; vs the undisturbed 0.67 = +38.4% ≈ "38%"
        implied = ma.implied_consideration(0.1724, 5.38)
        self.assertAlmostEqual(implied, 0.9275, places=4)
        self.assertAlmostEqual(ma.premium_pct(implied, 0.67), 38.43, places=1)

    def test_spread_and_zero_premium_line(self):
        # 08-24 tape: BNKR 4.76 / AGA 0.76 → implied 0.8206, spread 7.97% (the desk's ~7-8% band)
        implied = ma.implied_consideration(0.1724, 4.76)
        self.assertAlmostEqual(implied, 0.8206, places=4)
        self.assertAlmostEqual(ma.spread_pct(0.76, implied), 7.97, places=2)
        # the zero-premium line: 0.67 / 0.1724 = C$3.886 — the desk's "BNKR C$3.91" (rounded 0.674)
        self.assertAlmostEqual(ma.zero_premium_acquirer_px(0.674, 0.1724), 3.9095, places=3)

    def test_bad_inputs_are_none_not_zero(self):
        self.assertIsNone(ma.implied_consideration(None, 5.0))
        self.assertIsNone(ma.implied_consideration(0.1724, 0))
        self.assertIsNone(ma.spread_pct(None, 0.8))
        self.assertIsNone(ma.premium_pct(0.8, None))


class ReadTests(unittest.TestCase):
    def _cfg(self):
        return {"portfolio_metadata": {"_comment": "x", "AGA.V": {"merger_terms": dict(TERMS)},
                                       "GROY": {"type": "royalty"}}}

    def test_targets_and_acquirer_list_are_config_driven(self):
        self.assertEqual(list(ma.targets(self._cfg())), ["AGA.V"])
        self.assertEqual(ma.acquirer_tickers(self._cfg()), ["BNKR.TO"])
        self.assertEqual(ma.acquirer_tickers({"portfolio_metadata": {}}), [])

    def test_live_read(self):
        out = ma.read(self._cfg(), {"BNKR.TO": 4.88, "AGA.V": 0.79}, {"BNKR.TO": False, "AGA.V": False})
        r = out["AGA.V"]
        self.assertAlmostEqual(r["implied"], 0.8413, places=4)
        self.assertAlmostEqual(r["spread_pct"], 6.49, places=2)
        self.assertFalse(r["stale"]); self.assertEqual(r["vote_by"], "2026-11-15")

    def test_missing_or_stale_acquirer_is_flagged_never_filled(self):
        out = ma.read(self._cfg(), {"AGA.V": 0.79}, {"AGA.V": False})
        r = out["AGA.V"]
        self.assertIsNone(r["implied"]); self.assertIsNone(r["spread_pct"])
        self.assertTrue(r["stale"]); self.assertEqual(r["stale_reason"], "no acquirer price")
        out = ma.read(self._cfg(), {"BNKR.TO": 4.88, "AGA.V": 0.79}, {"BNKR.TO": True, "AGA.V": False})
        self.assertTrue(out["AGA.V"]["stale"]); self.assertEqual(out["AGA.V"]["stale_reason"], "stale mark")


if __name__ == "__main__":
    unittest.main()
