"""Tests for conditionals (action-plan P4) — AGA add gate, invalidation lines, dry-powder."""
import unittest

import conditionals as cx


BOOK = [
    {"ticker": "AGA.V",  "slot": "silver-spear",             "weight": 0.55},
    {"ticker": "GROY",   "slot": "gold-royalty-ballast",     "weight": 0.20},
    {"ticker": "GMX.TO", "slot": "project-generator-holdco", "weight": 0.10},
    {"ticker": "URC.TO", "slot": "electrification-royalty",  "weight": 0.15},
]
GOOD_WEIGHTS = {"A": 0.36, "B": 0.27, "C": 0.15, "D": 0.22}   # A+B = 0.63, spear-favorable
BAL = {"label": "BALANCED", "cap": 1.0}


class AgaAddGateTests(unittest.TestCase):
    def test_all_conditions_met_proposes_proportional_add(self):
        g = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS, posture=BAL,
                            entry="LOAD", aga_status="INTACT")
        self.assertEqual(g["decision"], "ADD")
        self.assertTrue(g["all_conditions_met"])
        self.assertGreater(g["proposed_add"], 0)
        self.assertLessEqual(g["target_weight"], cx.SPEAR_CEILING + 1e-9)   # never past the ceiling

    def test_at_ceiling_is_blocked(self):
        g = cx.aga_add_gate(spear_weight=0.60, weights=GOOD_WEIGHTS, posture=BAL, entry="LOAD")
        self.assertEqual(g["decision"], "BLOCKED")
        self.assertIn("ceiling", g["reason"])
        self.assertEqual(g["proposed_add"], 0.0)

    def test_extended_entry_holds(self):
        g = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS, posture=BAL,
                            entry="AVOID-EXTENDED", aga_status="INTACT")
        self.assertEqual(g["decision"], "HOLD")
        self.assertFalse(next(c["pass"] for c in g["conditions"] if c["name"] == "entry_not_extended"))

    def test_unverified_entry_fails_closed(self):
        # no entry read must NOT green-light an add (silence fails closed).
        g = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS, posture=BAL, aga_status="INTACT")
        self.assertEqual(g["decision"], "HOLD")

    def test_defensive_posture_blocks_regime_condition(self):
        g = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS,
                            posture={"label": "DEFENSIVE", "cap": 0.5}, entry="LOAD")
        self.assertEqual(g["decision"], "HOLD")
        self.assertFalse(next(c["pass"] for c in g["conditions"] if c["name"] == "regime_supportive"))

    def test_weak_spear_favorable_weight_fails_regime(self):
        weak = {"A": 0.20, "B": 0.15, "C": 0.35, "D": 0.30}   # A+B = 0.35 < 0.45
        g = cx.aga_add_gate(spear_weight=0.50, weights=weak, posture=BAL, entry="LOAD")
        self.assertFalse(next(c["pass"] for c in g["conditions"] if c["name"] == "regime_supportive"))

    def test_invalidated_thesis_blocks(self):
        g = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS, posture=BAL,
                            entry="LOAD", aga_status="INVALIDATED")
        self.assertEqual(g["decision"], "BLOCKED")

    def test_jsf_severe_blocks(self):
        g = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS, posture=BAL,
                            entry="LOAD", jsf_severe=True)
        self.assertEqual(g["decision"], "BLOCKED")

    def test_posture_cap_scales_the_add(self):
        small = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS,
                                posture={"label": "BALANCED", "cap": 0.5}, entry="LOAD", aga_status="INTACT")
        big = cx.aga_add_gate(spear_weight=0.50, weights=GOOD_WEIGHTS,
                              posture={"label": "SPEAR EXPLOIT", "cap": 1.25}, entry="LOAD", aga_status="INTACT")
        self.assertLess(small["proposed_add"], big["proposed_add"])


