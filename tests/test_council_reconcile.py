"""The council_reconcile MCP wrapper — the fix for the 2026-07-02 reassessment finding that the
deterministic reconciler (council.reconcile) had no runtime surface, so the Arbiter (which denies
Bash) could only apply the signal-coherence rules by feel. This pins that the wrapper: pulls live
facts, reconciles through the module, is READ-ONLY (writes nothing), and fails closed on bad input
or an offline engine. The reconcile MATH itself is pinned by tests/test_council*.py.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "mcp_server"))
import core  # noqa: E402


def _book():
    """A single convex spear with a clean gate — the shape get_conviction_ratings projects."""
    return {"engine_running": True, "baskets": [{
        "ticker": "AGA.V", "archetype": "option_convexity",
        "directive": "BELOW FLOOR — ACCUMULATE",
        "ladder": {"price": 1.00, "floor": 0.80, "bear": 0.95, "base": 1.50, "bull": 2.50},
        "asymmetry": {"rho": 3.0, "floor_coverage": 1.2}, "gate": {"cap": 7}}]}


class CouncilReconcileWrapper(unittest.TestCase):
    def setUp(self):
        self._orig_gcr = core.get_conviction_ratings
        self._orig_http = core._http_get_json
        core.get_conviction_ratings = lambda with_calibration=True: _book()
        # posture fetch must never crash the read-only tool
        core._http_get_json = mock.Mock(return_value={"posture": {"code": "balanced", "cap": 1.0}})

    def tearDown(self):
        core.get_conviction_ratings = self._orig_gcr
        core._http_get_json = self._orig_http

    def test_reconciles_live_facts_into_a_verdict(self):
        res = core.council_reconcile(
            "AGA.V",
            bull_claims_json='[{"side":"bull","text":"ρ 3.0 over a hard floor","grounded":true,"field":"rho"}]',
            bear_claims_json='[{"side":"bear","text":"dilution risk","grounded":false}]',
        )
        self.assertTrue(res["ok"], res)
        v = res["verdict"]
        self.assertEqual(v["ticker"], "AGA.V")
        self.assertIn("stance", v)
        self.assertIn("convergence", v)
        self.assertEqual(v["engine_directive"], "BELOW FLOOR — ACCUMULATE")

    def test_is_read_only(self):
        res = core.council_reconcile("AGA.V", "[]", "[]")
        self.assertTrue(res["ok"])
        self.assertFalse(res["persisted"])  # writes NOTHING; the Arbiter persists explicitly

    def test_lowercase_ticker_resolves(self):
        res = core.council_reconcile("aga.v", "[]", "[]")
        self.assertTrue(res["ok"], res)

    def test_bad_json_fails_closed(self):
        res = core.council_reconcile("AGA.V", bull_claims_json="{not json")
        self.assertFalse(res["ok"])
        self.assertIn("bull_claims_json", res["error"])

    def test_unknown_ticker_refused(self):
        res = core.council_reconcile("ZZZ.V", "[]", "[]")
        self.assertFalse(res["ok"])
        self.assertIn("not in the live rated book", res["error"])

    def test_engine_offline_fails_closed(self):
        core.get_conviction_ratings = lambda with_calibration=True: {"engine_running": False}
        res = core.council_reconcile("AGA.V", "[]", "[]")
        self.assertFalse(res["ok"])
        self.assertFalse(res["engine_running"])


if __name__ == "__main__":
    unittest.main()
