"""
Tests for the catalyst lifecycle unification (catalyst_lifecycle.py, Forge Phase 1).

Pins the keystone guarantees as executable contracts:
  * reconcile() drives the calendar lifecycle from realized overlay events — a printed event
    transitions the pending window it resolves to `hit` and stamps the realized outcome on it;
  * matching is by ticker + kind-FAMILY + realized-date-in-window (± grace), exact kind preferred;
  * a past-due unmatched window expires to `missed` (no window lingers pending forever);
  * reconcile is idempotent (re-running the same feed is a no-op);
  * unified_view() returns each catalyst as ONE object across its life, incl. unplanned hits;
  * link_thesis() binds a catalyst to the thesis it underwrites (the calibration join).
"""
import os
import tempfile
import unittest

import catalyst_calendar as cc
import catalyst_lifecycle as cl


NOW = "2026-06-10T00:00:00Z"   # a fixed Wednesday so windows are deterministic


def _ev(ticker, etype, date, headline, **kw):
    e = {"ticker": ticker, "type": etype, "date": date, "headline": headline}
    e.update(kw)
    return e


class LifecycleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        self.cal = cc.CatalystCalendar(path=self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)


class ReconcileTests(LifecycleBase):
    def test_drill_event_hits_pending_drill_window(self):
        w = self.cal.write(kind="drill_result", title="Q2 drill", ticker="AGA.V",
                           window_start="2026-06-01", window_end="2026-06-30")
        ev = _ev("AGA.V", "drill_result", "2026-06-05",
                 "Silver47 intersects 12 m @ 800 g/t Ag", impact=0.6, magnitude=0.7,
                 link="https://www.newsfilecorp.com/release/1")
        rep = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(rep["hits"]), 1)
        self.assertEqual(rep["pending_remaining"], 0)
        # window is now hit, original hidden
        self.assertEqual(len(self.cal.query("AGA.V", within_days=365, status="pending", now=NOW)), 0)
        hit = self.cal.query("AGA.V", within_days=365, status="hit", now=NOW)
        self.assertEqual(len(hit), 1)
        # realized outcome stamped on the SAME identity (verbatim headline)
        self.assertEqual(hit[0]["realized"]["headline"], "Silver47 intersects 12 m @ 800 g/t Ag")
        self.assertEqual(hit[0]["realized"]["impact"], 0.6)
        self.assertEqual(hit[0]["title"], "Q2 drill")     # title carried forward through supersede

    def test_kind_family_match_grade_beat_to_drill_window(self):
        self.cal.write(kind="drill_result", title="assay window", ticker="AGA.V",
                       window_start="2026-06-01", window_end="2026-06-30")
        ev = _ev("AGA.V", "grade_beat", "2026-06-12", "bonanza grades returned", impact=0.8)
        rep = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(rep["hits"]), 1)

    def test_metallurgy_window_resolved_by_catalyst_event(self):
        self.cal.write(kind="metallurgy", title="met results P3", ticker="AGA.V",
                       window_start="2026-05-20", window_end="2026-06-08")
        ev = _ev("AGA.V", "catalyst", "2026-06-04",
                 "Metallurgical testwork returns 92% recovery", impact=0.5)
        rep = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(rep["hits"]), 1)
        self.assertEqual(rep["hits"][0]["kind"], "metallurgy")

    def test_out_of_window_event_does_not_match(self):
        self.cal.write(kind="drill_result", title="Q3 drill", ticker="AGA.V",
                       window_start="2026-07-01", window_end="2026-09-30")
        # event 3 months before the window, beyond the 14d grace -> no match
        ev = _ev("AGA.V", "drill_result", "2026-04-01", "old drilling", impact=0.4)
        rep = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(rep["hits"]), 0)
        self.assertEqual(len(rep["unmatched_realized"]), 1)
        # the future window is not past-due, so it stays pending (not missed)
        self.assertEqual(len(rep["missed"]), 0)
        self.assertEqual(rep["pending_remaining"], 1)

    def test_past_due_unmatched_window_expires_to_missed(self):
        self.cal.write(kind="assay", title="April assays", ticker="AGA.V",
                       window_start="2026-04-01", window_end="2026-05-01")
        rep = cl.reconcile(self.cal, [], now=NOW)
        self.assertEqual(len(rep["missed"]), 1)
        missed = self.cal.query("AGA.V", within_days=365, status="missed", now="2026-04-15T00:00:00Z")
        self.assertEqual(len(missed), 1)

    def test_news_event_and_wrong_ticker_are_unmatched(self):
        self.cal.write(kind="drill_result", title="AGA drill", ticker="AGA.V",
                       window_start="2026-06-01", window_end="2026-06-30")
        evs = [
            _ev("AGA.V", "news", "2026-06-05", "corporate update", impact=0.1),   # news resolves nothing
            _ev("GROY", "drill_result", "2026-06-05", "unrelated", impact=0.5),   # no GROY window
        ]
        rep = cl.reconcile(self.cal, evs, now=NOW)
        self.assertEqual(len(rep["hits"]), 0)
        self.assertEqual(len(rep["unmatched_realized"]), 2)

    def test_idempotent(self):
        self.cal.write(kind="drill_result", title="Q2 drill", ticker="AGA.V",
                       window_start="2026-06-01", window_end="2026-06-30")
        ev = _ev("AGA.V", "drill_result", "2026-06-05", "hits high grade", impact=0.6,
                 link="https://x/1")
        first = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(first["hits"]), 1)
        second = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(second["hits"]), 0)             # already hit -> no-op
        self.assertEqual(len(self.cal.query("AGA.V", within_days=365, status="hit", now=NOW)), 1)

    def test_scheduled_window_transitions_without_losing_grounding(self):
        # a SCHEDULED window has a source_url; the realized event has none -> the window's url must
        # carry forward so the hit transition doesn't trip grounded-or-silent.
        self.cal.write(kind="drill_result", title="firm Q2 drill", ticker="AGA.V",
                       window_start="2026-06-01", window_end="2026-06-30",
                       confidence="scheduled", source_url="https://issuer/pr/1")
        ev = _ev("AGA.V", "drill_result", "2026-06-05", "results out")  # no link
        rep = cl.reconcile(self.cal, [ev], now=NOW)
        self.assertEqual(len(rep["hits"]), 1)
        hit = self.cal.query("AGA.V", within_days=365, status="hit", now=NOW)[0]
        self.assertEqual(hit["source_url"], "https://issuer/pr/1")