class InvalidationTests(unittest.TestCase):
    def test_uranium_term_flag_invalidates_urc(self):
        flags = [{"id": "uranium_term_invalidation", "active": True, "level": "risk"}]
        r = cx.invalidation_status(BOOK, flags=flags)
        urc = next(n for n in r["names"] if n["ticker"] == "URC.TO")
        self.assertEqual(urc["status"], "INVALIDATED")
        self.assertIn("URC.TO", r["invalidated"])

    def test_scenario_c_hole_is_a_watch_on_urc(self):
        flags = [{"id": "scenario_c_hole", "active": True, "level": "warn"}]
        r = cx.invalidation_status(BOOK, flags=flags)
        urc = next(n for n in r["names"] if n["ticker"] == "URC.TO")
        self.assertEqual(urc["status"], "WATCH")

    def test_debasement_at_risk_watches_the_core(self):
        flags = [{"id": "debasement_at_risk", "active": True, "level": "risk"}]
        r = cx.invalidation_status(BOOK, flags=flags)
        statuses = {n["ticker"]: n["status"] for n in r["names"]}
        self.assertEqual(statuses["AGA.V"], "WATCH")
        self.assertEqual(statuses["GROY"], "WATCH")

    def test_jsf_severe_name_signal_invalidates(self):
        r = cx.invalidation_status(BOOK, name_signals={"AGA.V": {"jsf_severe": True}})
        aga = next(n for n in r["names"] if n["ticker"] == "AGA.V")
        self.assertEqual(aga["status"], "INVALIDATED")

    def test_floor_breach_invalidates_spear(self):
        r = cx.invalidation_status(BOOK, name_signals={"AGA.V": {"floor_breached": True}})
        aga = next(n for n in r["names"] if n["ticker"] == "AGA.V")
        self.assertEqual(aga["status"], "INVALIDATED")
        self.assertTrue(any("REP floor" in t for t in aga["tripped"]))

    def test_bear_steepener_is_context_not_a_stop(self):
        flags = [{"id": "bear_steepener", "active": True, "level": "warn"}]
        r = cx.invalidation_status(BOOK, flags=flags)
        self.assertEqual(r["invalidated"], [])
        self.assertEqual(r["watch"], [])
        self.assertTrue(any(c["flag"] == "bear_steepener" for c in r["context_flags"]))

    def test_clean_book_all_intact(self):
        r = cx.invalidation_status(BOOK)
        self.assertTrue(all(n["status"] == "INTACT" for n in r["names"]))


class DryPowderTests(unittest.TestCase):
    def test_usd_tilt_surfaces(self):
        p = cx.dry_powder(usdcad={"tilt": "USD", "carry_pp": 1.58}, weights=GOOD_WEIGHTS, posture=BAL)
        self.assertEqual(p["currency_tilt"], "USD")
        self.assertIn("USD", p["powder_currency"])

    def test_defensive_holds(self):
        p = cx.dry_powder(posture={"label": "DEFENSIVE"}, entries={"AGA.V": "LOAD"})
        self.assertEqual(p["stance"], "HOLD")

    def test_clean_entry_deploys(self):
        p = cx.dry_powder(posture=BAL, entries={"GROY": "SCALE-IN", "AGA.V": "WAIT"})
        self.assertEqual(p["stance"], "DEPLOY")
        self.assertEqual(p["targets"], ["GROY"])

    def test_no_entry_staggers(self):
        p = cx.dry_powder(posture=BAL, entries={"AGA.V": "WAIT"})
        self.assertEqual(p["stance"], "STAGGER")

    def test_rich_crisis_weight_reserves_convexity(self):
        p = cx.dry_powder(posture=BAL, weights={"A": 0.3, "B": 0.35, "C": 0.15, "D": 0.2})
        self.assertTrue(p["reserve_convexity_tranche"])


class AssessTests(unittest.TestCase):
    def test_consolidates_and_flags_invalidation(self):
        scenario = {"weights": GOOD_WEIGHTS, "flags": [{"id": "scenario_c_hole", "active": True}]}
        sentinel = {"flags": [{"id": "uranium_term_invalidation", "active": True}]}
        r = cx.assess(BOOK, scenario=scenario, sentinel=sentinel, posture=BAL,
                      usdcad={"tilt": "USD", "carry_pp": 1.5},
                      entries={"AGA.V": "LOAD"}, spear_weight=0.50)
        self.assertIn("aga_add", r)
        self.assertIn("URC.TO", r["invalidation"]["invalidated"])
        self.assertTrue(any(f["id"] == "invalidation" and f["ticker"] == "URC.TO" for f in r["flags"]))

    def test_add_flag_emitted_on_add(self):
        r = cx.assess(BOOK, scenario={"weights": GOOD_WEIGHTS}, posture=BAL,
                      entries={"AGA.V": "LOAD"}, spear_weight=0.50)
        self.assertEqual(r["aga_add"]["decision"], "ADD")
        self.assertTrue(any(f["id"] == "aga_add" for f in r["flags"]))

    def test_glossary_present(self):
        r = cx.assess(BOOK, scenario={"weights": GOOD_WEIGHTS})
        for k in ("aga_add_gate", "invalidation_status", "dry_powder"):
            self.assertIn(k, r["glossary"])

    def test_empty_graceful(self):
        r = cx.assess([])
        self.assertEqual(r["invalidation"]["names"], [])
        self.assertIn(r["aga_add"]["decision"], ("HOLD", "BLOCKED"))


if __name__ == "__main__":
    unittest.main()
