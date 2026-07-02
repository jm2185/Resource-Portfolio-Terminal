"""Tests for task_supervision.py — the supervised-worker spine (crash recorded, unexpected return
counts as death, cancellation is a clean stop, on_death can't mask the record). Also carries the
adjacent audit-debt-closeout gates from the same round: A2.2 (set_param hard-gated to the proposal
queue) and A2.5 (RSS issuer-scoping)."""
from __future__ import annotations

import asyncio
import sys
import unittest
from unittest import mock

import task_supervision as ts


class TaskSupervisionTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

    def test_crash_is_recorded_and_on_death_fires(self):
        async def main():
            health, deaths = {}, []

            async def bad_worker():
                raise RuntimeError("boom")

            t = ts.create_supervised("prices", bad_worker(), health=health,
                                     on_death=lambda n, e: deaths.append((n, e)))
            await asyncio.wait([t])
            return health, deaths
        health, deaths = self._run(main())
        self.assertFalse(health["prices"]["alive"])
        self.assertIn("RuntimeError: boom", health["prices"]["error"])
        self.assertEqual(deaths[0][0], "prices")
        self.assertEqual(ts.dead_workers(health), ["prices"])

    def test_unexpected_return_counts_as_death(self):
        async def main():
            health = {}

            async def returns_quietly():            # worker loops must never return
                return 42

            await asyncio.wait([ts.create_supervised("macro", returns_quietly(), health=health)])
            return health
        health = self._run(main())
        self.assertFalse(health["macro"]["alive"])
        self.assertIn("never return", health["macro"]["error"])

    def test_cancellation_is_a_stop_not_a_death(self):
        async def main():
            health = {}

            async def forever():
                while True:
                    await asyncio.sleep(3600)

            t = ts.create_supervised("comps", forever(), health=health)
            await asyncio.sleep(0)
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)
            return health
        health = self._run(main())
        self.assertFalse(health["comps"]["alive"])
        self.assertEqual(health["comps"]["stopped"], "cancelled")
        self.assertEqual(ts.dead_workers(health), [])   # a clean stop is not a death

    def test_on_death_exception_cannot_mask_the_record(self):
        async def main():
            health = {}

            async def bad():
                raise ValueError("x")

            def explosive(_n, _e):
                raise RuntimeError("handler bug")

            await asyncio.wait([ts.create_supervised("cftc", bad(), health=health,
                                                     on_death=explosive)])
            return health
        health = self._run(main())
        self.assertIn("ValueError", health["cftc"]["error"])


class SetParamHardGateTests(unittest.TestCase):
    """A2.2 — the MCP channel is the agent channel: set_param can never write directly, even
    with confirm=true; it files a proposal for the operator's /confirm."""

    def setUp(self):
        sys.path.insert(0, "mcp_server")
        import core
        self.core = core

    def test_always_routes_to_the_proposal_queue(self):
        calls = []

        def fake_post(path, body, **kw):
            calls.append((path, body))
            return {"ok": True, "id": 7}

        with mock.patch.object(self.core, "_http_post_json", side_effect=fake_post):
            res = self.core.set_param("conservatism_scalar", 0.9, confirm=True)
        self.assertEqual(res["status"], "proposed")
        self.assertEqual(calls[0][0], "/config/propose")        # NEVER /config/param
        self.assertEqual(calls[0][1]["proposed_by"], "mcp:set_param")
        self.assertIn("/confirm", res["message"])

    def test_unconfirmed_also_proposes(self):
        with mock.patch.object(self.core, "_http_post_json",
                               return_value={"ok": True, "id": 8}) as p:
            res = self.core.set_param("rho_half", 2.2, confirm=False)
        self.assertEqual(res["status"], "proposed")
        self.assertEqual(p.call_args[0][0], "/config/propose")


_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Silver47 intersects 1,200 g/t AgEq over 12m at Red Mountain</title>
<link>https://example.com/pr/1</link><pubDate>Tue, 09 Jun 2026 12:00:00 GMT</pubDate>
<description>drill results</description></item>
</channel></rss>"""


class RssIssuerScopingTests(unittest.TestCase):
    """A2.5 — issuer-scoped PR wires only; generic aggregators skipped (default) or
    display-only at trust 0 (explicit opt-in). Never a catalyst record that supersedes."""

    def _adapter(self, ip, feeds, **kw):
        return ip.RssNewsAdapter(feeds=feeds, aliases={"silver47": "AGA.V"}, trust=2, **kw)

    def test_generic_feed_skipped_by_default(self):
        import ingestion_pipeline as ip
        if ip.classify_headline is None:
            self.skipTest("classifier unavailable in this env")
        with mock.patch.object(ip, "_http_get_text", return_value=_RSS):
            hinted = self._adapter(ip, [{"url": "https://wire/co", "ticker": "AGA.V"}]).fetch(["AGA.V"])
            generic = self._adapter(ip, ["https://news/all-mining"]).fetch(["AGA.V"])
        h_events = hinted["fragments"]["catalysts"]["events"]
        self.assertEqual(len(h_events), 1)                       # issuer wire: a catalyst record
        self.assertEqual(h_events[0]["_trust"], 2)
        self.assertEqual(generic["fragments"], {})               # aggregator: skipped entirely

    def test_generic_opt_in_is_display_only_trust_zero(self):
        import ingestion_pipeline as ip
        if ip.classify_headline is None:
            self.skipTest("classifier unavailable in this env")
        with mock.patch.object(ip, "_http_get_text", return_value=_RSS):
            res = self._adapter(ip, ["https://news/all-mining"],
                                allow_generic_feeds=True).fetch(["AGA.V"])
        evs = (res["fragments"].get("catalysts") or {}).get("events") or []
        if evs:                                                  # only if the alias attributed it
            self.assertTrue(all(e.get("display_only") for e in evs))
            self.assertTrue(all(e.get("_trust") == 0 for e in evs))


if __name__ == "__main__":
    unittest.main()
