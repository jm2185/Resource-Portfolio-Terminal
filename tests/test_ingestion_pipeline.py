"""
Phase 6 — Ingestion pipeline test suite.

Fully offline / fixture-based (unittest + unittest.mock): every network and yfinance
call is patched to return captured sample payloads, so the suite is deterministic and
CI-safe (no live internet). Covers the numeric helpers, the FRED CSV parser + adapter,
SEC CIK resolution (incl. the foreign-suffix skip) and CompanyFacts mapping, the
fundamental primitives, the manual-override CSV, the opt-in sentiment adapter, the
capability merge precedence, the PayloadMapper schema, the cache round-trip + staleness,
the orchestrator, and a contract test feeding built payloads into the PolymorphicRouter.
"""

import json
import math
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import ingestion_pipeline as ip


class TestNumericHelpers(unittest.TestCase):
    def test_to_float(self):
        self.assertEqual(ip._to_float("3.5"), 3.5)
        self.assertIsNone(ip._to_float("."))        # FRED missing marker
        self.assertIsNone(ip._to_float(None))
        self.assertIsNone(ip._to_float(float("nan")))
        self.assertIsNone(ip._to_float(float("inf")))

    def test_clamp(self):
        self.assertEqual(ip.clamp(2.0, -1.0, 1.0), 1.0)
        self.assertEqual(ip.clamp(-2.0, -1.0, 1.0), -1.0)
        self.assertEqual(ip.clamp(0.5, -1.0, 1.0), 0.5)

    def test_usable(self):
        self.assertTrue(ip._usable(0.0))
        self.assertTrue(ip._usable("CAD"))
        self.assertFalse(ip._usable(None))
        self.assertFalse(ip._usable(float("nan")))


class TestFredAdapter(unittest.TestCase):
    def test_parse_skips_missing_dot(self):
        csv_body = "DATE,SOFR\n2024-01-01,5.31\n2024-01-02,.\n2024-01-03,5.33\n"
        self.assertEqual(ip._parse_fred_csv(csv_body, "SOFR"), 5.33)

    def test_parse_empty_or_headeronly(self):
        self.assertIsNone(ip._parse_fred_csv("", "SOFR"))
        self.assertIsNone(ip._parse_fred_csv("DATE,SOFR\n", "SOFR"))

    def test_fetch_maps_fields_to_series(self):
        adapter = ip.FredMacroAdapter({"sofr": "SOFR", "ted": "TEDRATE"})

        def fake_get_text(url, **_):
            if "id=SOFR" in url:
                return "DATE,SOFR\n2024-01-01,5.31\n"
            if "id=TEDRATE" in url:
                return "DATE,TEDRATE\n2024-01-01,0.20\n"
            return None

        with mock.patch.object(ip, "_http_get_text", side_effect=fake_get_text):
            frag = adapter.fetch([])
        self.assertEqual(frag["provider"], "fred")
        self.assertEqual(frag["fragments"]["macro"], {"sofr": 5.31, "ted": 0.20})

    def test_fetch_degrades_when_offline(self):
        adapter = ip.FredMacroAdapter({"sofr": "SOFR"})
        with mock.patch.object(ip, "_http_get_text", return_value=None):
            frag = adapter.fetch([])
        self.assertEqual(frag["fragments"], {})   # nothing fetched -> no macro capability


class TestSecEdgarAdapter(unittest.TestCase):
    def test_foreign_suffix_is_skipped(self):
        adapter = ip.SecEdgarAdapter()
        self.assertIsNone(adapter.resolve_cik("AGA.V"))
        self.assertIsNone(adapter.resolve_cik("URC.TO"))
        self.assertIsNone(adapter.resolve_cik("GMX.TO"))

    def test_explicit_map_wins(self):
        adapter = ip.SecEdgarAdapter(ticker_cik_map={"GROY": 1832433})
        self.assertEqual(adapter.resolve_cik("GROY"), "1832433")

    def test_resolve_via_index(self):
        adapter = ip.SecEdgarAdapter()
        index = {"0": {"cik_str": 1832433, "ticker": "GROY", "title": "Gold Royalty"}}
        with mock.patch.object(ip, "_http_get_json", return_value=index):
            self.assertEqual(adapter.resolve_cik("GROY"), "1832433")
            self.assertIsNone(adapter.resolve_cik("NOTREAL"))

    def test_company_facts_mapping(self):
        facts = {"facts": {"us-gaap": {
            ip.CASH_TAG: {"units": {"USD": [
                {"end": "2022-12-31", "val": 1000, "form": "10-K"},
                {"end": "2023-12-31", "val": 1500, "form": "10-K"}]}},
            ip.OCF_TAG: {"units": {"USD": [
                {"end": "2022-12-31", "val": -1200, "form": "10-K"},
                {"end": "2023-12-31", "val": -2400, "form": "10-K"}]}},
            ip.SHARES_TAG: {"units": {"shares": [
                {"end": "2022-12-31", "val": 1_000_000, "form": "10-K"},
                {"end": "2023-12-31", "val": 1_100_000, "form": "10-K"}]}},
        }}}
        fin = ip.FundamentalsMapper.from_company_facts(facts)
        self.assertEqual(fin["cash"], 1500.0)
        self.assertEqual(fin["curr_burn"], 2400.0)
        self.assertEqual(fin["prev_burn"], 1200.0)
        self.assertAlmostEqual(fin["monthly_burn"], 200.0)
        self.assertEqual(fin["shares_t0"], 1_100_000.0)
        self.assertEqual(fin["shares_t1"], 1_000_000.0)


