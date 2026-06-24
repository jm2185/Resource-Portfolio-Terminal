"""narrative_integrity — the NIS check for operating turnarounds (Phase 5 of the dual-sided TIV spec):
grade a turnaround narrative claim-by-claim against its receipts, locate the live risk, fire a
narrative_break when a receipt reverses. Pure, hand-verifiable; the Euronet fixture is the worked case."""
import unittest

import narrative_integrity as ni

# The Euronet turnaround, decomposed: three claims with confirming receipts + the live risk (Ria,
# whose receipt has reversed under immigration policy) — exactly the case a resource-catalyst check misses.
EURONET = [
    {"claim": "ATM share of EFT falling (de-risking the melt)",
     "receipt": "10-K segment disclosure: ATM ~90%→~60% 2019–2024", "trend": "improving",
     "source": "EDGAR 10-K 2024", "area": "EFT / ATM", "kind": "segment_trend"},
    {"claim": "REN / CoreCard winning recurring-revenue deals",
     "receipt": "issuer PR: multiple REN platform wins 2023–24", "trend": "improving",
     "source": "issuer PR", "area": "epay / REN", "kind": "contract"},
    {"claim": "EU cash-access regulation mandates ATM outsourcing (tailwind)",
     "receipt": "EU member-state cash-access rules", "trend": "improving",
     "source": "regulatory", "area": "regulation", "kind": "regulatory"},
    {"claim": "Ria remittance resilient to US immigration policy",
     "receipt": "Q guidance: Ria volume outlook cut on immigration policy", "trend": "deteriorating",
     "source": "issuer PR", "area": "Ria remittance / immigration", "kind": "segment_trend"},
]


class GradeTests(unittest.TestCase):
    def test_euronet_score_risk_locus_and_break(self):
        g = ni.grade("EEFT", EURONET, lens="deep_value", listing="EEFT")
        self.assertTrue(g["available"])
        self.assertAlmostEqual(g["integrity_score"], 0.75, places=3)   # 3 confirmed + 1 broken / 4
        self.assertIn("Ria", g["risk_locus"])                          # the pressure relocated to Ria
        self.assertTrue(any(f["id"] == "narrative_break" for f in g["flags"]))
        self.assertEqual([c["status"] for c in g["claims"]],
                         ["confirmed", "confirmed", "confirmed", "broken"])

    def test_hand_waving_is_unsupported_fail_closed(self):
        # claims with NO receipts must be unsupported even if the trend asserts "improving"
        hand = [{"claim": "the turnaround is working", "trend": "improving"},
                {"claim": "margins will recover", "trend": "improving"}]
        g = ni.grade("XYZ", hand, lens="deep_value")
        self.assertEqual(g["integrity_score"], 0.0)
        self.assertTrue(all(c["status"] == "unsupported" for c in g["claims"]))
        self.assertEqual(g["flags"], [])                               # unsupported ≠ broken (no false alarm)

    def test_empty_is_graceful(self):
        self.assertFalse(ni.grade("XYZ", [])["available"])


class FacetsTests(unittest.TestCase):
    def test_context_aware_by_profile(self):
        op = ni.nis_facets(lens="deep_value")
        self.assertEqual(op["kind"], "operating_turnaround")
        self.assertFalse(op["drill_relevant"])
        self.assertIn("segment", op["receipt_system"].lower())
        ex = ni.nis_facets(archetype="option_convexity")
        self.assertEqual(ex["kind"], "resource_catalyst")
        self.assertTrue(ex["drill_relevant"])                          # a drill leak applies to an explorer, not a turnaround
        roy = ni.nis_facets(archetype="asset_light_yield")
        self.assertEqual(roy["kind"], "royalty")

    def test_filing_system_by_listing(self):
        self.assertIn("EDGAR", ni.nis_facets(lens="deep_value", listing="EEFT")["filing"])
        self.assertIn("SEDAR", ni.nis_facets(lens="deep_value", listing="X.TO")["filing"])


class QAndDedupTests(unittest.TestCase):
    def test_nis_to_q_lifts_and_caps(self):
        self.assertEqual(ni.nis_to_q(0.8)["management_proxy"], 0.8)
        self.assertIn("lift", ni.nis_to_q(0.8)["note"])
        self.assertIn("cap", ni.nis_to_q(0.2)["note"])
        self.assertIsNone(ni.nis_to_q(None)["management_proxy"])       # passthrough when ungraded

    def test_select_fresh_dedup_and_new_claim(self):
        flags = [{"id": "narrative_break", "ticker": "EEFT", "claim": "Ria"}]
        fresh, fired = ni.select_fresh(flags, {}, today="2026-06-24")
        self.assertEqual(len(fresh), 1)
        self.assertEqual(ni.select_fresh(flags, fired, today="2026-06-24")[0], [])   # same claim, same day
        other = [{"id": "narrative_break", "ticker": "EEFT", "claim": "epay"}]
        self.assertEqual(len(ni.select_fresh(other, fired, today="2026-06-24")[0]), 1)  # a new claim breaks


if __name__ == "__main__":
    unittest.main()
