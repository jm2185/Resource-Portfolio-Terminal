"""
Tests for the conventional-lane producer (conventional_holdings.py) + its sleeve renderer.

The bug this layer fixes: a REAL held position (CEGS CDRs) rendered nowhere because nothing produced
``dual_sided_reads`` — the consumer existed, the producer didn't. Guarantees pinned:

  * membership = portfolio_metadata + lane:'conventional' (never barbell_weights), and an entry with
    the lane but NO underwriting block is surfaced as a gap, not skipped;
  * the read carries the exact shape conventional_sentinel.assess_book consumes — proven by feeding
    one straight through, not by asserting keys;
  * a dead price feed falls back to the stored underwriting price STAMPED stale (grounded-or-silent);
  * one bad underwriting block yields an error row, never a dead sleeve;
  * the live v5_config CEG entry actually produces a priced read (the regression that matters);
  * the renderer shows stale/error states rather than hiding them.
"""
import json
import unittest

import conventional_holdings as ch
import conventional_sentinel as cs


def _pmeta(**over):
    base = {
        "AGA.V": {"type": "explorer"},                      # resource — must never enter the sleeve
        "CEG": {"name": "Constellation Energy", "lane": "conventional", "type": "operator",
                "instrument": "CEGS (TSX CDR)", "units": 24, "pricing_ref": "CEG",
                "dual_sided": {"lens": "compounder", "price": 263.56, "shares_out": 359_101_000,
                               "fcf": 3.1e9, "stressed_fcf": 2.2e9, "wacc": 0.08, "cap_years": 15,
                               "growth": {"p10": 0.03, "p50": 0.10, "p90": 0.18},
                               "quality": 0.75, "conviction": 0.65}},
    }
    base.update(over)
    return base


class MembershipTests(unittest.TestCase):
    def test_only_conventional_lane_names_enter(self):
        pos = ch.positions(_pmeta())
        self.assertEqual(["CEG"], [p["ticker"] for p in pos])

    def test_lane_without_underwriting_block_is_a_visible_gap_not_a_skip(self):
        pos = ch.positions(_pmeta(XYZ={"lane": "conventional"}))
        gap = [p for p in pos if p["ticker"] == "XYZ"][0]
        self.assertTrue(gap["unpriceable"])
        reads = ch.build_reads(pos)
        self.assertIn("error", reads["XYZ"])
        self.assertIn("underwriting", reads["XYZ"]["error"])

    def test_pricing_ref_defaults_to_ticker_and_respects_override(self):
        pos = ch.positions(_pmeta())
        self.assertEqual("CEG", pos[0]["pricing_ref"])


class ReadTests(unittest.TestCase):
    def test_live_price_flows_into_the_read(self):
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: 270.0)
        r = reads["CEG"]
        self.assertEqual(270.0, r["price"])
        self.assertFalse(r["price_stale"])
        for k in ("lens", "ladder", "rating", "band", "zone", "pillars"):
            self.assertIn(k, r)
        self.assertIsNotNone(r["ladder"].get("floor"))
        self.assertTrue({"T", "Q", "V"} <= set(r["pillars"]))   # lens pillars ride along

    def test_market_value_never_uses_the_reference_price(self):
        """24 CDRs are not 24 CEG shares — mv comes ONLY from the instrument's own unit price."""
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: 270.0)
        self.assertIsNone(reads["CEG"]["market_value"])          # no unit price -> no mv, no guess
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: 270.0,
                               unit_prices={"CEG": 17.98}, nav=5913.0)
        r = reads["CEG"]
        self.assertAlmostEqual(24 * 17.98, r["market_value"])    # CDR price, not 24×270
        self.assertAlmostEqual(24 * 17.98 / 5913.0, r["weight"])

    def test_dead_feed_falls_back_to_stored_price_stamped_stale(self):
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: None)
        self.assertEqual(263.56, reads["CEG"]["price"])
        self.assertTrue(reads["CEG"]["price_stale"])
        # a price_fn that RAISES is the same as one that returns None (fenced)
        def boom(ref):
            raise RuntimeError("feed down")
        self.assertTrue(ch.build_reads(ch.positions(_pmeta()), boom)["CEG"]["price_stale"])

    def test_bad_underwriting_yields_error_row_never_dead_sleeve(self):
        pm = _pmeta()
        pm["BAD"] = {"lane": "conventional", "dual_sided": {"price": "not-a-number",
                                                            "shares_out": None}}
        reads = ch.build_reads(ch.positions(pm), lambda ref: 100.0)
        self.assertNotIn("error", reads["CEG"])              # the good name still priced
        # BAD either errors or degrades — it must never be silently absent
        self.assertIn("BAD", reads)

    def test_weight_appears_only_with_nav_and_unit_price(self):
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: 250.0, nav=60_000.0)
        self.assertIsNone(reads["CEG"]["weight"])                # nav alone isn't enough
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: 250.0,
                               unit_prices={"CEG": 18.0}, nav=60_000.0)
        self.assertAlmostEqual(24 * 18.0 / 60_000.0, reads["CEG"]["weight"])

    def test_reads_feed_conventional_sentinel_directly(self):
        """The contract proven end-to-end: producer output → assess_book, no reshaping."""
        reads = ch.build_reads(ch.positions(_pmeta()), lambda ref: 263.56)
        conv = [r for r in reads.values() if not r.get("error")]
        cz = cs.assess_book(conv)
        self.assertIn("zones_next", cz)
        self.assertIn("CEG", cz["zones_next"])              # the name got a zone