class TestFundamentalPrimitives(unittest.TestCase):
    def test_runway_months(self):
        self.assertEqual(ip.FundamentalsMapper.runway_months(1000, 100), 10.0)
        self.assertIsNone(ip.FundamentalsMapper.runway_months(1000, 0))
        self.assertIsNone(ip.FundamentalsMapper.runway_months(None, 100))

    def test_cash_burn_acceleration(self):
        self.assertAlmostEqual(ip.FundamentalsMapper.cash_burn_acceleration(120, 100), 0.2)
        self.assertIsNone(ip.FundamentalsMapper.cash_burn_acceleration(120, 0))

    def test_dilution_velocity(self):
        self.assertAlmostEqual(ip.FundamentalsMapper.dilution_velocity(110, 100), 0.1)
        self.assertIsNone(ip.FundamentalsMapper.dilution_velocity(110, 0))


class TestYFinanceAdapter(unittest.TestCase):
    def test_fetch_financials_uses_info(self):
        fake_info = {"totalCash": 5.0e7, "sharesOutstanding": 2.0e8,
                     "ebitda": 4.0e7, "operatingCashflow": -1.2e7}
        fake_yf = mock.MagicMock()
        fake_yf.Ticker.return_value.info = fake_info
        with mock.patch.object(ip, "_import_yfinance", return_value=fake_yf):
            fin = ip.YFinanceFundamentalsAdapter().fetch_financials("URC.TO")
        self.assertEqual(fin["cash"], 5.0e7)
        self.assertEqual(fin["shares_t0"], 2.0e8)
        self.assertEqual(fin["curr_burn"], 1.2e7)         # negative OCF -> burn
        self.assertAlmostEqual(fin["monthly_burn"], 1.0e6)

    def test_unavailable_yfinance_degrades(self):
        with mock.patch.object(ip, "_import_yfinance", return_value=None):
            self.assertEqual(ip.YFinanceFundamentalsAdapter().fetch_financials("URC.TO"), {})


class TestManualOverrideAdapter(unittest.TestCase):
    def test_reads_long_format_csv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as fh:
            fh.write("ticker,capability,field,value\n")
            fh.write("# this is a comment row,,,\n")
            fh.write("URC.TO,financials,cash,12000000\n")
            fh.write("AGA.V,comps,peer_ev_oz,2.1\n")
            fh.write("ZZZ,financials,cash,5\n")            # not requested -> ignored
            path = fh.name
        try:
            frag = ip.ManualOverrideAdapter(path=path).fetch(["URC.TO", "AGA.V"])
        finally:
            os.unlink(path)
        self.assertEqual(frag["fragments"]["financials"]["URC.TO"], {"cash": 12000000.0})
        self.assertEqual(frag["fragments"]["comps"]["AGA.V"], {"peer_ev_oz": 2.1})
        self.assertNotIn("ZZZ", frag["fragments"].get("financials", {}))

    def test_missing_file_is_graceful(self):
        frag = ip.ManualOverrideAdapter(path="/no/such/file.csv").fetch(["URC.TO"])
        self.assertEqual(frag["fragments"], {})


class TestSentimentAdapter(unittest.TestCase):
    def test_disabled_contributes_nothing(self):
        frag = ip.SentimentAdapter(enabled=False).fetch(["AGA.V"])
        self.assertEqual(frag, {"provider": "sentiment", "fragments": {}})

    def test_enabled_returns_neutral_defaults(self):
        frag = ip.SentimentAdapter(enabled=True).fetch(["AGA.V"])
        conv = frag["fragments"]["conviction_signals"]["AGA.V"]
        self.assertEqual(conv["insider_net_buying"], 0.0)
        self.assertEqual(conv["short_interest_pressure"], 0.0)

    def test_signals_are_clamped(self):
        class Loud(ip.SentimentAdapter):
            def fetch_conviction(self, ticker):
                return {"insider_net_buying": 5.0, "short_interest_pressure": -3.0}

        conv = Loud(enabled=True).fetch(["X"])["fragments"]["conviction_signals"]["X"]
        self.assertEqual(conv["insider_net_buying"], 1.0)        # clamped to [-1, 1]
        self.assertEqual(conv["short_interest_pressure"], 0.0)   # clamped to [0, 1]


