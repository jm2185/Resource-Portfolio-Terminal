"""
Tests for the matrix price sources (matrix/prices.py) — offline/degrade paths only (no live network):
empty input, no-key short-circuit, and the env-key reader. Live fetches are verified on a real run.
"""
import unittest

from matrix import prices


class PriceSourceTests(unittest.TestCase):
    def test_yfinance_empty_is_empty_dict(self):
        self.assertEqual(prices.yfinance_price_fetcher([]), {})

    def test_yfinance_returns_dict(self):
        self.assertIsInstance(prices.yfinance_price_fetcher([]), dict)

    def test_finnhub_without_key_short_circuits(self):
        self.assertEqual(prices.finnhub_price_fetcher(["AGA.V"], key=""), {})   # no key -> no network

    def test_env_key_absent_is_empty(self):
        self.assertEqual(prices.env_key("NOPE_NOT_A_REAL_ENV_KEY_12345"), "")


if __name__ == "__main__":
    unittest.main()
