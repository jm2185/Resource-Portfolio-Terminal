"""Tests for upside_framework (action-plan P5.2) — GROY & GMX ballast upside frameworks."""
import unittest

import upside_framework as uf


class GroyTests(unittest.TestCase):
    def test_legs_and_base_vs_bull(self):
        r = uf.groy_upside(geo_growth_pct=12.0, gold_upside_pct=15.0, current_pnav=0.8, target_pnav=1.0)
        names = {l["name"] for l in r["legs"]}
        self.assertIn("royalty cash-flow / GEO growth", names)
        self.assertIn("gold price leverage", names)
        self.assertIn("P/NAV re-rate", names)
        # base excludes the re-rate; bull includes it -> bull > base
        self.assertAlmostEqual(r["base_upside_pct"], 12.0 + 15.0, places=1)
        self.assertGreater(r["bull_upside_pct"], r["base_upside_pct"])

    def test_gold_beta_scales_leverage(self):
        hi = uf.groy_upside(gold_upside_pct=10.0, config={"upside_framework": {"groy": {"gold_beta": 1.5}}})
        lev = next(l for l in hi["legs"] if l["name"] == "gold price leverage")
        self.assertAlmostEqual(lev["pct"], 15.0, places=1)

    def test_partial_inputs_omit_legs(self):
        r = uf.groy_upside(geo_growth_pct=8.0)
        self.assertEqual(len(r["legs"]), 1)
        self.assertEqual(r["key_driver"], "royalty cash-flow / GEO growth")


class GmxTests(unittest.TestCase):
    def test_discount_close_leg_math(self):
        # discount 0.40 -> 0.20: price lifts by (0.80/0.60 - 1) = 33.3%
        r = uf.gmx_upside(current_discount=0.40, target_discount=0.20)
        leg = next(l for l in r["legs"] if l["name"] == "holdco discount close")
        self.assertAlmostEqual(leg["pct"], 33.33, places=1)

    def test_base_excludes_discovery_bull_includes(self):
        r = uf.gmx_upside(nav_growth_pct=10.0, current_discount=0.40, target_discount=0.20,
                          discovery_option_pct=25.0)
        self.assertAlmostEqual(r["base_upside_pct"], 10.0 + 33.33, places=1)
        self.assertAlmostEqual(r["bull_upside_pct"], 10.0 + 33.33 + 25.0, places=1)

    def test_default_target_discount_used(self):
        r = uf.gmx_upside(current_discount=0.40)   # default target 0.20
        self.assertTrue(any(l["name"] == "holdco discount close" for l in r["legs"]))


class DispatchTests(unittest.TestCase):
    def test_dispatch_by_ticker(self):
        self.assertEqual(uf.assess("GROY", {"geo_growth_pct": 10})["framework"], "GROY")
        self.assertEqual(uf.assess("GMX.TO", {"nav_growth_pct": 10})["framework"], "GMX")

    def test_dispatch_by_slot(self):
        self.assertEqual(uf.assess("gold-royalty-ballast", {"geo_growth_pct": 10})["framework"], "GROY")

    def test_spear_has_no_ballast_framework(self):
        r = uf.assess("AGA.V")
        self.assertIsNone(r["framework"])
        self.assertIn("asymmetry", r["note"])

    def test_glossary_present(self):
        self.assertIn("upside_framework", uf.groy_upside(geo_growth_pct=5)["glossary"])
        self.assertIn("gmx_upside", uf.gmx_upside(nav_growth_pct=5)["glossary"])

    def test_empty_graceful(self):
        r = uf.groy_upside()
        self.assertEqual(r["legs"], [])
        self.assertEqual(r["base_upside_pct"], 0)


if __name__ == "__main__":
    unittest.main()