class TestMergeByCapability(unittest.TestCase):
    def test_field_level_precedence(self):
        fragments = [
            {"provider": "yfinance_fundamentals",
             "fragments": {"financials": {"URC.TO": {"cash": 1.0, "ebitda": 9.0}}}},
            {"provider": "sec_edgar",
             "fragments": {"financials": {"URC.TO": {"cash": 2.0}}}},
            {"provider": "manual_override",
             "fragments": {"financials": {"URC.TO": {"cash": 3.0}}}},
        ]
        merged = ip.merge_by_capability(
            fragments,
            precedence={"financials": ["manual_override", "sec_edgar", "yfinance_fundamentals"]})
        fin = merged["tickers"]["URC.TO"]["financials"]
        self.assertEqual(fin["cash"], 3.0)     # manual override wins
        self.assertEqual(fin["ebitda"], 9.0)   # only yfinance supplied it

    def test_macro_merge(self):
        merged = ip.merge_by_capability([{"provider": "fred", "fragments": {"macro": {"sofr": 5.3}}}])
        self.assertEqual(merged["macro"], {"sofr": 5.3})


class TestPayloadMapper(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "ballast_valuation": {"GROY": {"currency": "USD"}, "URC.TO": {"currency": "CAD"}},
            "aga_shares_out": 208_600_000.0,
        }
        self.mapper = ip.PayloadMapper(self.cfg)

    def test_currency_resolution(self):
        self.assertEqual(self.mapper._currency("GROY"), "USD")
        self.assertEqual(self.mapper._currency("URC.TO"), "CAD")
        self.assertEqual(self.mapper._currency("AGA.V"), "CAD")   # .V foreign suffix -> CAD

    def test_build_payload_matches_schema(self):
        merged = {"macro": {"sofr": 5.3, "real_yield": 2.1},
                  "tickers": {"AGA.V": {
                      "financials": {"cash": 5.0e7, "monthly_burn": 5.0e5,
                                     "shares_t0": 2.0e8, "shares_t1": 1.9e8},
                      "comps": {"peer_ev_oz": 2.1}}}}
        payload = self.mapper.build_all(["AGA.V"], merged)["tickers"]["AGA.V"]
        self.assertEqual(payload["currency"], "CAD")
        self.assertEqual(payload["macro"]["sofr"], 5.3)
        self.assertEqual(payload["comps"]["peer_ev_oz"], 2.1)
        self.assertEqual(payload["shares_out"], 2.0e8)            # from shares_t0
        self.assertAlmostEqual(payload["financials"]["runway_months"], 100.0)
        self.assertIn("dilution_velocity", payload["financials"])


class TestIngestionCache(unittest.TestCase):
    def test_roundtrip_and_staleness(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "ingestion_cache.json")   # nested dir auto-created
            cache = ip.IngestionCache(path)
            cache.write({"macro": {"sofr": 5.3}, "tickers": {}}, sources_meta={"fred": {"status": "ok"}})
            self.assertTrue(os.path.exists(path))
            env = cache.read()
            self.assertEqual(env["data"]["macro"]["sofr"], 5.3)
            self.assertEqual(env["schema_version"], ip.SCHEMA_VERSION)
            self.assertFalse(ip.IngestionCache.is_stale(env, 3600))
            env["generated_at"] = time.time() - 10_000
            self.assertTrue(ip.IngestionCache.is_stale(env, 3600))

    def test_load_missing_returns_none(self):
        self.assertIsNone(ip.load_ingestion_cache("/nonexistent/path/x.json"))

    def test_load_stale_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            ip.IngestionCache(path).write({"a": 1}, sources_meta={})
            self.assertIsNotNone(ip.load_ingestion_cache(path, max_age_seconds=3600))
            self.assertIsNone(ip.load_ingestion_cache(path, max_age_seconds=-1))

    def test_load_corrupt_returns_none(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not valid json")
            path = fh.name
        try:
            self.assertIsNone(ip.load_ingestion_cache(path))
        finally:
            os.unlink(path)


class TestPipelineOrchestrator(unittest.TestCase):
    def test_run_with_registered_stub(self):
        @ip.register_adapter("stub_macro_test")
        class _StubMacro(ip.BaseAdapter):
            provides = (ip.CAP_MACRO,)

            @classmethod
            def from_config(cls, params):
                return cls()

            def fetch(self, tickers):
                return {"provider": "stub_macro_test", "fragments": {"macro": {"sofr": 5.3}}}

        try:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "cache.json")
                cfg = {"portfolio_metadata": {"AGA.V": {}},
                       "ingestion": {"providers": [{"name": "stub_macro_test", "enabled": True}],
                                     "cache_path": path}}
                summary = ip.IngestionPipeline(config=cfg, cache_path=path).run()
                self.assertEqual(summary["ticker_count"], 1)
                self.assertIn("sofr", summary["macro_keys"])
                self.assertEqual(summary["sources"]["stub_macro_test"]["status"], "ok")
                self.assertTrue(os.path.exists(path))
        finally:
            ip.ADAPTER_REGISTRY.pop("stub_macro_test", None)

    def test_failing_adapter_does_not_crash_run(self):
        @ip.register_adapter("stub_boom_test")
        class _Boom(ip.BaseAdapter):
            provides = (ip.CAP_FIN,)

            @classmethod
            def from_config(cls, params):
                return cls()

            def fetch(self, tickers):
                raise RuntimeError("boom")

        try:
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "cache.json")
                cfg = {"ingestion": {"providers": [{"name": "stub_boom_test", "enabled": True}],
                                     "cache_path": path}}
                summary = ip.IngestionPipeline(config=cfg, cache_path=path).run(["AGA.V"])
                self.assertEqual(summary["sources"]["stub_boom_test"]["status"], "failed")
                self.assertTrue(os.path.exists(path))    # still wrote a (degraded) cache
        finally:
            ip.ADAPTER_REGISTRY.pop("stub_boom_test", None)


