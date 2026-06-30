"""
General royalty metal-RE-RATE in central_fair_value (holdco_nav.py), with the verify-before-wire gate.

A royalty book carried at acquisition COST understates as the metal re-rates ("book understates a
royalty"). This pins the cockpit-wide fix and its trust gate:

  * DETECTOR (always on, no rating change): every royalty-mode fair value returns
    cost_basis_anchor=True and, until re-rated, rerate_candidate=True — so the under-mark is visible
    for EVERY royalty name. holdco/PG mode is NOT a cost anchor.
  * CORRECTION (flag-gated, fail-safe): a SOURCED rerated_book_value lifts the anchor only when the
    royalty_rerate flag is on — only ever UP (never crush below cost), capped at MED confidence.
  * VERIFY-BEFORE-WIRE: an agent-sourced re-rate may NOT move the rating until an INDEPENDENT verifier
    has cleared it (rerated_verified). Unverified ⇒ held back (rerate_pending_verification), cost book
    stands. Default is unverified — a sourced value is inert until checked. The feed reads a CONFIRMED
    verdict off the research_cache `verified` block.

Pure stdlib; no engine/network.
"""
import unittest

import holdco_nav as hn
import holdco_nav_feed as hnf


def _groy(**over):
    a = dict(mode="royalty", price=2.76, shares=230.8e6, total_equity=722e6, goodwill=0.0)
    a.update(over)
    return a


ON = {"royalty_rerate": {"enabled": True}}
OFF = {"royalty_rerate": {"enabled": False}}


class _FakeCache:
    """Mimics ResearchCache.get(ticker, field) over a plain nested dict."""
    def __init__(self, d):
        self._d = d
    def get(self, ticker, field):
        return self._d.get(ticker, {}).get(field)


class DetectorTests(unittest.TestCase):
    def test_every_royalty_is_flagged_cost_basis_and_rerate_candidate(self):
        r = hn.central_fair_value(**_groy())
        self.assertTrue(r["cost_basis_anchor"])
        self.assertTrue(r["rerate_candidate"])
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
        for r in (hn.central_fair_value(mode="royalty", price=1.0, shares=None),
                  hn.central_fair_value(mode="bogus")):
            for k in ("cost_basis_anchor", "rerate_applied", "rerate_candidate",
                      "rerate_pending_verification"):
                self.assertIn(k, r)


class CorrectionGateTests(unittest.TestCase):
    def test_flag_off_keeps_cost_book_even_with_a_verified_rerate(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True, config=OFF)
        self.assertFalse(r["rerate_applied"])
        self.assertFalse(r["rerate_pending_verification"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_flag_on_and_verified_lifts_the_anchor(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True, config=ON)
        self.assertTrue(r["rerate_applied"])
        self.assertFalse(r["rerate_candidate"])
        self.assertFalse(r["rerate_pending_verification"])
        self.assertEqual(r["basis"], "royalty_book_rerated_to_metal")
        self.assertAlmostEqual(r["fair_value_ps"], 4.333, places=2)        # 1.0e9 / 230.8e6
        self.assertAlmostEqual(r["components"]["rerate_uplift_pct"], 38.5, places=0)
        self.assertTrue(r["wire"])

    def test_rerate_never_crushes_below_cost(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=500e6, rerated_verified=True, config=ON)
        self.assertFalse(r["rerate_applied"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)

    def test_rerate_confidence_is_capped_at_med(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_confidence="high",
                                  rerated_verified=True, config=ON)
        self.assertEqual(r["confidence"], "med")
        r_low = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_confidence="low",
                                      rerated_verified=True, config=ON)
        self.assertEqual(r_low["confidence"], "low")

    def test_default_config_absence_is_off(self):
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True)
        self.assertFalse(r["rerate_applied"])
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)


class VerifyBeforeWireTests(unittest.TestCase):
    def test_unverified_rerate_is_held_back_not_applied(self):
        # flag ON, value above cost, but NOT verified ⇒ held back; the rating stays on cost book
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=False, config=ON)
        self.assertFalse(r["rerate_applied"])
        self.assertTrue(r["rerate_pending_verification"])
        self.assertTrue(r["rerate_candidate"])
        self.assertEqual(r["basis"], "tangible_book_ex_goodwill")
        self.assertAlmostEqual(r["fair_value_ps"], 3.128, places=2)        # NOT 4.33 — unverified can't move it

    def test_unverified_is_the_safe_default(self):
        # rerated_verified defaults False ⇒ a sourced value is inert until an independent pass clears it
        r = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, config=ON)
        self.assertFalse(r["rerate_applied"])
        self.assertTrue(r["rerate_pending_verification"])

    def test_verification_flips_it_on(self):
        held = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=False, config=ON)
        live = hn.central_fair_value(**_groy(), rerated_book_value=1.0e9, rerated_verified=True, config=ON)
        self.assertAlmostEqual(held["fair_value_ps"], 3.128, places=2)
        self.assertAlmostEqual(live["fair_value_ps"], 4.333, places=2)


class FeedVerificationTests(unittest.TestCase):
    """The feed maps the research_cache `verified` block to the rerated_verified flag the gate reads."""
    def _raw(self, verified):
        entry = {"value": 1.0e9, "confidence": "med"}
        if verified is not None:
            entry["verified"] = verified
        cache = _FakeCache({"GROY": {
            "total_equity": {"value": 722e6, "confidence": "high"},
            "shares_out": {"value": 230.8e6},
            "royalty_book_rerated_value": entry,
        }})
        return hnf.fair_value_inputs_from_cache(cache, "GROY")

    def test_absent_verified_is_false(self):
        self.assertFalse(self._raw(None)["rerated_verified"])

    def test_confirmed_verdict_is_verified(self):
        self.assertTrue(self._raw({"verdict": "confirmed", "by": "verifier"})["rerated_verified"])

    def test_rejected_verdict_is_not_verified(self):
        self.assertFalse(self._raw({"verdict": "rejected"})["rerated_verified"])

    def test_bool_true_is_verified(self):
        self.assertTrue(self._raw(True)["rerated_verified"])

    def test_value_and_confidence_flow_through(self):
        raw = self._raw({"verdict": "confirmed"})
        self.assertEqual(raw["rerated_book_value"], 1.0e9)
        self.assertEqual(raw["rerated_confidence"], "med")


if __name__ == "__main__":
    unittest.main()
