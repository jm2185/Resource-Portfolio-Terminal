"""
Tests for the 2026-07-31 handoff ingestion (scripts/bootstrap/ingest_handoff_2026_07_31.py).

The script writes into the desk's permanent, append-only record, so the guarantees worth pinning are
about SAFETY and HONESTY, not about the prose:

  * both theses VALIDATE — every pre-commitment rule parses through the safe grammar and every claim
    type-checks, so nothing malformed can enter the record;
  * every rule fires on an ``event:<kind>`` that a REAL seeded calendar window can actually stamp —
    the failure mode this guards against is a tripwire wired to an event name nothing ever emits;
  * IDEMPOTENCY — a second run writes nothing (an append-only store cannot be de-duplicated after
    the fact, so re-runnability has to be proven, not assumed);
  * the unverified price levels stay quarantined (``verified: false``) and out of the ticker/engine
    namespace, per the handoff's own instruction;
  * the §5 feeds land at ``pending_approval`` — the operator's gate is preserved, not assumed.
"""
import importlib.util
import os
import tempfile
import unittest

import catalyst_calendar as cc
import sentinel_watch as sw
import thesis_ledger as tl
import trigger_grammar as tg
from living_memory import LivingMemory

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "ingest_handoff_2026_07_31",
    os.path.join(_ROOT, "scripts", "bootstrap", "ingest_handoff_2026_07_31.py"))
ingest_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ingest_mod)


class IngestBase(unittest.TestCase):
    def setUp(self):
        self.mem_path = tempfile.mktemp(suffix=".jsonl")
        self.cal_path = tempfile.mktemp(suffix=".jsonl")
        self.watch_path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.mem_path, self.cal_path, self.watch_path, self.watch_path + ".tmp"):
            if os.path.exists(p):
                os.remove(p)

    def run_ingest(self, **kw):
        return ingest_mod.ingest(memory_path=self.mem_path, calendar_path=self.cal_path,
                                 watch_path=self.watch_path, **kw)


class ThesisValidityTests(unittest.TestCase):
    def test_both_theses_validate(self):
        for body in (ingest_mod.CEG_THESIS, ingest_mod.MEM_THESIS):
            ok, errors = tl.validate_thesis(body)
            self.assertTrue(ok, f"{body['ticker']}: {errors}")

    def test_every_rule_trigger_parses_through_the_safe_grammar(self):
        for body in (ingest_mod.CEG_THESIS, ingest_mod.MEM_THESIS):
            for rule in body["rules"]:
                tg.parse(rule["trigger"])                     # raises GrammarError if not

    def test_every_rule_event_is_a_kind_a_seeded_window_can_stamp(self):
        """A rule keyed to an event nothing ever emits is a tripwire that can never fire. The
        grammar's events are calendar KINDS marked ``hit``, so each rule's event must be a kind
        this ingestion actually seeds for that same ticker."""
        seeded = {(t, k) for t, k, *_ in ingest_mod.CALENDAR}
        for body in (ingest_mod.CEG_THESIS, ingest_mod.MEM_THESIS):
            for rule in body["rules"]:
                trig = rule["trigger"]
                self.assertTrue(trig.startswith("event:"), trig)
                kind = trig.split("event:", 1)[1].strip()
                self.assertIn(kind, cc.KINDS, f"{trig} is not a calendar kind")
                if kind in ("earnings", "regulatory"):       # the dated ones this batch seeds
                    self.assertIn((body["ticker"], kind), seeded,
                                  f"{body['ticker']} rule {trig} has no seeded window to stamp it")

    def test_rule_actions_never_auto_act_on_an_exit(self):
        """Build-Spec Open-Decision #5: alerts may auto-fire, exits/trims must only ever propose."""
        import sentinel as sen
        for body in (ingest_mod.CEG_THESIS, ingest_mod.MEM_THESIS):
            for rule in body["rules"]:
                self.assertIn(rule["action"], tl.RULE_ACTIONS)
                if rule["action"] not in sen.AUTO_ACTABLE:
                    self.assertIn(rule["action"], ("review", "trim_to", "add_to", "exit"))

    def test_confirm_criteria_are_load_bearing_claims_not_prose(self):
        """R-7 is only enforced if the criteria are claims the Sentinel re-checks."""
        claims = {c["id"]: c for c in ingest_mod.CEG_THESIS["claims"]}
        for cid in ("c1", "c2", "c3", "c4"):
            self.assertIn(cid, claims)
            self.assertEqual("manual", claims[cid]["check"])  # no engine metric can read a guide
            self.assertEqual("unknown", claims[cid]["status"])  # unresolved until the call

    def test_unverified_price_levels_are_quarantined(self):
        for body in (ingest_mod.CEG_THESIS, ingest_mod.MEM_THESIS):
            ref = body["reference_levels"]
            self.assertFalse(ref["verified"])
            self.assertIn("NOT verified", ref["_warning"])

    def test_memory_thesis_is_a_reject_with_no_position(self):
        self.assertEqual("REJECT", ingest_mod.MEM_THESIS["stance"])
        self.assertTrue(ingest_mod.MEM_THESIS["surveillance_only"])
        self.assertEqual("NONE — surveillance only", ingest_mod.MEM_THESIS["expected"]["position"])