class TestRouterContract(unittest.TestCase):
    """The built payloads must flow through the real PolymorphicRouter without crashing."""

    def setUp(self):
        try:
            from archetypes import build_default_router, NEUTRAL_REGIME
        except Exception as exc:                          # pragma: no cover
            self.skipTest(f"archetypes unavailable: {exc}")
        try:
            with open("v5_config.json", "r") as fh:
                self.cfg = json.load(fh)
        except OSError as exc:                            # pragma: no cover
            self.skipTest(f"v5_config.json unavailable: {exc}")
        self.router = build_default_router(self.cfg)
        self.neutral = NEUTRAL_REGIME
        self.mapper = ip.PayloadMapper(self.cfg)

    def test_built_payloads_value_without_crashing(self):
        merged = {
            "macro": {"spot_ag": 75.6, "gold": 2650.0, "real_yield": 2.1, "silver_vol": 0.30,
                      "y30": 4.99, "capital_discount": 0.88, "sofr": 5.31, "m2v": 1.39, "ted": 0.2},
            "tickers": {
                "AGA.V": {"financials": {"cash": 5.307e7, "monthly_burn": 7.5e5, "shares_t0": 2.086e8,
                                         "shares_t1": 2.086e8, "curr_burn": 2.25e6, "prev_burn": 2.0e6},
                          "comps": {"peer_ev_oz": 2.078}},
                "GROY": {"financials": {"sloan_cfo": 0.01, "sloan_bs": 0.01, "ebitda": 4.0e7,
                                        "shares_t0": 1.5e8, "shares_t1": 1.5e8}},
                "GMX.TO": {"financials": {"net_debt": 5.0e7, "ebitda": 8.0e7,
                                          "shares_t0": 1.2e8, "shares_t1": 1.21e8}},
            },
        }
        # The router is CONFIG-DRIVEN, so the ticker list must be too: naming holdings here is
        # what broke this test twice (URC.TO removed 2026-07-31, then GMX.TO exited 2026-08-13 —
        # each departure turning a valid list into a TickerNotRegisteredError).
        # route exactly the names that are BOTH registered (config-driven) and fixtured above —
        # a departed holding then simply drops out instead of raising.
        names = sorted(set(self.router.registered_tickers()) & set(merged["tickers"]))
        self.assertTrue(names, "no fixtured ticker is registered on the router")
        built = self.mapper.build_all(names, merged)
        for ticker, payload in built["tickers"].items():
            summary = self.router.get_valuation(ticker, payload, self.neutral)
            blended = summary["blended_intrinsic"]
            self.assertTrue(isinstance(blended, (int, float)) and math.isfinite(blended), ticker)
            self.assertGreaterEqual(blended, 0.0, ticker)
            self.assertAlmostEqual(sum(summary["weights"].values()), 1.0, places=5, msg=ticker)
            self.assertEqual(summary["base_currency"], "CAD", ticker)
            json.dumps(summary)                           # fully serializable


