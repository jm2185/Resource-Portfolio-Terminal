"""kalshi_client — wire-format normalization + snapshot assembly, NO live network.

The transport is injected (url → canned dict), so the suite validates both API vintages (the
current ``*_dollars`` strings / ``orderbook_fp`` and the legacy integer-cents fields), the
complementary-side fill, cursor paging, and per-series error stamping."""
from __future__ import annotations

import unittest

import kalshi_client as kc


class TestParseMarket(unittest.TestCase):
    def test_current_dollars_format(self):
        m = kc.parse_market({
            "ticker": "KXFED-26SEP-T2.75", "event_ticker": "KXFED-26SEP",
            "strike_type": "greater", "floor_strike": 2.75, "status": "active",
            "close_time": "2026-09-16T18:00:00Z",
            "yes_bid_dollars": "0.9900", "yes_ask_dollars": "1.0000",
            "no_bid_dollars": "0.0000", "no_ask_dollars": "0.0100",
            "yes_bid_size_fp": "151.74", "yes_ask_size_fp": "1821.83",
            "last_price_dollars": "0.9900", "liquidity_dollars": "1234.00",
            "volume_24h_fp": "1.12", "open_interest_fp": "40012.09"})
        self.assertEqual(m["yes_bid"], 0.99)
        self.assertEqual(m["yes_ask"], 1.0)
        self.assertEqual(m["no_ask"], 0.01)
        self.assertIsNone(m["no_bid"])              # "0.0000" is unquoted, then 1-yes_ask = 0.0 -> None
        self.assertEqual(m["yes_bid_size"], 151.74)
        self.assertEqual(m["floor_strike"], 2.75)

    def test_legacy_cents_format(self):
        m = kc.parse_market({"ticker": "T", "yes_bid": 13, "yes_ask": 15, "no_bid": 85, "no_ask": 87})
        self.assertEqual(m["yes_bid"], 0.13)
        self.assertEqual(m["no_ask"], 0.87)

    def test_complementary_fill(self):
        # only the YES side quoted -> NO side derived from the complementary book identity
        m = kc.parse_market({"ticker": "T", "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4300"})
        self.assertEqual(m["no_ask"], 0.60)         # 1 - yes_bid
        self.assertEqual(m["no_bid"], 0.57)         # 1 - yes_ask

    def test_thin_market_never_raises(self):
        m = kc.parse_market({})
        self.assertIsNone(m["yes_ask"])
        self.assertEqual(m["ticker"], "")
        self.assertIsNone(kc.parse_market({"yes_ask_dollars": "garbage"})["yes_ask"])


class TestParseOrderbook(unittest.TestCase):
    def test_fp_dollars_levels_sorted_best_first(self):
        ob = kc.parse_orderbook({"orderbook_fp": {
            "yes_dollars": [["0.10", "50"], ["0.12", "151.74"]],
            "no_dollars": [["0.85", "10"]]}})
        self.assertEqual(ob["yes"], [(0.12, 151.74), (0.10, 50.0)])
        self.assertEqual(ob["no"], [(0.85, 10.0)])

    def test_legacy_cents_levels(self):
        ob = kc.parse_orderbook({"orderbook": {"yes": [[12, 100]], "no": []}})
        self.assertEqual(ob["yes"], [(0.12, 100.0)])
        self.assertEqual(ob["no"], [])

    def test_empty_and_garbage(self):
        self.assertEqual(kc.parse_orderbook({}), {"yes": [], "no": []})
        self.assertEqual(kc.parse_orderbook({"orderbook_fp": {"yes_dollars": [["x"], None]}})["yes"], [])


def _fake_transport(pages: dict):
    """url -> canned payload; records the urls it served."""
    calls = []

    def transport(url: str) -> dict:
        calls.append(url)
        for key, payload in pages.items():
            if key in url:
                return payload
        return {}
    transport.calls = calls
    return transport


class TestClientAndSnapshot(unittest.TestCase):
    def _client(self, pages):
        return kc.KalshiPublicClient(transport=_fake_transport(pages), min_interval_s=0.0)

    def test_cursor_paging_stops_on_empty_cursor(self):
        pages = {"cursor=abc": {"events": [{"event_ticker": "E2"}], "cursor": ""},
                 "/events": {"events": [{"event_ticker": "E1"}], "cursor": "abc"}}
        c = self._client(pages)
        evs = c.get_series_events("KXFED")
        self.assertEqual([e["event_ticker"] for e in evs], ["E1", "E2"])

    def test_build_snapshot_normalizes_and_stamps_errors(self):
        ev = {"event_ticker": "KXFED-26SEP", "series_ticker": "KXFED", "title": "Fed",
              "category": "Economics", "mutually_exclusive": False, "available_on_brokers": True,
              "markets": [{"ticker": "M1", "yes_ask_dollars": "0.5000", "yes_bid_dollars": "0.4800"}]}
        pages = {"series_ticker=KXFED": {"events": [ev], "cursor": ""},
                 "series_ticker=KXEMPTY": {"events": [], "cursor": ""},
                 "/markets/M1/orderbook": {"orderbook_fp": {"yes_dollars": [["0.48", "10"]],
                                                            "no_dollars": [["0.50", "5"]]}}}
        c = self._client(pages)
        snap = kc.build_snapshot(c, series=["KXFED", "KXEMPTY"], orderbook_tickers=["M1"],
                                 now_ts=123.0)
        self.assertEqual(snap["ts"], 123.0)
        self.assertEqual(len(snap["events"]), 1)
        self.assertEqual(snap["events"][0]["markets"][0]["yes_ask"], 0.50)
        self.assertTrue(snap["events"][0]["available_on_brokers"])
        self.assertEqual(snap["orderbooks"]["M1"]["yes"], [(0.48, 10.0)])
        self.assertEqual([e["series"] for e in snap["errors"]], ["KXEMPTY"])

    def test_cache_serves_repeats_without_refetch(self):
        pages = {"/events": {"events": [], "cursor": ""}}
        t = _fake_transport(pages)
        c = kc.KalshiPublicClient(transport=t, min_interval_s=0.0, cache_ttl_s=60.0)
        c.get_events(series_ticker="KXFED")
        c.get_events(series_ticker="KXFED")
        self.assertEqual(len(t.calls), 1)

    def test_transport_failure_returns_none(self):
        def boom(url):
            raise OSError("net down")
        c = kc.KalshiPublicClient(transport=boom, min_interval_s=0.0)
        self.assertIsNone(c.get_orderbook("M1"))
        snap = kc.build_snapshot(c, series=["KXFED"])
        self.assertEqual(snap["events"], [])
        self.assertTrue(snap["errors"])

    def test_no_order_endpoints_exist(self):
        # read-only BY CONSTRUCTION: the client must never grow trade/portfolio surface
        for banned in ("create_order", "place_order", "cancel_order", "portfolio", "login"):
            self.assertFalse(hasattr(kc.KalshiPublicClient, banned))


if __name__ == "__main__":
    unittest.main()