class UnifiedViewTests(LifecycleBase):
    def test_unified_view_folds_pending_hit_and_unplanned(self):
        # a pending future window
        self.cal.write(kind="pea", title="PEA 2026", ticker="AGA.V",
                       window_start="2026-08-01", window_end="2026-09-30",
                       confidence="guided")
        # a window that will be hit
        self.cal.write(kind="drill_result", title="Q2 drill", ticker="AGA.V",
                       window_start="2026-06-01", window_end="2026-06-30")
        hit_ev = _ev("AGA.V", "drill_result", "2026-06-05", "12 m @ 800 g/t", impact=0.6,
                     link="https://x/1")
        # a realized event with NO scheduled window -> should surface as unplanned
        unplanned = _ev("AGA.V", "permitting", "2026-06-07", "Plan of Operations approved",
                        impact=0.45, link="https://x/2")
        cl.reconcile(self.cal, [hit_ev, unplanned], now=NOW)

        view = cl.unified_view(self.cal, [hit_ev, unplanned], ticker="AGA.V", now=NOW)
        by_status = {}
        for r in view:
            by_status.setdefault(r["status"], []).append(r)
        self.assertEqual(len(by_status.get("pending", [])), 1)      # the PEA
        self.assertEqual(len(by_status.get("hit", [])), 2)          # drill window + unplanned permit
        self.assertTrue(all("catalyst_id" in r for r in view))
        unplanned_rows = [r for r in view if r.get("unplanned")]
        self.assertEqual(len(unplanned_rows), 1)
        self.assertEqual(unplanned_rows[0]["title"], "Plan of Operations approved")

    def test_unified_view_status_filter(self):
        self.cal.write(kind="pea", title="PEA", ticker="AGA.V", window_start="2026-08-01",
                       window_end="2026-09-30", confidence="guided")
        pend = cl.unified_view(self.cal, [], ticker="AGA.V", status="pending", now=NOW)
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["status"], "pending")


class LinkThesisTests(LifecycleBase):
    def test_link_thesis_binds_and_supersedes(self):
        w = self.cal.write(kind="drill_result", title="Q2 drill", ticker="AGA.V",
                           window_start="2026-06-01", window_end="2026-06-30")
        new = cl.link_thesis(self.cal, w["id"], "dec_abc123")
        self.assertIsNotNone(new)
        self.assertEqual(new["linked_thesis"], "dec_abc123")
        # old hidden, new visible
        live = self.cal.query("AGA.V", within_days=365, status=None, now=NOW)
        ids = {e["id"] for e in live}
        self.assertIn(new["id"], ids)
        self.assertNotIn(w["id"], ids)

    def test_link_thesis_unknown_id_returns_none(self):
        self.assertIsNone(cl.link_thesis(self.cal, "cal_nope", "dec_x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