class TestCatalystAdapter(unittest.TestCase):
    """Phase 8: the catalyst_manual adapter + feed writer/refresh."""

    def _csv(self, body):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
        fh.write(body); fh.close()
        return fh.name

    def test_adapter_reads_csv_events(self):
        path = self._csv(
            "ticker,date,type,headline,impact,magnitude,share_change_pct\n"
            "AGA.V,2026-05-26,drill_result,big hit,0.85,0.9,\n"
            "GMX.TO,2026-04-29,financing,raise,-0.45,0.7,0.14\n"
            "ZZZ,2026-01-01,news,ignored,0.1,0.1,\n")
        try:
            ad = ip.CatalystManualAdapter(path=path)
            self.assertTrue(ad.is_available())
            frag = ad.fetch(["AGA.V", "GMX.TO"])["fragments"][ip.CAP_CATALYSTS]
            evs = frag["events"]
            self.assertEqual({e["ticker"] for e in evs}, {"AGA.V", "GMX.TO"})  # ZZZ filtered out
            fin = next(e for e in evs if e["type"] == "financing")
            self.assertEqual(fin["share_change_pct"], 0.14)                    # numeric coercion
            self.assertEqual(fin["headline"], "raise")
        finally:
            os.unlink(path)

    def test_adapter_missing_file_is_graceful(self):
        ad = ip.CatalystManualAdapter(path="nope/missing.csv")
        self.assertFalse(ad.is_available())
        self.assertEqual(ad.fetch(["AGA.V"])["fragments"], {})

    def test_write_and_load_feed_roundtrip(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "catalysts.json")
        ip.write_catalyst_feed([{"ticker": "AGA.V", "type": "drill_result", "impact": 0.8}], path=path)
        with open(path) as fh:
            env = json.load(fh)
        self.assertEqual(env["schema_version"], ip.SCHEMA_VERSION)
        self.assertEqual(len(env["events"]), 1)

    def test_refresh_noop_when_no_provider_events(self):
        # No CSV present -> refresh is a graceful no-op (does not wipe an existing feed).
        res = ip.refresh_catalyst_feed(
            {"catalysts": {"providers": [{"name": "catalyst_manual", "enabled": True,
                                          "params": {"path": "nope/missing.csv"}}],
                           "feed_path": "nope/out.json"}},
            tickers=["AGA.V"])
        self.assertEqual(res["status"], "noop")

    def test_refresh_writes_from_csv(self):
        d = tempfile.mkdtemp()
        csv_path = os.path.join(d, "cat.csv")
        out = os.path.join(d, "feed.json")
        with open(csv_path, "w", newline="") as fh:
            fh.write("ticker,date,type,headline,impact\nAGA.V,2026-05-26,drill_result,hit,0.8\n")
        res = ip.refresh_catalyst_feed(
            {"catalysts": {"providers": [{"name": "catalyst_manual", "enabled": True,
                                          "params": {"path": csv_path}}], "feed_path": out}},
            tickers=["AGA.V"])
        self.assertEqual(res["status"], "written")
        self.assertEqual(res["count"], 1)
        self.assertTrue(os.path.exists(out))


