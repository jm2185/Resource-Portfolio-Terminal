"""The 2026-07-03 compute-integrity pass — three guards born from one lesson (context-blind numbers
silently poisoning judgment):

1. council._engine_break — the flat spear-tuned ``φ < 0.9`` fired ``engine_break=true`` on every
   healthy ballast (GMX φ 0.36; the council had to hand-annotate it as "a thin-floor note"). Now
   archetype-aware: asymmetry-mode names break on φ/ρ; value-mode names break on materially-rich
   upside or a placeholder-zone floor — and the flag always carries its reason.
2. replay.detect_store_seams / cross_check.store_seam_check — the GROY currency seam (USD backfill
   next to CAD ledger marks) fabricated −30%% grades that replay reported as model failures. Grading
   now detects a same-date basis divergence and REFUSES to grade the seamed ticker, reporting a
   data_seam record instead.
3. discovery_screen currency contract — the screen's gates read *_cad_m fields; a non-CAD candidate
   now carries a first-class data gap telling @verifier to confirm the FX conversion.
"""
import unittest

import cross_check
import replay
from council import _engine_break


class EngineBreakArchetypeAware(unittest.TestCase):
    def test_spear_breaks_on_phi(self):
        broke, reason = _engine_break("option_convexity", phi=0.85)
        self.assertTrue(broke)
        self.assertIn("REP floor", reason)

    def test_spear_breaks_on_rho(self):
        broke, reason = _engine_break("option_convexity", phi=1.2, rho=0.4)
        self.assertTrue(broke)
        self.assertIn("payoff", reason)

    def test_healthy_ballast_phi_does_not_break(self):
        # GMX.TO 2026-07-03: φ 0.36 on asset_light_yield fired the old flat threshold.
        broke, reason = _engine_break("asset_light_yield", phi=0.36, rho=None, upside_pct=6.9)
        self.assertFalse(broke)
        self.assertEqual(reason, "")

    def test_value_mode_breaks_when_materially_rich(self):
        broke, reason = _engine_break("asset_light_yield", phi=0.4, upside_pct=-25.0)
        self.assertTrue(broke)
        self.assertIn("rich", reason)

    def test_value_mode_breaks_on_placeholder_zone_floor(self):
        # the collapsed-cache signature: floor ~10% of price
        broke, reason = _engine_break("asset_light_yield", phi=0.11)
        self.assertTrue(broke)
        self.assertIn("backstop", reason)

    def test_severe_gate_breaks_any_archetype(self):
        for arch in ("option_convexity", "asset_light_yield", "commodity_cyclical"):
            broke, reason = _engine_break(arch, phi=1.5, severe_gate=True)
            self.assertTrue(broke)
            self.assertIn("forensic", reason)

    def test_verdict_payload_carries_the_reason(self):
        import council
        facts = {"ticker": "GMX.TO", "archetype": "asset_light_yield",
                 "directive": "FAIR VALUE — HOLD",
                 "asymmetry": {"floor_coverage": 0.36, "rho": None, "upside_pct": 6.9},
                 "gate": {"applied": False}, "ladder": {"floor": 0.71}}
        v = council.reconcile(facts, [], [])
        self.assertFalse(v["engine_break"])               # healthy ballast: no break
        self.assertIn("engine_break_reason", v)


