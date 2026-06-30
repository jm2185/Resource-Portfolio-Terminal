"""
General royalty metal-RE-RATE in central_fair_value (holdco_nav.py).

A royalty book carried at acquisition COST understates as the metal re-rates ("book understates a
royalty"). This pins the cockpit-wide fix:

  * DETECTOR (always on, no rating change): every royalty-mode fair value returns
    cost_basis_anchor=True and, until re-rated, rerate_candidate=True — so the under-mark is visible
    for EVERY royalty name, not just the one someone noticed. holdco/PG mode is NOT a cost anchor.
  * CORRECTION (flag-gated, fail-safe): a SOURCED rerated_book_value lifts the anchor only when the
    royalty_rerate flag is on — only ever UP (never crush below cost), capped at MED confidence,
    rerate_applied=True. Flag off or no sourced value ⇒ cost book stands unchanged.

Pure stdlib; no engine/network.
"""
import unittest

import holdco_nav as hn


def _groy(**over):
    a = dict(mode="royalty", price=2.76, shares=230.8e6, total_equity=722e6, goodwill=0.0)
    a.update(over)
    return a


ON = {"royalty_rerate": {"enabled": True}}
OFF = {"royalty_rerate": {"enabled": False}}


class DetectorTests(unittest.TestCase):
    def test_every_royalty_is_flagged_cost_basis_and_rerate_candidate(self):
        r = hn.central_fair_value(**_groy())
        self.assertTrue(r["cost_basis_anchor"])
        self.assertTrue(r["rerate_candidate"])      # carried at cost, not re-rated → visible to the desk
        self.assertFalse(r["rerate_applied"])
        self.assertEqual(r["basis"], "tangible_book_ex_goodwill")
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_holdco_mode_is_not_a_cost_basis_anchor(self):
        h = hn.central_fair_value(mode="holdco", price=1.97, shares=57e6, hard_floor_ps=0.658,
                                  risked_pipeline_value=100e6, peer_portfolio_value=30e6)
        self.assertFalse(h["cost_basis_anchor"])
        self.assertFalse(h["rerate_candidate"])
        self.assertFalse(h["rerate_applied"])

    def test_flags_present_on_every_return(self):
        for r in (hn.central_fair_value(mode="royalty", price=1.0, shares=None),   # missing-input path
                  hn.central_fair_value(mode="bogus")):                            # unknown mode
            for k in ("cost_basis_anchor", "rerate_applied", "rerate_candidate"):
                self.assertIn(k, r)


class CorrectionGateTests(unittest.TestCase):
    def test_flag_off_keeps_cost_book_even_with_a_sourced_rerate(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, config=OFF)
        self.assertFalse(r["rerate_applied"])
        self.assertTrue(r["rerate_candidate"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_flag_on_with_sourced_rerate_lifts_the_anchor(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, config=ON)
        self.assertTrue(r["rerate_applied"])
        self.assertFalse(r["rerate_candidate"])
        self.assertEqual(r["basis"], "royalty_book_rerated_to_metal")
        self.assertAlmostEqual(r["fair_value_ps"], 4.333, places=2)        # 1.0e9 / 230.8e6
        self.assertAlmostEqual(r["components"]["rerate_uplift_pct"], 38.5, places=0)
        self.assertTrue(r["wire"])                                          # above price ⇒ wires

    def test_rerate_never_crushes_below_cost(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=500e6, config=ON)   # below the 722M cost
        self.assertFalse(r["rerate_applied"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_rerate_confidence_is_capped_at_med(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_confidence="high", config=ON)
        self.assertEqual(r["confidence"], "med")        # a metal mark is never an audited (HIGH) book
        r_low = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_confidence="low", config=ON)
        self.assertEqual(r_low["confidence"], "low")    # an explicit LOW is honoured

    def test_default_config_absence_is_off(self):
        # no config at all ⇒ feature off (no silent activation, no config edit required)
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9)
        self.assertFalse(r["rerate_applied"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)


if __name__ == "__main__":
    unittest.main()
