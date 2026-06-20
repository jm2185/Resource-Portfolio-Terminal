"""Tests for rates_monitor (action-plan P2.1) — the bear-steepener / fiscal-dominance upstream tell.
Pure-Python, no numpy/pandas, mirroring the dependency-free design."""
import unittest

import rates_monitor as rm


# A representative live snapshot (rates in %): a steepish curve, 30Y well above funds.
CUR = {"dgs2": 3.90, "dgs5": 4.10, "dgs10": 4.55, "dgs30": 4.95, "fedfunds": 4.33}


class SpreadsTests(unittest.TestCase):
    def test_curve_spreads(self):
        s = rm.assess(CUR)["spreads"]
        self.assertAlmostEqual(s["2s10s"], 4.55 - 3.90, places=3)
        self.assertAlmostEqual(s["5s30s"], 4.95 - 4.10, places=3)
        self.assertAlmostEqual(s["30y_funds"], 4.95 - 4.33, places=3)

    def test_missing_series_degrades_gracefully(self):
        s = rm.assess({"dgs10": 4.55, "dgs2": 3.90})["spreads"]
        self.assertIsNotNone(s["2s10s"])
        self.assertIsNone(s["5s30s"])                 # no dgs5/dgs30 -> None, never fabricated
        self.assertIsNone(s["30y_funds"])


class BearSteepenerTests(unittest.TestCase):
    """The signature: long end RISING over the window while the front is static/falling."""

    def _prior(self, **delta):
        # prior = current minus the given moves (in pp); default flat
        p = dict(CUR)
        for k, dv in delta.items():
            p[k] = CUR[k] - dv
        return p

    def test_fires_when_long_rises_and_front_static(self):
        prior = self._prior(dgs30=0.30, dgs10=0.25)   # long +30/+25 bps; funds unchanged
        r = rm.assess(CUR, prior=prior)
        bs = r["bear_steepener"]
        self.assertTrue(bs["active"])
        self.assertAlmostEqual(bs["long_rise_bps"], 30.0, places=1)
        self.assertAlmostEqual(bs["front_change_bps"], 0.0, places=1)
        # raises the discrete flag + a timeline event
        self.assertTrue(any(f["id"] == "bear_steepener" and f["active"] for f in r["flags"]))
        self.assertTrue(any(e["type"] == "bear_steepener" for e in r["events"]))

    def test_does_not_fire_on_bull_steepener(self):
        # bull-steepener: the FRONT falls (easing), long roughly anchored -> NOT fiscal-dominance.
        prior = dict(CUR); prior["fedfunds"] = CUR["fedfunds"] + 0.40   # funds were higher -> they FELL 40bps
        prior["dgs30"] = CUR["dgs30"] - 0.02                            # long barely moved
        r = rm.assess(CUR, prior=prior)
        self.assertFalse(r["bear_steepener"]["active"])

    def test_does_not_fire_on_bear_flattener(self):
        # Fed hiking: front rises FASTER than the long -> flattener, not the fiscal-dominance tell.
        prior = self._prior(dgs30=0.20, fedfunds=0.40)   # long +20, front +40
        r = rm.assess(CUR, prior=prior)
        self.assertFalse(r["bear_steepener"]["active"])  # front_change +40 > +5 threshold

    def test_not_assessable_without_prior(self):
        bs = rm.assess(CUR)["bear_steepener"]
        self.assertFalse(bs["active"])
        self.assertFalse(bs["assessable"])
        self.assertIn("prior", bs["note"])

    def test_threshold_is_config_tunable(self):
        prior = self._prior(dgs30=0.12)                  # +12bps, below the default 20bps trigger
        self.assertFalse(rm.assess(CUR, prior=prior)["bear_steepener"]["active"])
        cfg = {"rates_monitor": {"long_rise_bps": 10.0}}
        self.assertTrue(rm.assess(CUR, prior=prior, config=cfg)["bear_steepener"]["active"])