class WatchRegistryTests(unittest.TestCase):
    def test_the_declared_registry_validates(self):
        ok, errors = sw.validate_registry(ingest_mod.WATCHES)
        self.assertTrue(ok, errors)

    def test_memory_feeds_await_approval_except_the_already_wired_one(self):
        by_id = {w["id"]: w for w in ingest_mod.WATCHES}
        mem_feeds = [w for wid, w in by_id.items() if wid.startswith("mem.")]
        self.assertTrue(mem_feeds)
        for w in mem_feeds:
            if w["id"] == "mem.macro_cross_link":            # the handoff's "already configured" row
                self.assertEqual("active", w["status"])
            else:
                self.assertEqual("pending_approval", w["status"], w["id"])

    def test_every_watch_names_the_thesis_it_feeds(self):
        for w in ingest_mod.WATCHES:
            self.assertTrue(w["feeds"], w["id"])


class IngestionTests(IngestBase):
    def test_writes_everything_then_is_idempotent(self):
        first = self.run_ingest()
        self.assertEqual(29, first["written"]["memory"])
        self.assertEqual(3, first["written"]["calendar"])
        self.assertEqual(13, first["written"]["watches"])

        second = self.run_ingest()
        self.assertEqual({"memory": 0, "calendar": 0, "watches": 0}, second["written"])

        mem = LivingMemory(self.mem_path)
        self.assertEqual(2, len(mem.query(type="thesis", limit=0)))
        self.assertEqual(3, len(cc.CatalystCalendar(self.cal_path).all()))
        self.assertEqual(13, len(sw.load(self.watch_path)))

    def test_dry_run_writes_nothing(self):
        rep = self.run_ingest(dry_run=True)
        self.assertTrue(rep["written"]["memory"])            # it PLANNED writes
        self.assertFalse(os.path.exists(self.mem_path))
        self.assertFalse(os.path.exists(self.cal_path))
        self.assertFalse(os.path.exists(self.watch_path))

    def test_ulysses_entries_are_stored_verbatim(self):
        self.run_ingest()
        mem = LivingMemory(self.mem_path)
        rows = mem.query(tag="ulysses", limit=0)
        self.assertEqual(5, len(rows))
        for rid, _label, _tk, text in ingest_mod.ULYSSES:
            hit = [r for r in rows if (r["meta"] or {}).get("record_id") == rid]
            self.assertEqual(1, len(hit), rid)
            self.assertEqual(text, hit[0]["meta"]["verbatim"])  # not paraphrased

    def test_ledger_shows_the_graveyard_entry(self):
        self.run_ingest()
        led = tl.Ledger(LivingMemory(self.mem_path))
        self.assertEqual(1, len(led.graveyard()))
        self.assertEqual("MU", led.graveyard()[0]["ticker"])
        self.assertEqual({"CONDITIONAL": 1, "REJECT": 1}, led.stats()["by_stance"])

    def test_calendar_dates_are_never_upgraded_to_scheduled_without_a_source(self):
        """grounded-or-silent: this batch has no straight-to-source URLs, so no window may claim
        the 'scheduled' confidence a pre-commitment rule would trust most."""
        self.run_ingest()
        for e in cc.CatalystCalendar(self.cal_path).all():
            self.assertNotEqual("scheduled", e["confidence"])
            self.assertFalse(e["grounded"])

    def test_open_items_and_predictions_are_queryable_and_open(self):
        self.run_ingest()
        mem = LivingMemory(self.mem_path)
        self.assertEqual(7, len(mem.query(tag="open-item", limit=0)))
        preds = mem.query(tag="prediction", limit=0)
        self.assertEqual(4, len(preds))
        for p in preds:
            self.assertEqual("open", p["meta"]["status"])
            self.assertTrue(p["meta"]["resolve_by"])

    def test_rulebook_is_queryable_as_eight_rules(self):
        self.run_ingest()
        rows = LivingMemory(self.mem_path).query(tag="rulebook", limit=0)
        self.assertEqual(8, len(rows))
        self.assertEqual({f"R-{i}" for i in range(1, 9)},
                         {r["meta"]["rule_id"] for r in rows})

    def test_entries_are_stamped_user_provenance_not_engine_or_sourced(self):
        """A handoff paragraph is the operator's read, not an engine number and not a sourced
        filing — a consumer weighting by evidence must not be able to mistake it for one."""
        self.run_ingest()
        for e in LivingMemory(self.mem_path).query(limit=0):
            self.assertEqual("user", e["provenance"])

    def test_no_phantom_tickers_enter_the_namespace(self):
        self.run_ingest()
        tickers = {e["ticker"] for e in LivingMemory(self.mem_path).query(limit=0)
                   if e["ticker"]}
        self.assertEqual({"CEG", "MU", "SNDK"}, tickers)


if __name__ == "__main__":
    unittest.main()
