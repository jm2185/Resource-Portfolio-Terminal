"""The discovery bench — depth-tiered classification of the funnel (rated ◇EVAL → graduated →
monitored → parked), dedup across tiers, and the honest floor readout."""
import unittest

import bench


def _basket(tk, **kw):
    b = {"ticker": tk, "eval_only": True, "floor": 1.97, "rating": 7.4}
    b.update(kw)
    return b


def _cand(tk, **kw):
    c = {"ticker": tk, "source": "scout"}
    c.update(kw)
    return c


class BenchTierTests(unittest.TestCase):
    def test_rated_takes_only_eval_only_baskets(self):
        baskets = [_basket("OGN.V"), {"ticker": "AGA.V", "eval_only": False}]  # AGA is HELD, not bench
        tiers = bench.bench_tiers(baskets, [])
        self.assertEqual([t["key"] for t in tiers], ["rated"])
        self.assertEqual([i["ticker"] for i in tiers[0]["items"]], ["OGN.V"])

    def test_tiers_are_ordered_and_empties_omitted(self):
        tiers = bench.bench_tiers([_basket("OGN.V")], [_cand("DML.TO")])
        self.assertEqual([t["key"] for t in tiers], ["rated", "monitored"])   # graduated/parked omitted
        self.assertEqual(tiers[0]["glyph"], "◇")
        self.assertEqual(tiers[1]["glyph"], "·")

    def test_name_counts_once_at_its_furthest_stage(self):
        # OGN is both rated and (stale) on the monitored list → it belongs to RATED only
        tiers = bench.bench_tiers([_basket("OGN.V")], [_cand("OGN.V"), _cand("DML.TO")])
        rated = next(t for t in tiers if t["key"] == "rated")["items"]
        monitored = next(t for t in tiers if t["key"] == "monitored")["items"]
        self.assertEqual([i["ticker"] for i in rated], ["OGN.V"])
        self.assertEqual([i["ticker"] for i in monitored], ["DML.TO"])

    def test_graduated_and_parked_tiers(self):
        tiers = bench.bench_tiers([], [_cand("M.V")], graduated=[_cand("G.V")], parked=[_cand("P.V")])
        self.assertEqual([t["key"] for t in tiers], ["graduated", "monitored", "parked"])

    def test_counts_summary(self):
        tiers = bench.bench_tiers([_basket("OGN.V")], [_cand("A.V"), _cand("B.V")])
        c = bench.bench_counts(tiers)
        self.assertEqual(c["per_tier"], {"rated": 1, "monitored": 2})
        self.assertEqual(c["total"], 3)

    def test_empty_is_empty(self):
        self.assertEqual(bench.bench_tiers([], []), [])
        self.assertEqual(bench.bench_counts([]), {"per_tier": {}, "total": 0})


class FloorDisplayTests(unittest.TestCase):
    def test_real_floor_shows_the_number(self):
        self.assertEqual(bench.floor_display(_basket("OGN.V", floor=1.97)), "1.97")

    def test_degraded_floor_reads_pending(self):
        self.assertEqual(bench.floor_display(_basket("X.V", floor=0.50, floor_degraded=True)), "pending")

    def test_missing_floor_reads_pending(self):
        self.assertEqual(bench.floor_display(_basket("X.V", floor=None)), "pending")
        self.assertEqual(bench.floor_display({}), "pending")


if __name__ == "__main__":
    unittest.main()