class MoveTests(unittest.TestCase):
    def test_spike_on_level(self):
        r = rm.assess(CUR, move=130.0)
        self.assertTrue(r["move"]["spike"])
        self.assertTrue(any(f["id"] == "move_spike" for f in r["flags"]))
        self.assertTrue(any(e["type"] == "move_spike" for e in r["events"]))

    def test_spike_on_jump(self):
        r = rm.assess(CUR, move=110.0, move_prior=90.0)   # +20 over the window
        self.assertTrue(r["move"]["spike"])

    def test_calm_move_no_spike(self):
        r = rm.assess(CUR, move=85.0, move_prior=84.0)
        self.assertFalse(r["move"]["spike"])
        self.assertFalse(any(f["id"] == "move_spike" for f in r["flags"]))

    def test_missing_move_is_graceful(self):
        r = rm.assess(CUR)
        self.assertIsNone(r["move"]["value"])
        self.assertFalse(r["move"]["spike"])


class AuctionTests(unittest.TestCase):
    def test_tail_flags_weak_auction_event(self):
        r = rm.assess(CUR, auctions=[{"tenor": "30Y", "tail_bps": 2.1, "bid_to_cover": 2.3,
                                      "date": "2026-06-18"}])
        self.assertTrue(r["auctions"][0]["weak"])
        ev = [e for e in r["events"] if e["type"] == "auction_tail"]
        self.assertEqual(len(ev), 1)
        self.assertIn("30Y", ev[0]["text"])

    def test_weak_bid_to_cover_flags(self):
        r = rm.assess(CUR, auctions=[{"tenor": "10Y", "tail_bps": 0.2, "bid_to_cover": 2.1}])
        self.assertTrue(r["auctions"][0]["weak"])        # soft b/c even with a small tail

    def test_strong_auction_no_event(self):
        r = rm.assess(CUR, auctions=[{"tenor": "10Y", "tail_bps": -0.5, "bid_to_cover": 2.6}])
        self.assertFalse(r["auctions"][0]["weak"])
        self.assertEqual([e for e in r["events"] if e["type"] == "auction_tail"], [])


class FiscalDominanceTests(unittest.TestCase):
    def test_composite_present_and_labeled(self):
        f = rm.assess(CUR)["fiscal_dominance"]
        self.assertIsNotNone(f["score"])
        self.assertIn(f["label"], ("DORMANT", "BUILDING", "ELEVATED", "ACUTE"))
        self.assertLessEqual(f["score"], 100.0)
        self.assertGreaterEqual(f["score"], 0.0)

    def test_stress_scores_higher_than_calm(self):
        calm = rm.assess({"dgs2": 4.20, "dgs5": 4.20, "dgs10": 4.20, "dgs30": 4.25, "fedfunds": 4.30},
                         move=80.0)                       # flat curve, long ~ funds, calm vol
        stressed = rm.assess(CUR, prior={**CUR, "dgs30": CUR["dgs30"] - 0.35}, move=140.0,
                             auctions=[{"tenor": "30Y", "tail_bps": 2.5, "bid_to_cover": 2.0}])
        self.assertGreater(stressed["fiscal_dominance"]["score"], calm["fiscal_dominance"]["score"])

    def test_active_steepener_drives_acute_region(self):
        stressed = rm.assess(CUR, prior={**CUR, "dgs30": CUR["dgs30"] - 0.40}, move=150.0,
                             auctions=[{"tenor": "30Y", "tail_bps": 3.0, "bid_to_cover": 1.9}])
        self.assertIn(stressed["fiscal_dominance"]["label"], ("ELEVATED", "ACUTE"))


class StructureTests(unittest.TestCase):
    def test_glossary_and_upstream_framing(self):
        r = rm.assess(CUR)
        for k in ("rates_monitor", "bear_steepener", "twos_tens", "fives_thirties",
                  "thirty_funds", "move", "auction_tail"):
            self.assertIn(k, r["glossary"], k)
            self.assertTrue(r["glossary"][k])
        self.assertIn("upstream", r["upstream_note"].lower())
        self.assertIn("upstream", r["fiscal_dominance"]["note"].lower())

    def test_empty_input_is_graceful(self):
        r = rm.assess(None)
        self.assertIsNone(r["spreads"]["2s10s"])
        self.assertFalse(r["bear_steepener"]["active"])
        self.assertEqual(r["flags"], [])

    def test_tooltip_unknown_key_is_empty(self):
        self.assertEqual(rm.rates_tooltip("does_not_exist"), "")


if __name__ == "__main__":
    unittest.main()
