"""
V1 — Mark-NAV-to-Spot (nav_mark.py): the live NAV recompute that replaces the static
hand-entered nav_adj_per_share, plus the two-tier spot resolve and the staleness contract
the confidence ribbon widens on. Pure stdlib; mirrors the URC.TO 6-K figures.
"""
import os
import tempfile
import time
import unittest

import nav_mark
from asymmetry_rating import _confidence_ribbon


def _urc_inventory(**over):
    """The real URC.TO Jan-2026 6-K structure (equity C$381.0M, 2,329,637 lbs at C$184.9M
    carrying, 146,477,507 shares), spot stamped at US$86.10."""
    inv = {"total_equity_cad": 381_026_000, "phy_units": 2_329_637,
           "carrying_cad": 184_900_000, "shares_out": 146_477_507,
           "commodity": "uranium", "spot_usd": 86.10, "spot_as_of": "2026-06-04"}
    inv.update(over)
    return inv


class SpotResolveTests(unittest.TestCase):
    def test_live_commodity_prefers_live_feed(self):
        s = nav_mark.resolve_spot("gold", live_spots={"gold": 4540.0}, stamped_usd=4000.0)
        self.assertEqual(s["tier"], "live")
        self.assertEqual(s["spot_usd"], 4540.0)
        self.assertFalse(s["stale"])

    def test_uranium_uses_the_stamp_with_age(self):
        now = time.mktime((2026, 6, 9, 12, 0, 0, 0, 0, -1))
        s = nav_mark.resolve_spot("uranium", live_spots={"gold": 4540.0},
                                  stamped_usd=86.10, stamped_as_of="2026-06-04", now=now)
        self.assertEqual(s["tier"], "stamped")
        self.assertEqual(s["age_days"], 5.0)
        self.assertFalse(s["stale"])

    def test_old_stamp_is_stale_and_undated_stamp_is_stale(self):
        now = time.mktime((2026, 6, 9, 12, 0, 0, 0, 0, -1))
        old = nav_mark.resolve_spot("uranium", stamped_usd=86.10,
                                    stamped_as_of="2026-01-04", now=now)
        self.assertTrue(old["stale"])
        undated = nav_mark.resolve_spot("uranium", stamped_usd=86.10, stamped_as_of=None)
        self.assertTrue(undated["stale"])           # never invented: no date = no freshness claim

    def test_nothing_usable_returns_none(self):
        self.assertIsNone(nav_mark.resolve_spot("uranium", live_spots={"gold": 4540.0}))
        self.assertIsNone(nav_mark.resolve_spot("uranium", stamped_usd=-5))

    def test_live_feed_missing_falls_back_to_stamp(self):
        s = nav_mark.resolve_spot("gold", live_spots={"gold": None}, stamped_usd=4000.0,
                                  stamped_as_of="2026-06-01")
        self.assertEqual(s["tier"], "stamped")


