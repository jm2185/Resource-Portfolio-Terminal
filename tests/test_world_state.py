"""
Tests for the world-state snapshot (world_state.py) — the shared situational frame every agent
inherits. Pins: regime+posture+focus+book+actions+memory assemble; operator actions read as "you";
the brief is compact text; everything degrades gracefully to nulls.
"""
import unittest

import world_state as ws


def _state():
    return {
        "mri": 39.1,
        "posture": {"code": "spear_exploit", "label": "SPEAR EXPLOIT", "cap": 0.75, "headwind": True},
        "macro_tape": {"net_tilt": "risk_on"},
        "conviction_mode": {"baskets": [
            {"ticker": "AGA.V", "rating": 9.0, "band": "PRIME", "directive": "BELOW FLOOR — ACCUMULATE"},
            {"ticker": "GROY", "rating": 6.9, "band": "SOLID", "directive": "FAIR VALUE — HOLD"},
        ]},
        "agent_activity": [
            {"agent": "claude", "kind": "ran", "summary": "python -m unittest test_council", "ticker": None},
            {"agent": "claude", "kind": "git", "summary": "git commit -m fix", "ticker": None},
            {"agent": "scout", "kind": "tool", "summary": "scout silver", "ticker": None},
        ],
        "pipeline": {"status": "running", "theme": "silver", "stage": "verifier"},
    }


class BuildTests(unittest.TestCase):
    def test_assembles_the_full_frame(self):
        w = ws.build(_state(), focus="AGA.V",
                     recent_memory=[{"type": "council_verdict", "ticker": "AGA.V", "text": "RE-AFFIRM"}])
        self.assertEqual(w["regime"]["mri"], 39.1)
        self.assertEqual(w["regime"]["posture"], "SPEAR EXPLOIT")
        self.assertEqual(w["focus"], "AGA.V")
        self.assertEqual(len(w["book"]), 2)
        self.assertEqual(w["recent_memory"][0]["text"], "RE-AFFIRM")
        self.assertEqual(w["pipeline"]["stage"], "verifier")

    def test_operator_actions_read_as_you(self):
        w = ws.build(_state())
        op = [a for a in w["recent_actions"] if a["who"] == "you"]
        self.assertTrue(any(a["kind"] == "ran" for a in op))
        self.assertTrue(any(a["kind"] == "git" for a in op))
        # the headless scout is NOT "you"
        self.assertTrue(any(a["who"] == "scout" for a in w["recent_actions"]))

    def test_idle_pipeline_is_omitted(self):
        s = _state(); s["pipeline"] = {"status": "idle"}
        self.assertIsNone(ws.build(s)["pipeline"])

    def test_graceful_on_empty(self):
        w = ws.build({})
        self.assertIsNone(w["regime"]["mri"])
        self.assertEqual(w["book"], [])
        self.assertEqual(w["recent_actions"], [])


class BriefTests(unittest.TestCase):
    def test_brief_is_compact_and_grounded(self):
        brief = ws.render_brief(ws.build(_state(), focus="AGA.V"))
        self.assertIn("DESK STATE", brief)
        self.assertIn("SPEAR EXPLOIT", brief)
        self.assertIn("0.75x", brief)
        self.assertIn("AGA.V", brief)
        self.assertIn("you", brief)              # operator actions surfaced
        self.assertLess(len(brief), 1200)        # compact enough to prepend to every prompt

    def test_brief_graceful_on_empty(self):
        brief = ws.render_brief(ws.build({}))
        self.assertIn("DESK STATE", brief)       # never crashes on a cold engine


if __name__ == "__main__":
    unittest.main(verbosity=2)
