"""The price-history store is uniformly CAD (the engine marks the book in CAD, the ledger stamps
CAD), so a USD-listed name's Yahoo close — which arrives in USD — MUST be converted before it lands.
Storing it raw is the GROY currency seam: GROY sat at ~2.86 USD next to ~4.0 CAD neighbours, so every
replay grade divided a USD forward close by a CAD mark and manufactured a ~-30% drop.

These tests pin the fix WITHOUT a network: the pure conversion, the pure mis-currency detector, a
currency-aware backfill (via an injected source), and the remediation of already-poisoned rows —
proving CAD names are never touched and only pre-conversion USD rows get corrected.
"""
import os
import tempfile
import unittest

import price_history as ph


FX = 1.395   # USD/CAD used across the fixtures


def _sources(native_by_ticker: dict, fx: float = FX):
    """Fake (closes_fn, fx_series) for backfill/repair — no yfinance, deterministic."""
    dates = set()
    for m in native_by_ticker.values():
        dates.update(m)
    fx_series = {d: fx for d in dates}

    def closes_fn(t):
        if t == "USDCAD=X":
            return dict(fx_series)
        return dict(native_by_ticker.get(t, {}))
    return closes_fn, fx_series


class ToStoreCurrency(unittest.TestCase):
    def test_usd_converts_to_cad(self):
        self.assertAlmostEqual(ph.to_store_ccy(2.86, "USD", 1.395), 2.86 * 1.395, places=6)

    def test_cad_and_unknown_pass_through(self):
        self.assertEqual(ph.to_store_ccy(4.06, "CAD", 1.395), 4.06)
        self.assertEqual(ph.to_store_ccy(4.06, None, 1.395), 4.06)

    def test_missing_fx_never_scales(self):
        self.assertEqual(ph.to_store_ccy(2.86, "USD", None), 2.86)


class WrongCurrencyDetector(unittest.TestCase):
    def test_raw_usd_row_is_flagged(self):
        # stored 2.86 (raw USD) vs correct 3.99 (CAD) → poisoned
        self.assertTrue(ph.looks_wrong_currency(2.86, 2.86, 2.86 * FX))

    def test_correct_cad_row_is_clean(self):
        self.assertFalse(ph.looks_wrong_currency(2.86 * FX, 2.86, 2.86 * FX))

    def test_cad_name_can_never_trip(self):
        # a CAD name: native == converted (no fx gap) → detector must not fire on any stored value
        self.assertFalse(ph.looks_wrong_currency(4.06, 4.06, 4.06))


class CurrencyAwareBackfill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))
        self.ccy = lambda t: {"GROY": "USD"}.get(t, "CAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_usd_name_lands_in_cad_cad_name_untouched(self):
        native = {"GROY": {"2026-06-15": 2.86, "2026-06-16": 2.90},
                  "AGA.V": {"2026-06-15": 0.63}}
        res = ph.backfill_from_yahoo(self.h, ["GROY", "AGA.V"], currency_of=self.ccy,
                                     _sources=_sources(native))
        self.assertTrue(res["ok"])
        # GROY stored in CAD (converted), AGA.V stored as-is
        self.assertAlmostEqual(self.h.close_on("GROY", "2026-06-15")["close"], 2.86 * FX, places=4)
        self.assertEqual(self.h.close_on("AGA.V", "2026-06-15")["close"], 0.63)
        self.assertEqual(res["results"]["GROY"]["converted_to_cad"], 2)
        self.assertEqual(res["results"]["AGA.V"]["currency"], "CAD")

    def test_no_double_conversion_on_rerun(self):
        native = {"GROY": {"2026-06-15": 2.86}}
        src = _sources(native)
        ph.backfill_from_yahoo(self.h, ["GROY"], currency_of=self.ccy, _sources=src)
        first = self.h.close_on("GROY", "2026-06-15")["close"]
        # re-run: the CAD row already exists → record_many dedups, value stays put (not ×fx again)
        ph.backfill_from_yahoo(self.h, ["GROY"], currency_of=self.ccy, _sources=src)
        self.assertAlmostEqual(self.h.close_on("GROY", "2026-06-15")["close"], first, places=6)


class CurrencyRepair(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = ph.PriceHistory(path=os.path.join(self.tmp.name, "ph.json"))
        self.ccy = lambda t: {"GROY": "USD"}.get(t, "CAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_repair_corrects_only_poisoned_usd_rows(self):
        # seed a poisoned USD row (raw 2.86) and a clean CAD row (3.99) for GROY, plus a CAD name
        self.h.force_set("GROY", "2026-06-15", 2.86)          # poisoned (stored as USD)
        self.h.force_set("GROY", "2026-06-16", 2.90 * FX)     # already correct CAD
        self.h.force_set("AGA.V", "2026-06-15", 0.63)         # CAD name, must stay
        native = {"GROY": {"2026-06-15": 2.86, "2026-06-16": 2.90}, "AGA.V": {"2026-06-15": 0.63}}
        src = _sources(native)

        dry = ph.repair_currency(self.h, ["GROY", "AGA.V"], currency_of=self.ccy, _sources=src)
        self.assertEqual(dry["fixed"], 1)                     # only the poisoned GROY row
        self.assertEqual(self.h.close_on("GROY", "2026-06-15")["close"], 2.86)  # dry-run: unchanged

        applied = ph.repair_currency(self.h, ["GROY", "AGA.V"], currency_of=self.ccy,
                                     apply=True, _sources=src)
        self.assertEqual(applied["fixed"], 1)
        self.assertAlmostEqual(self.h.close_on("GROY", "2026-06-15")["close"], 2.86 * FX, places=4)
        self.assertAlmostEqual(self.h.close_on("GROY", "2026-06-16")["close"], 2.90 * FX, places=4)
        self.assertEqual(self.h.close_on("AGA.V", "2026-06-15")["close"], 0.63)  # never touched

    def test_repair_is_idempotent(self):
        self.h.force_set("GROY", "2026-06-15", 2.86)
        native = {"GROY": {"2026-06-15": 2.86}}
        src = _sources(native)
        ph.repair_currency(self.h, ["GROY"], currency_of=self.ccy, apply=True, _sources=src)
        again = ph.repair_currency(self.h, ["GROY"], currency_of=self.ccy, apply=True, _sources=src)
        self.assertEqual(again["fixed"], 0)                   # nothing left to correct


if __name__ == "__main__":
    unittest.main()