class StoreSeamDetection(unittest.TestCase):
    def test_currency_seam_is_flagged(self):
        # the GROY shape: every same-date pair ~40% apart (CAD ledger vs USD store)
        pairs = [("GROY", f"2026-06-{d:02d}", 4.0, 2.86) for d in range(15, 20)]
        out = cross_check.store_seam_check(pairs)
        self.assertTrue(out["GROY"]["seamed"])
        self.assertGreater(out["GROY"]["median_divergence"], 0.25)
        self.assertIn("note", out["GROY"])

    def test_consistent_stores_are_clean(self):
        pairs = [("AGA.V", f"2026-06-{d:02d}", 0.63, 0.63) for d in range(15, 20)]
        out = cross_check.store_seam_check(pairs)
        self.assertFalse(out["AGA.V"]["seamed"])

    def test_one_restated_print_does_not_trip_the_median(self):
        pairs = [("URC.TO", "2026-06-15", 4.24, 4.24),
                 ("URC.TO", "2026-06-16", 4.30, 4.30),
                 ("URC.TO", "2026-06-17", 4.10, 4.10),
                 ("URC.TO", "2026-06-18", 4.00, 5.60)]     # one outlier (restatement/split)
        out = cross_check.store_seam_check(pairs)
        self.assertFalse(out["URC.TO"]["seamed"])

    def test_fewer_than_three_pairs_never_seams(self):
        out = cross_check.store_seam_check([("X", "2026-06-15", 4.0, 2.8),
                                            ("X", "2026-06-16", 4.0, 2.8)])
        self.assertFalse(out["X"]["seamed"])


class GradeLedgerRefusesSeams(unittest.TestCase):
    class _Ledger:
        def __init__(self, snaps): self._s = snaps
        def query(self, limit=0, newest_first=False): return list(self._s)

    def test_seamed_ticker_grades_suppressed_with_record(self):
        import os, tempfile
        import price_history as ph
        tmp = tempfile.TemporaryDirectory()
        h = ph.PriceHistory(path=os.path.join(tmp.name, "ph.json"))
        # store holds USD-basis closes for GROY (the seam) and a clean CAD name
        snaps = []
        for d in range(10, 16):
            day = f"2026-03-{d:02d}"
            h.force_set("GROY", day, 2.86)                 # USD in the store
            h.force_set("AGA.V", day, 0.63)
            snaps.append({"ticker": "GROY", "ts": day, "price": 4.0, "intrinsic": 4.5,
                          "archetype": "asset_light_yield"})
            snaps.append({"ticker": "AGA.V", "ts": day, "price": 0.63, "intrinsic": 1.9,
                          "archetype": "option_convexity"})
        grades = replay.grade_ledger(self._Ledger(snaps), h, horizon_days=1)
        seam_recs = [g for g in grades if g.get("data_seam")]
        graded_tks = {g["ticker"] for g in grades if g.get("realized_return") is not None}
        self.assertEqual([r["ticker"] for r in seam_recs], ["GROY"])   # one seam record, not grades
        self.assertNotIn("GROY", graded_tks)                # no fabricated GROY grades
        self.assertIn("AGA.V", graded_tks)                  # the clean name still grades
        tmp.cleanup()


class ScreenCurrencyContract(unittest.TestCase):
    @staticmethod
    def _cand(**kw):
        base = {"ticker": "TEST.V", "name": "Test Co", "slots": ["silver-spear"],
                "vehicle": "explorer", "commodity": "silver", "stage": "pea",
                "fraser_index": 80.0, "mcap_cad_m": 60.0, "runway_months": 18.0,
                "dilution_annual": 0.08, "cash_cad_m": 20.0,
                "stressed_in_ground_cad_m": 40.0, "ev_cad_m": 50.0}
        base.update(kw)
        return base

    def test_non_cad_survivor_carries_the_fx_gap(self):
        import discovery_screen as ds
        out = ds.screen([self._cand(ticker="USGO", currency="USD")], slot="silver-spear")
        surv = [s for s in out.get("survivors", []) if s.get("ticker") == "USGO"]
        self.assertTrue(surv, f"candidate unexpectedly killed: {out.get('killed')}")
        gaps = " ".join(surv[0].get("data_gaps", []))
        self.assertIn("currency=USD", gaps)
        self.assertIn("FX-converted", gaps)

    def test_cad_survivor_has_no_fx_gap(self):
        import discovery_screen as ds
        out = ds.screen([self._cand(currency="CAD")], slot="silver-spear")
        self.assertTrue(out.get("survivors"))
        for s in out["survivors"]:
            self.assertNotIn("currency=", " ".join(s.get("data_gaps", [])))


if __name__ == "__main__":
    unittest.main()