class TestCatalystSources(unittest.TestCase):
    """Phase 8 follow-up: RSS/news + filings adapters and the primary/fallback aggregation."""

    RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Silver47 drills 1,240 g/t AgEq over 4.2m at Red Mountain</title>
        <link>http://ex/1</link><pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate>
        <description>High-grade silver intercept.</description></item>
      <item><title>Macro: gold ticks higher on CPI</title><link>http://ex/2</link>
        <pubDate>Mon, 25 May 2026 09:00:00 GMT</pubDate></item>
    </channel></rss>"""

    def test_stdlib_feed_parse(self):
        entries = ip._parse_feed_entries(self.RSS)
        self.assertEqual(len(entries), 2)
        self.assertIn("Red Mountain", entries[0]["title"])
        self.assertEqual(entries[0]["link"], "http://ex/1")

    def test_feed_parse_sanitizes_markup(self):
        rss = ('<?xml version="1.0"?><rss version="2.0"><channel><item>'
               '<title>Drills 900 g/t Ag</title><link>http://ex/9</link>'
               '<pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate>'
               '<description>&lt;p&gt;High-grade&lt;/p&gt;&lt;script&gt;evil()&lt;/script&gt;</description>'
               '</item></channel></rss>')
        e = ip._parse_feed_entries(rss)[0]
        self.assertNotIn("evil", e["summary"])           # script stripped (bs4 / regex fallback)
        self.assertNotIn("<", e["summary"])

    def test_empty_or_garbage_feed_is_graceful(self):
        self.assertEqual(ip._parse_feed_entries(None), [])
        self.assertEqual(ip._parse_feed_entries("not xml at all"), [])

    def test_rss_adapter_classifies_and_matches(self):
        # No feed-level ticker hint -> a GENERIC aggregator. A2.5: such feeds are skipped by
        # default (issuer-scoped only); the attribution mechanics survive behind the explicit
        # opt-in, and even then the events are display-only at trust 0 — never a catalyst record.
        generic = ip.RssNewsAdapter(feeds=[{"url": "http://feed"}],
                                    aliases={"AGA.V": ["silver47", "red mountain"]}, trust=1)
        with mock.patch.object(ip, "_http_get_text", return_value=self.RSS):
            self.assertEqual(generic.fetch(["AGA.V"])["fragments"], {})   # skipped (A2.5 default)
        ad = ip.RssNewsAdapter(feeds=[{"url": "http://feed"}],
                               aliases={"AGA.V": ["silver47", "red mountain"]}, trust=1,
                               allow_generic_feeds=True)
        with mock.patch.object(ip, "_http_get_text", return_value=self.RSS):
            frag = ad.fetch(["AGA.V"])["fragments"]
        evs = frag[ip.CAP_CATALYSTS]["events"]
        self.assertEqual(len(evs), 1)                        # macro headline not matched to ticker
        self.assertEqual(evs[0]["ticker"], "AGA.V")
        self.assertIn(evs[0]["type"], ("drill_result", "grade_beat"))
        self.assertEqual(evs[0]["_trust"], 0)                # generic-attributed: demoted
        self.assertTrue(evs[0]["display_only"])              # ...and display-only (A2.5)
        self.assertEqual(evs[0]["date"], "2026-05-26")

    def test_rss_adapter_graceful_without_feeds(self):
        self.assertFalse(ip.RssNewsAdapter(feeds=[]).is_available())
        self.assertEqual(ip.RssNewsAdapter(feeds=[]).fetch(["AGA.V"])["fragments"], {})

    def test_edgar_skips_foreign_and_is_graceful_offline(self):
        ad = ip.EdgarFilingsAdapter()
        with mock.patch.object(ip, "_http_get_json", return_value=None):
            frag = ad.fetch(["AGA.V", "URC.TO"])["fragments"]    # .V/.TO skipped by CIK resolver
        self.assertEqual(frag, {})

    def test_sedar_stub_disabled_by_default(self):
        self.assertFalse(ip.SedarFilingsAdapter().is_available())
        self.assertEqual(ip.SedarFilingsAdapter().fetch(["AGA.V"])["fragments"], {})

    def test_refresh_precedence_filing_supersedes_rss(self):
        # Same financing month from RSS (trust 1) and a filing (trust 3) -> filing wins, deduped.
        rss = {"ticker": "GMX.TO", "type": "financing", "headline": "bought deal rumor",
               "date": "2026-04-29", "_source": "rss", "_trust": 1}
        filing = {"ticker": "GMX.TO", "type": "financing", "headline": "SEC 424B5: prospectus",
                  "date": "2026-04-15", "_source": "edgar", "_trust": 3}
        collapsed = ip._collapse_by_source_precedence([rss, filing])
        fins = [e for e in collapsed if e["type"] == "financing"]
        self.assertEqual(len(fins), 1)
        self.assertEqual(fins[0]["_trust"], 3)               # authoritative filing kept

    def test_rss_drops_weak_attribution(self):
        # A generic sector headline must NOT be attributed to a specific ticker.
        rss = ('<?xml version="1.0"?><rss version="2.0"><channel><item>'
               '<title>Silver prices rise on macro tailwinds</title><link>http://ex/g</link>'
               '<pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate></item></channel></rss>')
        ad = ip.RssNewsAdapter(feeds=[{"url": "u"}], aliases={"AGA.V": ["silver47", "red mountain"]},
                               min_relevance=0.5, allow_generic_feeds=True)
        with mock.patch.object(ip, "_http_get_text", return_value=rss):
            self.assertEqual(ad.fetch(["AGA.V"])["fragments"], {})   # unattributed -> nothing

    def test_rss_requires_a_title(self):
        rss = ('<?xml version="1.0"?><rss version="2.0"><channel><item>'
               '<title>   </title><link>http://ex/blank</link></item></channel></rss>')
        ad = ip.RssNewsAdapter(feeds=[{"url": "u", "ticker": "AGA.V"}])
        with mock.patch.object(ip, "_http_get_text", return_value=rss):
            self.assertEqual(ad.fetch(["AGA.V"])["fragments"], {})   # no clean title -> discard

    def test_rss_keeps_exact_title_for_strong_match(self):
        rss = ('<?xml version="1.0"?><rss version="2.0"><channel><item>'
               '<title>Silver47 drills 1,240 g/t AgEq at Red Mountain</title><link>http://ex/1</link>'
               '<pubDate>Tue, 26 May 2026 10:00:00 GMT</pubDate></item></channel></rss>')
        ad = ip.RssNewsAdapter(feeds=[{"url": "u"}], aliases={"AGA.V": ["silver47", "red mountain"]},
                               allow_generic_feeds=True)   # mechanics test: explicit A2.5 opt-in
        with mock.patch.object(ip, "_http_get_text", return_value=rss):
            evs = ad.fetch(["AGA.V"])["fragments"][ip.CAP_CATALYSTS]["events"]
        self.assertEqual(evs[0]["headline"], "Silver47 drills 1,240 g/t AgEq at Red Mountain")
        self.assertGreaterEqual(evs[0]["relevance"], 0.6)

    def test_edgar_uses_exact_desc_or_skips(self):
        subs = {"filings": {"recent": {
            "form": ["8-K", "8-K"], "filingDate": ["2026-05-20", "2026-05-10"],
            "primaryDocDescription": ["Material definitive agreement", ""]}}}  # 2nd has no desc
        ad = ip.EdgarFilingsAdapter()
        with mock.patch.object(ad._sec, "resolve_cik", return_value="1832433"), \
             mock.patch.object(ip, "_http_get_json", return_value=subs):
            evs = ad.fetch(["GROY"])["fragments"][ip.CAP_CATALYSTS]["events"]
        self.assertEqual(len(evs), 1)                                  # blank-desc filing discarded
        self.assertIn("Material definitive agreement", evs[0]["headline"])

    def test_attribution_override_reassign_and_drop(self):
        overrides = [("misfeed.com", "DROP"), ("silver47 corp", "AGA.V")]
        evs = [{"ticker": "WRONG", "headline": "Silver47 Corp drills", "link": "http://ok/1", "_source": "rss"},
               {"ticker": "AGA.V", "headline": "spam", "link": "http://misfeed.com/x", "_source": "rss"},
               {"ticker": "AGA.V", "headline": "analyst note", "_source": "manual"}]
        out = ip._apply_attribution_overrides(evs, overrides)
        self.assertEqual(len(out), 2)                                  # misfeed dropped
        self.assertEqual(out[0]["ticker"], "AGA.V")                    # reassigned by override
        self.assertEqual(out[1]["_source"], "manual")                 # analyst event untouched

    def test_override_loader_parses_csv(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "ov.csv")
        with open(p, "w", newline="") as fh:
            fh.write("pattern,ticker\n# comment line,IGNORED\naurora cannabis,DROP\nsilver47,AGA.V\n")
        ov = ip.load_attribution_overrides(p)
        self.assertIn(("aurora cannabis", "DROP"), ov)
        self.assertIn(("silver47", "AGA.V"), ov)
        self.assertTrue(all(not pat.startswith("#") for pat, _ in ov))

    def test_write_strips_internal_keys(self):
        d = tempfile.mkdtemp(); path = os.path.join(d, "f.json")
        ip.write_catalyst_feed([{"ticker": "AGA.V", "type": "news", "headline": "h",
                                 "_source": "rss", "_trust": 1, "impact": 0.1}], path=path)
        with open(path) as fh:
            ev = json.load(fh)["events"][0]
        self.assertNotIn("_source", ev)
        self.assertNotIn("_trust", ev)
        self.assertIn("impact", ev)


class TestManualOverrideIsEmptyByDefault(unittest.TestCase):
    """The manual catalyst CSV is now a TRUE OVERRIDE: heavily commented and empty by default. It
    must parse to zero rows (comment banner is not treated as a header) and never fabricate data."""

    def test_comment_only_csv_yields_no_events(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "catalysts.csv")
        with open(p, "w") as fh:
            fh.write("# banner line\n# another comment\n\n"
                     "ticker,date,type,headline,impact,magnitude,share_change_pct,stage_to,p_discovery_delta\n")
        ad = ip.CatalystManualAdapter(path=p)
        frag = ad.fetch(["AGA.V", "GROY"]).get("fragments", {})
        self.assertEqual(frag, {})                          # no events -> empty fragment

    def test_verified_row_still_parses_through_comments(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "catalysts.csv")
        with open(p, "w") as fh:
            fh.write("# documentation banner\n"
                     "ticker,date,type,headline,impact,magnitude,share_change_pct,stage_to,p_discovery_delta\n"
                     "AGA.V,2026-05-26,drill_result,Verified hit,0.6,0.7,,,0.05\n")
        ad = ip.CatalystManualAdapter(path=p)
        evs = ad.fetch(["AGA.V"])["fragments"][ip.CAP_CATALYSTS]["events"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["headline"], "Verified hit")


class TestLivePrimaryAttribution(unittest.TestCase):
    """Live RSS is primary; generic sector news must NOT attribute to a portfolio ticker, and a
    distinctive company name must. Exercised through the real adapter with a mocked transport."""

    SAMPLE = ('<?xml version="1.0"?><rss><channel>'
              '<item><title>Silver47 Exploration drills 1205 g/t AgEq at Red Mountain</title>'
              '<link>http://x/a</link><pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item>'
              '<item><title>Silver prices rally on Fed rate-cut bets</title>'
              '<link>http://x/b</link><pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate></item>'
              '</channel></rss>')

    def test_generic_news_unattributed_company_news_kept(self):
        adapter = ip.RssNewsAdapter(
            feeds=[{"url": "http://x/feed"}],
            aliases={"AGA.V": ["silver47", "red mountain"], "GROY": ["gold royalty corp"]},
            min_relevance=0.5, min_title_len=6, allow_generic_feeds=True)   # A2.5 opt-in
        with mock.patch.object(ip, "_http_get_text", lambda url, **kw: self.SAMPLE):
            frag = adapter.fetch(["AGA.V", "GROY"]).get("fragments", {}).get(ip.CAP_CATALYSTS, {})
        evs = frag.get("events", [])
        self.assertEqual(len(evs), 1)                       # generic "Silver prices rally" dropped
        self.assertEqual(evs[0]["ticker"], "AGA.V")
        self.assertIn("Silver47", evs[0]["headline"])       # verbatim source title


class TestEngineLiveFeedFlag(unittest.TestCase):
    """Phase 8 debug fix: the engine must actually drive the live pipeline behind
    ``catalysts.use_live_feeds`` (it previously only ever served a static file), and fall back
    to EMPTY when the flag is off so a stale checked-in feed is never shown as if it were live."""

    def setUp(self):
        import engine as E
        self.E = E
        # Bypass __init__ (no network/yfinance); we only exercise the catalyst-feed plumbing.
        self.eng = E.CommodityExMonitor.__new__(E.CommodityExMonitor)

    def _feed_file(self, events):
        d = tempfile.mkdtemp(); path = os.path.join(d, "feed.json")
        ip.write_catalyst_feed(events, path=path, source="seed")
        return path

    def test_disabled_flag_falls_back_to_empty(self):
        path = self._feed_file([{"ticker": "AGA.V", "type": "news", "headline": "x", "impact": 0.1}])
        cfg = {"catalysts": {"enabled": True, "use_live_feeds": False,
                             "serve_seed_when_disabled": False, "feed_path": path}}
        feed = self.eng._catalyst_feed(cfg)
        self.assertEqual(feed["status"], "live_disabled")
        self.assertEqual(feed["events"], [])               # explicit empty fallback, not the file

    def test_disabled_with_seed_escape_hatch_serves_file(self):
        path = self._feed_file([{"ticker": "AGA.V", "type": "news", "headline": "x", "impact": 0.1}])
        cfg = {"catalysts": {"enabled": True, "use_live_feeds": False,
                             "serve_seed_when_disabled": True, "feed_path": path}}
        feed = self.eng._catalyst_feed(cfg)
        self.assertEqual(len(feed["events"]), 1)            # offline-demo opt-in serves the seed

    def test_live_flag_invokes_refresh(self):
        path = self._feed_file([{"ticker": "AGA.V", "type": "news", "headline": "old", "impact": 0.1}])
        cfg = {"catalysts": {"enabled": True, "use_live_feeds": True,
                             "live_refresh_seconds": 0, "feed_path": path}}  # ttl 0 -> always refresh
        called = {}

        def fake_refresh(config, *, path=None):
            called["path"] = path
            ip.write_catalyst_feed([{"ticker": "AGA.V", "type": "drill_result",
                                     "headline": "live hit", "impact": 0.4}], path=path, source="live")
            return {"status": "written", "providers": ["catalyst_manual"], "count": 1}

        with mock.patch.object(self.E, "refresh_catalyst_feed", fake_refresh):
            feed = self.eng._catalyst_feed(cfg)
        self.assertEqual(called.get("path"), path)          # engine drove the live refresher
        self.assertEqual(feed["events"][0]["headline"], "live hit")

    def test_live_refresh_failure_serves_cached_feed(self):
        path = self._feed_file([{"ticker": "AGA.V", "type": "news", "headline": "cached", "impact": 0.1}])
        cfg = {"catalysts": {"enabled": True, "use_live_feeds": True,
                             "live_refresh_seconds": 0, "feed_path": path}}

        def boom(config, *, path=None):
            raise RuntimeError("network down")

        with mock.patch.object(self.E, "refresh_catalyst_feed", boom):
            feed = self.eng._catalyst_feed(cfg)             # must NOT raise
        self.assertEqual(feed["events"][0]["headline"], "cached")   # serves what's on disk


class TestHttpCacheResilience(unittest.TestCase):
    """A broken requests_cache layer (e.g. ``NameError: RequestsCookieJar`` from a requests/
    requests_cache version skew) must NOT kill every feed: the GET path drops the cache for the
    run and retries once uncached. A genuine network error must NOT trigger that fallback."""

    def setUp(self):
        self._saved = (ip._SESSION, ip._SESSION_IS_CACHED)

    def tearDown(self):
        ip._SESSION, ip._SESSION_IS_CACHED = self._saved

    def test_cache_layer_error_falls_back_and_succeeds(self):
        class BrokenCached:
            def get(self, *a, **k):
                raise NameError("name 'RequestsCookieJar' is not defined")

        class Plain:
            def __init__(self):
                self.calls = []

            def get(self, url, **k):
                self.calls.append(url)
                return SimpleNamespace(status_code=200, text="<rss/>", json=lambda: {"k": 1})

        plain = Plain()

        def _heal():
            ip._SESSION, ip._SESSION_IS_CACHED = plain, False
            return plain

        with mock.patch.object(ip, "_fallback_uncached_session", _heal):
            ip._SESSION, ip._SESSION_IS_CACHED = BrokenCached(), True
            self.assertEqual(ip._http_get_text("https://feed/rss"), "<rss/>")
            ip._SESSION, ip._SESSION_IS_CACHED = BrokenCached(), True   # reset for the JSON path
            self.assertEqual(ip._http_get_json("https://feed/json"), {"k": 1})

        self.assertIn("https://feed/rss", plain.calls)

    def test_network_error_is_not_treated_as_cache_failure(self):
        if ip.requests is None:
            self.skipTest("requests not installed")

        class CachedNetFail:
            def get(self, *a, **k):
                raise ip.requests.exceptions.ConnectTimeout("down")

        ip._SESSION, ip._SESSION_IS_CACHED = CachedNetFail(), True
        with mock.patch.object(ip, "_fallback_uncached_session") as healed:
            self.assertIsNone(ip._http_get_text("https://feed/rss"))   # logged + None, as before
            healed.assert_not_called()                                  # cache NOT dropped on a network error


if __name__ == "__main__":
    unittest.main(verbosity=2)
