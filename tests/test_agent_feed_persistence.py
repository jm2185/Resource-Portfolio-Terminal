"""Tests for the durable QUEST-LOG feed (agent_activity persistence across restart)."""
import json
import os
import tempfile
import unittest

import engine


class _Stub(engine.CommodityExMonitor):
    """A monitor with only the attributes the agent-feed methods touch — skips the heavy __init__
    (engines / network) so we test persistence in isolation, with the REAL methods bound."""
    def __init__(self):
        self.terminal_state = {"agent_activity": [], "agent_reply": None}
        self._agent_seq = 0

    def publish_state(self):
        pass


class AgentFeedPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = engine.AGENT_ACTIVITY_PATH
        engine.AGENT_ACTIVITY_PATH = os.path.join(self.tmp, "agent_activity.jsonl")

    def tearDown(self):
        engine.AGENT_ACTIVITY_PATH = self._orig

    def _lines(self):
        with open(engine.AGENT_ACTIVITY_PATH, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def test_records_persist_to_disk(self):
        s = _Stub()
        s.record_agent_activity({"agent": "scout", "kind": "prompt", "summary": "scout silver"})
        s.record_agent_activity({"agent": "scout", "kind": "response", "summary": "found 4", "text": "full reply"})
        rows = self._lines()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["text"], "full reply")      # reply text persisted
        self.assertEqual(rows[0]["agent"], "scout")

    def test_reload_restores_feed_reply_and_seq(self):
        s = _Stub()
        for i in range(3):
            s.record_agent_activity({"agent": "a", "kind": "note", "summary": f"n{i}"})
        s.record_agent_activity({"agent": "a", "kind": "response", "summary": "done", "text": "the reply"})
        last_seq = s._agent_seq

        s2 = _Stub()                                          # simulate a restart
        s2._reload_agent_feed()
        self.assertEqual(len(s2.terminal_state["agent_activity"]), 4)
        self.assertEqual(s2.terminal_state["agent_reply"]["text"], "the reply")
        self.assertEqual(s2._agent_seq, last_seq)             # seq counter continues
        r = s2.record_agent_activity({"agent": "a", "kind": "note", "summary": "after restart"})
        self.assertEqual(r["seq"], last_seq + 1)              # no seq collision

    def test_live_buffer_bounded_disk_keeps_full(self):
        s = _Stub()
        n = engine.AGENT_ACTIVITY_BUFFER + 12
        for i in range(n):
            s.record_agent_activity({"agent": "a", "kind": "note", "summary": f"n{i}"})
        self.assertEqual(len(s.terminal_state["agent_activity"]), engine.AGENT_ACTIVITY_BUFFER)
        self.assertEqual(len(self._lines()), n)               # disk keeps all (under the KEEP cap)

    def test_reload_buffer_is_recent_tail(self):
        s = _Stub()
        n = engine.AGENT_ACTIVITY_BUFFER + 12
        for i in range(n):
            s.record_agent_activity({"agent": "a", "kind": "note", "summary": f"n{i}"})
        s2 = _Stub()
        s2._reload_agent_feed()
        buf = s2.terminal_state["agent_activity"]
        self.assertEqual(len(buf), engine.AGENT_ACTIVITY_BUFFER)
        self.assertEqual(buf[-1]["summary"], f"n{n - 1}")     # the most recent survived

    def test_missing_file_is_graceful(self):
        s = _Stub()
        s._reload_agent_feed()                                # no file yet -> no-op, no raise
        self.assertEqual(s.terminal_state["agent_activity"], [])

    def test_corrupt_lines_skipped(self):
        os.makedirs(os.path.dirname(engine.AGENT_ACTIVITY_PATH), exist_ok=True)
        with open(engine.AGENT_ACTIVITY_PATH, "w", encoding="utf-8") as fh:
            fh.write('{"seq": 1, "agent": "a", "summary": "ok"}\n')
            fh.write("not json at all\n")
            fh.write('{"seq": 2, "agent": "a", "summary": "ok2"}\n')
        s = _Stub()
        s._reload_agent_feed()
        self.assertEqual(len(s.terminal_state["agent_activity"]), 2)   # bad line skipped, not fatal
        self.assertEqual(s._agent_seq, 2)


if __name__ == "__main__":
    unittest.main()
