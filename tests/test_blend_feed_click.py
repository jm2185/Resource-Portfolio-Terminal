"""Quest-Log (Agent Hub) click resolution — the feed is rebuilt + re-sorted newest-first on a 1s
timer, so resolving a click by positional INDEX bound at render time lands on the wrong (drifting
toward most-recent) row. Clicks must resolve by the STABLE uid; keyboard nav (a live _sel index read
in-tick) still resolves positionally."""
import unittest

import commodityex_tui as t
from rich.text import Text


def _click_metas(parts):
    out = []
    for p in parts:
        if isinstance(p, Text):
            for span in p.spans:
                m = getattr(span.style, "meta", None)
                if m and "@click" in m:
                    out.append(m["@click"])
    return out


class _StubScreen:
    def __init__(self, items):
        self._items = items


ITEMS = [
    {"uid": "thread:aaa", "title": "oldest thread", "kind": "ask", "opens": "thread", "ts": 100},
    {"uid": "mem:bbb", "title": "a note", "kind": "note", "opens": "detail", "ts": 200},
    {"uid": "done:ccc", "title": "a dossier", "kind": "dossier", "opens": "detail", "ts": 300},
]


class BlendClickResolutionTests(unittest.TestCase):
    def test_row_click_carries_uid_not_index(self):
        metas = _click_metas(t._blend_feed_row(ITEMS[0], 0, -1, set()))
        self.assertTrue(any("blend_open('thread:aaa')" in m for m in metas), metas)
        self.assertTrue(any("blend_expand('thread:aaa')" in m for m in metas), metas)

    def test_resolves_by_uid_after_the_feed_reorders(self):
        # the bug: user clicks the oldest row (uid thread:aaa, index 0); before the click dispatches the
        # 1s timer rebuilds the feed newest-first and prepends two new items, so thread:aaa is now at
        # index 2 — a positional resolve would open one of the NEW rows ("most recent no matter what").
        scr = _StubScreen([{"uid": "run:new1", "ts": 999}, {"uid": "mem:new2", "ts": 998}] + list(ITEMS))
        it = t.Cockpit._blend_item_by_ref(None, scr, "thread:aaa")
        self.assertIsNotNone(it)
        self.assertEqual(it["uid"], "thread:aaa")            # the clicked row, NOT the newest

    def test_keyboard_index_still_resolves_positionally(self):
        it = t.Cockpit._blend_item_by_ref(None, _StubScreen(list(ITEMS)), 1)
        self.assertEqual(it["uid"], "mem:bbb")

    def test_unknown_uid_returns_none(self):
        self.assertIsNone(t.Cockpit._blend_item_by_ref(None, _StubScreen(list(ITEMS)), "mem:gone"))

    def test_out_of_range_index_returns_none(self):
        self.assertIsNone(t.Cockpit._blend_item_by_ref(None, _StubScreen(list(ITEMS)), 99))

    def test_empty_feed_is_graceful(self):
        self.assertIsNone(t.Cockpit._blend_item_by_ref(None, _StubScreen([]), "thread:aaa"))


if __name__ == "__main__":
    unittest.main()