class NavFromInventoryTests(unittest.TestCase):
    def test_reproduces_the_hand_derived_urc_mark(self):
        # the static 3.26 was derived at US$86.10 × 1.40 USDCAD — the live compute must agree
        m = nav_mark.nav_from_inventory(_urc_inventory(), usd_to_cad=1.40)
        self.assertAlmostEqual(m["nav_per_share"], 3.26, places=2)
        self.assertEqual(m["spot"]["tier"], "stamped")
        # uplift = 2,329,637 × 86.10 × 1.40 − 184,900,000
        self.assertAlmostEqual(m["uplift_cad"], 2_329_637 * 86.10 * 1.40 - 184_900_000, delta=1.0)

    def test_breathes_with_spot(self):
        lo = nav_mark.nav_from_inventory(_urc_inventory(spot_usd=70.0), usd_to_cad=1.40)
        hi = nav_mark.nav_from_inventory(_urc_inventory(spot_usd=100.0), usd_to_cad=1.40)
        self.assertLess(lo["nav_per_share"], hi["nav_per_share"])

    def test_carrying_is_an_nrv_floor_never_a_negative_uplift(self):
        # spot collapsed below carrying → IFRS already reflects it → uplift 0, NAV = equity/shares
        m = nav_mark.nav_from_inventory(_urc_inventory(spot_usd=20.0), usd_to_cad=1.40)
        self.assertEqual(m["uplift_cad"], 0.0)
        self.assertAlmostEqual(m["nav_per_share"], 381_026_000 / 146_477_507, places=4)

    def test_missing_inputs_yield_none_not_a_fake(self):
        self.assertIsNone(nav_mark.nav_from_inventory(_urc_inventory(shares_out=None),
                                                      usd_to_cad=1.40))
        self.assertIsNone(nav_mark.nav_from_inventory(_urc_inventory(), usd_to_cad=None))
        self.assertIsNone(nav_mark.nav_from_inventory(_urc_inventory(spot_usd=None),
                                                      usd_to_cad=1.40))   # no stamp, no live feed
        self.assertIsNone(nav_mark.nav_from_inventory("not a dict", usd_to_cad=1.40))

    def test_live_commodity_marks_to_live(self):
        inv = _urc_inventory(commodity="gold", spot_usd=4000.0)   # stale-ish stamp present
        m = nav_mark.nav_from_inventory(inv, live_spots={"gold": 4540.0}, usd_to_cad=1.40)
        self.assertEqual(m["spot"]["tier"], "live")
        self.assertEqual(m["spot"]["spot_usd"], 4540.0)

    def test_quality_note_names_tier_and_staleness(self):
        now = time.mktime((2026, 6, 9, 12, 0, 0, 0, 0, -1))
        fresh = nav_mark.nav_from_inventory(_urc_inventory(), usd_to_cad=1.40, now=now)
        self.assertIn("STAMPED", nav_mark.quality_note(fresh))
        self.assertNotIn("STALE", nav_mark.quality_note(fresh))
        old = nav_mark.nav_from_inventory(_urc_inventory(spot_as_of="2026-01-04"),
                                          usd_to_cad=1.40, now=now)
        self.assertIn("STALE", nav_mark.quality_note(old))
        self.assertIsNone(nav_mark.quality_note(None))


class RibbonStalenessTests(unittest.TestCase):
    """The ribbon is where the staleness SURFACES: a stale stamped mark widens the band."""

    def _asset(self, nav_quality=None):
        return {"price": 4.81, "data_quality": "full", "bull": 6.0, "bear": 3.0,
                "nav_quality": nav_quality}

    def test_stale_nav_mark_widens_the_band_and_says_why(self):
        fresh = _confidence_ribbon(self._asset(
            {"commodity": "uranium", "spot": {"tier": "stamped", "stale": False,
                                              "age_days": 5.0}}), {})
        stale = _confidence_ribbon(self._asset(
            {"commodity": "uranium", "spot": {"tier": "stamped", "stale": True,
                                              "age_days": 150.0}}), {})
        self.assertGreater(stale["plus_minus"], fresh["plus_minus"])
        self.assertIn("STALE", stale["nav_mark"])
        self.assertIn("150d", stale["nav_mark"])

    def test_no_nav_quality_is_byte_compatible(self):
        r = _confidence_ribbon(self._asset(None), {})
        self.assertNotIn("nav_mark", r)
        self.assertIn("plus_minus", r)


class RecordMarkTests(unittest.TestCase):
    """Pre-flight hardening P2 — the engine's intraday mark converges to the close; history
    stays immutable."""

    def setUp(self):
        import price_history as ph
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_day_mark_updates(self):
        a = self.h.record_mark("AGA.V", "2026-06-10", 0.61, today="2026-06-10")
        self.assertTrue(a["ok"] and not a.get("updated"))
        b = self.h.record_mark("AGA.V", "2026-06-10", 0.63, today="2026-06-10")
        self.assertTrue(b["ok"] and b["updated"])               # converges to the close
        self.assertEqual(self.h.close_on("AGA.V", "2026-06-10")["close"], 0.63)

    def test_past_immutable_future_refused(self):
        self.h.record("AGA.V", "2026-06-09", 0.58)
        past = self.h.record_mark("AGA.V", "2026-06-09", 0.99, today="2026-06-10")
        self.assertTrue(past.get("conflict"))                   # yesterday can't be rewritten
        self.assertEqual(self.h.close_on("AGA.V", "2026-06-09")["close"], 0.58)
        fut = self.h.record_mark("AGA.V", "2026-06-11", 0.70, today="2026-06-10")
        self.assertFalse(fut["ok"])

    def test_duplicate_mark_no_dirty_write(self):
        self.h.record_mark("AGA.V", "2026-06-10", 0.61, today="2026-06-10")
        r = self.h.record_mark("AGA.V", "2026-06-10", 0.61, today="2026-06-10")
        self.assertTrue(r.get("duplicate"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