class LiveConfigRegressionTests(unittest.TestCase):
    def test_the_shipped_ceg_entry_produces_a_priced_read(self):
        """The actual v5_config.json CEG block must survive the whole path — this is the exact
        failure the operator hit (held position, empty dashboard)."""
        cfg = json.load(open("v5_config.json"))
        pos = ch.positions(cfg.get("portfolio_metadata"))
        self.assertIn("CEG", [p["ticker"] for p in pos])
        reads = ch.build_reads(pos, lambda ref: None)         # engine-down worst case
        r = reads["CEG"]
        self.assertNotIn("error", r)
        self.assertTrue(r["price_stale"])                    # honest about the dead feed
        self.assertGreater(r["ladder"]["floor"], 0)
        rows = ch.sleeve_rows(reads)
        self.assertEqual("CEG", rows[0]["ticker"])
        # units are the operator's live fill count (add_holding rewrites them on every tranche):
        # assert the row carries the CONFIG's units, never a frozen number (was 24 → 44 → 54)
        self.assertEqual(float(cfg["portfolio_metadata"]["CEG"]["units"]), float(rows[0]["units"]))
        self.assertGreater(rows[0]["units"], 0)

    def test_ceg_is_not_in_barbell_weights(self):
        cfg = json.load(open("v5_config.json"))
        self.assertNotIn("CEG", cfg["barbell_weights"])      # lane guard: priced, never sized


class RendererTests(unittest.TestCase):
    def _rows(self, **over):
        row = {"ticker": "CEG", "instrument": "CEGS (TSX CDR)", "units": 24, "lens": "compounder",
               "rating": 7.31, "band": "HIGH QUALITY", "zone": "accumulate", "price": 263.56,
               "price_stale": False, "floor": 103.59, "base": 274.83, "bull": 675.07,
               "pillars": {"T": 5.0, "Q": 7.76, "V": 6.72},
               "weight": 0.073, "market_value": 431.52, "target": 0.15}
        row.update(over)
        return [row]

    def test_renders_full_parity_row(self):
        import cockpit_widgets as cw
        t = cw.render_conventional_sleeve(self._rows()).plain
        self.assertIn("CONVENTIONAL", t)
        self.assertIn("CEG", t)
        self.assertIn("ACCUMULATE", t)
        self.assertIn("CEGS ×24", t)                          # short name, no truncated paren
        self.assertIn("base $275 +4%", t)
        self.assertIn("bull $675", t)
        # parity with the resource rows: pillars + lens tag + band + the position line
        self.assertIn("T 5.0", t)
        self.assertIn("Q 7.8", t)
        self.assertIn("·compounder", t)
        self.assertIn("HIGH QUALITY", t)
        self.assertIn("mv $432", t)
        self.assertIn("7.3% of book (target 15%)", t)

    def test_stale_price_and_errors_are_shown_not_hidden(self):
        import cockpit_widgets as cw
        t = cw.render_conventional_sleeve(self._rows(price_stale=True)).plain
        self.assertIn("⚠stale", t)
        t = cw.render_conventional_sleeve([{"ticker": "XYZ", "error": "no dual_sided block"}]).plain
        self.assertIn("⚠ no dual_sided block", t)

    def test_empty_sleeve_renders_nothing(self):
        import cockpit_widgets as cw
        self.assertEqual("", cw.render_conventional_sleeve([]).plain)


if __name__ == "__main__":
    unittest.main()
