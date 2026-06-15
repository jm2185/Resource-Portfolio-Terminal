"""
Tests for the logo cache (matrix/logos.py) and the per-name detail card (matrix/screens/detail.py).
The render path is cache-only (no network); fetch is exercised live. Microcaps with no logo fall back
to text — the card must always render at 128x64 and never crash on missing data.
"""
import io
import tempfile
import unittest

from PIL import Image

from matrix import logos
from matrix.contract import CatalystRef, MatrixState, WatchItem
from matrix.screens.detail import detail_card, render


class LogoCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig, logos.CACHE_DIR = logos.CACHE_DIR, self.tmp

    def tearDown(self):
        logos.CACHE_DIR = self._orig

    def test_missing_returns_none(self):
        self.assertFalse(logos.has_logo("AGA.V"))
        self.assertIsNone(logos.load_logo("AGA.V", (20, 20)))

    def test_cache_image_and_load_fitted(self):
        logos.cache_logo("LUN.TO", Image.new("RGB", (64, 48), (0, 200, 80)))
        self.assertTrue(logos.has_logo("LUN.TO"))
        out = logos.load_logo("LUN.TO", (24, 24))
        self.assertEqual((out.size, out.mode), ((24, 24), "RGB"))

    def test_cache_from_bytes(self):
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), (255, 0, 0)).save(buf, "PNG")
        self.assertIsNotNone(logos.cache_logo("U.UN.TO", buf.getvalue()))
        self.assertTrue(logos.has_logo("U.UN.TO"))

    def test_bad_bytes_no_crash(self):
        self.assertIsNone(logos.cache_logo("BAD.TO", b"not an image"))


class _NoLogoFMP:
    def profile(self, ticker):
        return {"data": {}}


class FetchTests(unittest.TestCase):
    def test_fetch_without_keys_is_false_offline(self):
        # no Finnhub key + an FMP stub with no image -> no network, returns False
        self.assertFalse(logos.fetch_logo("AGA.V", finnhub_key="", fmp_client=_NoLogoFMP()))


class DetailCardTests(unittest.TestCase):
    MS = MatrixState(
        watchlist=(WatchItem("AGA", "AGA.V", 1.0, 2.4, rating=8.7, directive="ACCUMULATE",
                             rho=3.2, floor_coverage=1.85),),
        next_catalyst=CatalystRef("DRILL", 12))

    def test_renders_128x64(self):
        self.assertEqual(render(self.MS).size, (128, 64))

    def test_no_holdings_is_safe(self):
        self.assertEqual(render(MatrixState()).size, (128, 64))

    def test_none_fields_do_not_crash(self):
        detail_card(MatrixState(), WatchItem("X", "X.TO"))


if __name__ == "__main__":
    unittest.main()
