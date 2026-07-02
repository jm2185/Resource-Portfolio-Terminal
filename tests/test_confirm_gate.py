"""The human-in-the-loop gate on APPLYING a config mutation — both the direct-write endpoint
(/config/param, audit A2.2) and the CONFIRM endpoint (/config/confirm, 2026-07-02 reassessment
finding #1). Confirming a pending change applies a mutation, so it must be as human-gated as a
direct write. This pins that the shared source guard refuses agent sources and admits the
cockpit/human channel, so an agent can neither self-write nor self-confirm a tunable.
"""
import unittest

from engine import _write_source_ok


class WriteSourceGate(unittest.TestCase):
    def test_cockpit_channel_admitted(self):
        # the cockpit UI (_do_confirm) and the direct-write route both present as "cockpit"
        self.assertTrue(_write_source_ok("cockpit"))

    def test_human_channel_admitted(self):
        self.assertTrue(_write_source_ok("human"))
        self.assertTrue(_write_source_ok("human:operator"))

    def test_agent_sources_refused(self):
        # every agent/MCP channel must route through /config/propose -> the operator's /confirm
        for src in ("agent", "mcp", "mcp:set_param", "mcp:confirm_param_change",
                    "engine-flywheel", "scout", ""):
            self.assertFalse(_write_source_ok(src), f"{src!r} must be refused")

    def test_none_refused(self):
        # a missing source is not the cockpit — fail closed
        self.assertFalse(_write_source_ok(None))


if __name__ == "__main__":
    unittest.main()
