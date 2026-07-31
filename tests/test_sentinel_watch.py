"""
Tests for the SENTINEL watch registry (sentinel_watch.py).

Pins the three disciplines the module exists to enforce:
  * grounded-or-silent — an ACTIVE watch with no source is rejected at validation (a
    pending_approval one is not: naming the source it WOULD use is what's being approved);
  * coverage is explicit — a pending item is never counted as watched, and ``board()`` names it;
  * the cadence clock — ``due()`` nags about clocked items that have fallen behind, and NEVER about
    event-driven ones (they have no clock) or non-active ones (nothing is watching them).
"""
import json
import os
import tempfile
import unittest

import sentinel_watch as sw

NOW = "2026-07-31T00:00:00Z"


def _item(**kw):
    base = dict(watch_id="x.one", subject="CEG", label="A watch", source="EDGAR",
                added="2026-07-01", last_review="2026-07-01")
    base.update(kw)
    return sw.new_watch(**base)


class ValidationTests(unittest.TestCase):
    def test_active_watch_requires_a_source(self):
        ok, errors = sw.validate(_item(source=""))
        self.assertFalse(ok)
        self.assertTrue(any("source" in e for e in errors), errors)

    def test_pending_approval_may_have_no_source(self):
        # the whole point of the pending tier: hold an honest proposal without pretending it's wired
        ok, errors = sw.validate(_item(source="", status="pending_approval"))
        self.assertTrue(ok, errors)

    def test_bad_status_cadence_and_subject_kind_are_rejected(self):
        ok, errors = sw.validate(_item(status="watching", cadence="hourly", subject_kind="sector"))
        self.assertFalse(ok)
        self.assertEqual(3, len(errors), errors)

    def test_lands_as_must_be_a_real_calendar_kind(self):
        ok, errors = sw.validate(_item(lands_as="not_a_kind"))
        self.assertFalse(ok)
        self.assertTrue(any("lands_as" in e for e in errors), errors)
        # and the conventional-lane kinds the handoff needs DO resolve
        for kind in ("earnings", "regulatory", "contract_award", "equity_offering", "supply_data"):
            ok, errors = sw.validate(_item(lands_as=kind))
            self.assertTrue(ok, f"{kind}: {errors}")

    def test_duplicate_ids_are_rejected_at_registry_level(self):
        ok, errors = sw.validate_registry([_item(), _item()])
        self.assertFalse(ok)
        self.assertTrue(any("duplicate" in e for e in errors), errors)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.tmp, self.tmp + ".tmp"):
            if os.path.exists(p):
                os.remove(p)

    def test_missing_and_corrupt_files_degrade_to_empty_never_raise(self):
        self.assertEqual([], sw.load(self.tmp))
        with open(self.tmp, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual([], sw.load(self.tmp))

    def test_save_roundtrip_and_invalid_never_reaches_disk(self):
        sw.save([_item()], self.tmp)
        self.assertEqual(1, len(sw.load(self.tmp)))
        with self.assertRaises(ValueError):
            sw.save([_item(source="")], self.tmp)          # active, unsourced
        self.assertEqual(1, len(sw.load(self.tmp)))         # prior good file untouched

    def test_upsert_replaces_by_id_rather_than_duplicating(self):
        items = [_item()]
        items, added = sw.upsert(items, _item(label="renamed"))
        self.assertFalse(added)
        self.assertEqual(1, len(items))
        self.assertEqual("renamed", items[0]["label"])
        items, added = sw.upsert(items, _item(watch_id="x.two"))
        self.assertTrue(added)
        self.assertEqual(2, len(items))


class DueTests(unittest.TestCase):
    def test_event_cadence_never_falls_due(self):
        items = [_item(cadence="event", last_review="2020-01-01")]
        self.assertEqual([], sw.due(items, now=NOW))

    def test_clocked_item_past_its_interval_is_due_with_overdue_days(self):
        items = [_item(cadence="weekly", last_review="2026-07-01")]
        hits = sw.due(items, now=NOW)
        self.assertEqual(1, len(hits))
        self.assertEqual(23, hits[0]["overdue_days"])       # 2026-07-08 due -> 2026-07-31

    def test_fresh_clocked_item_is_not_due(self):
        self.assertEqual([], sw.due([_item(cadence="monthly", last_review="2026-07-30")], now=NOW))

    def test_never_reviewed_active_item_is_due(self):
        hits = sw.due([_item(cadence="monthly", last_review="", added="")], now=NOW)
        self.assertEqual(1, len(hits))
        self.assertIsNone(hits[0]["overdue_days"])

    def test_pending_and_retired_items_never_fall_due(self):
        for st in ("pending_approval", "retired"):
            items = [_item(cadence="daily", last_review="2020-01-01", status=st, source="")]
            self.assertEqual([], sw.due(items, now=NOW), st)


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            _item(watch_id="a", subject="CEG", cadence="event"),
            _item(watch_id="b", subject="CEG", cadence="weekly", last_review="2026-07-01"),
            _item(watch_id="c", subject="memory-complex", subject_kind="theme",
                  status="pending_approval", source=""),
            _item(watch_id="d", subject="memory-complex", subject_kind="theme",
                  status="pending_approval", source=""),
        ]

    def test_pending_items_are_named_and_not_counted_as_watched(self):
        cov = sw.board(self.items, now=NOW)["coverage"]
        self.assertEqual(2, cov["active"])
        self.assertEqual(2, cov["pending_approval"])
        self.assertEqual(0.5, cov["pct_watched"])
        self.assertEqual({"c", "d"}, {p["id"] for p in cov["pending"]})

    def test_board_groups_by_subject_and_surfaces_due(self):
        bd = sw.board(self.items, now=NOW)
        self.assertEqual({"CEG", "memory-complex"}, set(bd["by_subject"]))
        self.assertEqual(["b"], [d["id"] for d in bd["due"]])

    def test_subject_filter_narrows_the_board(self):
        bd = sw.board(self.items, now=NOW, subject="ceg")   # case-insensitive
        self.assertEqual(2, bd["total"])

    def test_hand_edited_unsourced_active_item_is_surfaced_not_hidden(self):
        # validation blocks this on write, but a hand-edited file could still carry it — the board
        # must show the gap rather than count it as coverage.
        rogue = dict(_item(watch_id="e"))
        rogue["source"] = ""
        cov = sw.board(self.items + [rogue], now=NOW)["coverage"]
        self.assertEqual(["e"], cov["unsourced_active"])

    def test_summary_line_reports_pending_and_due(self):
        line = sw.summary_line(sw.board(self.items, now=NOW))
        self.assertIn("2 active", line)
        self.assertIn("2 pending approval", line)
        self.assertIn("1 due", line)


if __name__ == "__main__":
    unittest.main()
