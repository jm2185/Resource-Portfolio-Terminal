"""Valuation ledger (Phase 1 of the validation flywheel) — append-only mechanics, cadence gate,
Goodhart guard, point-in-time input immunity."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import valuation_ledger as vl


def _basket(ticker="AGA.V", *, intrinsic=1.05, band="STRONG ASYMMETRY",
            directive="STRONG ASYMMETRY — WATCH CLOSELY", cap=10.0, rho=3.1, phi=0.85):
    return {
        "ticker": ticker, "archetype": "option_convexity",
        "rating": 7.8, "band": band, "directive": directive,
        "pillars": {"T": {"score": 7.0}, "Q": {"score": 6.5},
                    "V": {"score": 8.2, "rho": rho, "floor_coverage": phi}},
        "gate": {"cap": cap, "reason": "clean"},
        "confidence_ribbon": {"plus_minus": 0.9, "quality": "full"},
        "ladder": {"floor": 0.52, "bear": 0.48, "base": intrinsic, "bull": 2.10, "price": 0.61},
    }


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ledger.jsonl")
        self.led = vl.ValuationLedger(path=self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_assigns_identity_and_validates(self):
        rec = self.led.record(vl.snapshot_from_basket(_basket()), trigger="manual")
        self.assertEqual(rec["schema_version"], vl.SCHEMA_VERSION)
        self.assertEqual(rec["trigger"], "manual")
        self.assertTrue(rec["id"] and rec["ts"] and rec["fingerprint"])
        with self.assertRaises(ValueError):
            self.led.record(vl.snapshot_from_basket(_basket()), trigger="whenever")
        with self.assertRaises(ValueError):
            self.led.record({"intrinsic": 1.0}, trigger="manual")     # no ticker

    def test_append_only_no_mutation_api(self):
        for name in ("update", "delete", "edit", "overwrite", "remove"):
            self.assertFalse(hasattr(self.led, name), f"mutation path {name!r} must not exist")

    def test_maybe_record_seed_then_dedup(self):
        snap = vl.snapshot_from_basket(_basket())
        first = self.led.maybe_record(snap)
        self.assertEqual(first["trigger"], "seed")
        # identical state, same day -> NO new record (the eval loop can't flood the ledger)
        self.assertIsNone(self.led.maybe_record(vl.snapshot_from_basket(_basket())))
        self.assertEqual(self.led.stats()["records"], 1)

    def test_maybe_record_material_change(self):
        self.led.maybe_record(vl.snapshot_from_basket(_basket()))
        moved = self.led.maybe_record(vl.snapshot_from_basket(_basket(intrinsic=1.40)))
        self.assertEqual(moved["trigger"], "material_change")
        flipped = self.led.maybe_record(
            vl.snapshot_from_basket(_basket(intrinsic=1.40, directive="UPSIDE SPENT — HOLD / TRIM")))
        self.assertEqual(flipped["trigger"], "material_change")

    def test_maybe_record_daily_mark_after_date_roll(self):
        snap = vl.snapshot_from_basket(_basket())
        self.led.record(snap, trigger="seed", ts="2026-06-09T12:00:00Z")   # yesterday
        rec = self.led.maybe_record(vl.snapshot_from_basket(_basket()))
        self.assertEqual(rec["trigger"], "daily")

    def test_goodhart_guard_agent_payload_ignored(self):
        """Free-form top-level rho/legs in the payload must NOT leak into the snapshot —
        only the engine's fixed paths (pillars.V / asymmetry / ladder) count."""
        b = _basket(rho=3.1, phi=0.85)
        b["rho"] = 99.0                                # adversarial agent-supplied
        b["legs"] = {"floor": 5.0, "bull": 50.0}
        snap = vl.snapshot_from_basket(b)
        self.assertEqual(snap["asymmetry"]["rho"], 3.1)
        self.assertEqual(snap["ladder"]["bull"], 2.10)

    def test_inputs_copied_by_value_immune_to_restatement(self):
        prov = {"aisc_per_oz": {"value": 14.5, "as_of": "2026-01-01", "confidence": "high",
                                "source": "https://example.com/filing"}}
        inputs = vl.inputs_from_provenance(prov)
        rec = self.led.record(vl.snapshot_from_basket(_basket(), inputs=inputs), trigger="manual")
        prov["aisc_per_oz"]["value"] = 99.9            # the cache restates later...
        stored = self.led.get(rec["id"])
        self.assertEqual(stored["inputs"]["aisc_per_oz"]["value"], 14.5)   # ...the stamp is immune

    def test_torn_line_tolerated_and_visible(self):
        self.led.record(vl.snapshot_from_basket(_basket()), trigger="manual")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"torn": ')                      # a torn partial line
        self.led._cache = None
        self.assertEqual(len(self.led.all()), 1)
        self.assertEqual(self.led.stats()["skipped_lines"], 1)

    def test_query_filters_and_stats(self):
        self.led.record(vl.snapshot_from_basket(_basket("AGA.V")), trigger="manual")
        self.led.record(vl.snapshot_from_basket(_basket("GROY")), trigger="decision")
        self.assertEqual(len(self.led.query(ticker="aga.v")), 1)
        self.assertEqual(len(self.led.query(trigger="decision")), 1)
        st = self.led.stats()
        self.assertEqual(st["records"], 2)
        self.assertEqual(set(st["by_ticker"]), {"AGA.V", "GROY"})

    def test_method_spread(self):
        ms = vl.method_spread({"cost": 0.9, "market": 1.5, "income": 0.0},
                              {"cost": 0.3, "market": 0.7, "income": 0.0})
        self.assertEqual(ms["n_methods"], 2)           # zero-value & zero-weight income excluded
        self.assertAlmostEqual(ms["spread_pct"], (1.5 - 0.9) / 1.2 * 100, places=1)
        self.assertIsNone(vl.method_spread({"cost": 1.0}, {"cost": 1.0}))   # one method = no spread

    def test_projection_shape_tolerated(self):
        """The MCP projection carries asymmetry{rho,floor_coverage} instead of pillars.V."""
        proj = {"ticker": "URC.TO", "archetype": "asset_light_yield", "rating": 6.4,
                "band": "HIGH QUALITY", "directive": "QUALITY — CORE HOLD",
                "asymmetry": {"rho": 1.4, "floor_coverage": 1.1},
                "gate": {"cap": 10.0}, "ladder": {"floor": 3.1, "base": 4.4, "bull": 5.5,
                                                  "price": 4.0}}
        snap = vl.snapshot_from_basket(proj)
        self.assertEqual(snap["asymmetry"]["rho"], 1.4)
        self.assertEqual(snap["intrinsic"], 4.4)


if __name__ == "__main__":
    unittest.main()
