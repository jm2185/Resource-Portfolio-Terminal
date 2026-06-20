"""Tests for oil_supply_monitor (action-plan P2.4) — objective proxies, NO intent score."""
import unittest

import oil_supply_monitor as om


class ProxyTests(unittest.TestCase):
    def test_price_break(self):
        self.assertTrue(om.assess(wti=88.0)["proxies"]["price_break"]["active"])
        self.assertFalse(om.assess(wti=72.0)["proxies"]["price_break"]["active"])
        self.assertTrue(om.assess(brent=95.0)["proxies"]["price_break"]["active"])

    def test_ovx_spike(self):
        self.assertTrue(om.assess(ovx=55.0)["proxies"]["ovx_spike"]["active"])
        self.assertFalse(om.assess(ovx=30.0)["proxies"]["ovx_spike"]["active"])

    def test_backwardation(self):
        back = om.assess(front=84.0, deferred=82.0)["proxies"]["backwardation"]
        contango = om.assess(front=80.0, deferred=82.0)["proxies"]["backwardation"]
        self.assertTrue(back["active"])
        self.assertEqual(back["spread"], 2.0)
        self.assertFalse(contango["active"])


class ElevationTests(unittest.TestCase):
    def test_all_three_fire_together_arms_watch(self):
        r = om.assess(wti=90.0, ovx=55.0, front=85.0, deferred=83.0)
        self.assertTrue(r["elevated"])
        self.assertTrue(r["armed_energy_royalty_watch"])
        self.assertTrue(any(f["id"] == "oil_supply_risk" for f in r["flags"]))

    def test_one_proxy_alone_does_not_arm(self):
        # a price break with calm vol and contango must NOT arm the watch.
        r = om.assess(wti=90.0, ovx=25.0, front=80.0, deferred=83.0)
        self.assertFalse(r["elevated"])
        self.assertFalse(r["armed_energy_royalty_watch"])
        self.assertEqual(r["flags"], [])

    def test_requires_core_physical_tells(self):
        # OVX spike alone (no price/term data) is not enough — the physical tells must be present.
        self.assertFalse(om.assess(ovx=60.0)["elevated"])

    def test_glut_stays_dormant(self):
        r = om.assess(wti=68.0, ovx=22.0, front=66.0, deferred=69.0)
        self.assertFalse(r["elevated"])
        self.assertFalse(r["armed_energy_royalty_watch"])

    def test_ovx_absent_allows_price_plus_backwardation(self):
        # when OVX isn't available, the two physical tells firing together still arms the watch.
        r = om.assess(wti=90.0, front=85.0, deferred=83.0)
        self.assertTrue(r["elevated"])


class HeadlineContextTests(unittest.TestCase):
    def test_headline_is_context_only_never_scored(self):
        # headlines present but proxies dormant -> NOT elevated (headline never moves the flag).
        r = om.assess(wti=68.0, front=66.0, deferred=69.0,
                      headlines=["Hormuz tanker seized amid Iran tensions"])
        self.assertTrue(r["headline_context"]["present"])
        self.assertIn("hormuz", r["headline_context"]["keywords"])
        self.assertFalse(r["headline_context"]["scored"])
        self.assertFalse(r["elevated"])                  # context did NOT arm anything

    def test_no_intent_score_anywhere(self):
        r = om.assess(wti=90.0, ovx=55.0, front=85.0, deferred=83.0,
                      headlines=["Israel weighing response"])
        blob = str(r).lower()
        self.assertNotIn("intent", r["proxies"])         # no intent proxy
        self.assertIn("no component scores political intent", r["anti_pattern_note"])

    def test_empty_headlines_graceful(self):
        r = om.assess(wti=90.0)
        self.assertFalse(r["headline_context"]["present"])


class StructureTests(unittest.TestCase):
    def test_glossary(self):
        r = om.assess(wti=80.0)
        for k in ("oil_supply_monitor", "oil_price_break", "ovx_spike", "oil_backwardation", "oil_headline"):
            self.assertIn(k, r["glossary"], k)
            self.assertTrue(r["glossary"][k])

    def test_empty_is_graceful(self):
        r = om.assess()
        self.assertFalse(r["elevated"])
        self.assertIsNone(r["proxies"]["price_break"]["active"])

    def test_tooltip_unknown_key_empty(self):
        self.assertEqual(om.oil_tooltip("nope"), "")


if __name__ == "__main__":
    unittest.main()
