"""The book-membership contract — one place that fails when the shipped book changes shape.

Holdings move (URC.TO removed 2026-07-31, GMX.TO exited 2026-08-13) and every test that spelled
the book out in a literal rotted silently: eight of them were asserting a portfolio that no longer
existed, so the suite was red for a reason that had nothing to do with the code under test.

The structural fix is ``tests.helpers.live_*`` — membership derived from ``v5_config.json`` in ONE
place. This module guards THAT: it asserts the shipped config is internally coherent, so a config
change that would break many suites fails HERE first, with a message naming the actual problem,
instead of scattering confusing failures across the router, sizer and ingestion tests.

The rule these encode, for anyone adding a test later: **name a specific ticker only when that
ticker IS the subject** (ticker-identity guards, a named regression). If the test just needs "the
book", "a ballast", or "some holdco", derive it from ``tests.helpers`` or build a synthetic fixture.
"""
import unittest

from tests.helpers import (live_ballasts, live_barbell, live_config, live_resource_names,
                           live_spear)


class BookMembershipContractTests(unittest.TestCase):
    def setUp(self):
        self.cfg = live_config()

    def test_barbell_is_non_empty_and_sums_to_one(self):
        bw = live_barbell(self.cfg)
        self.assertTrue(bw, "barbell_weights is empty — the sizer has no book to weight")
        self.assertAlmostEqual(sum(bw.values()), 1.0, places=6,
                               msg=f"barbell must sum to 1.0, got {sum(bw.values())}: {bw}")

    def test_every_barbell_name_is_a_known_holding(self):
        pm = self.cfg["portfolio_metadata"]
        for tk in live_barbell(self.cfg):
            self.assertIn(tk, pm, f"{tk} carries barbell weight but has no portfolio_metadata "
                                  f"entry — a phantom the sizer would still size")

    def test_spear_resolves_and_carries_weight(self):
        spear = live_spear(self.cfg)
        self.assertTrue(spear, "no name fills the silver-spear slot and no barbell name to fall "
                               "back on")
        self.assertIn(spear, live_barbell(self.cfg), f"spear {spear} carries no barbell weight")

    def test_at_least_one_ballast_remains(self):
        # a barbell of one name is not a barbell — the correlation gauge averages over nothing
        self.assertTrue(live_ballasts(self.cfg),
                        "every barbell name is the spear — no ballast left to diversify against")

    def test_resource_names_exclude_the_conventional_lane(self):
        import dual_sided
        pm = self.cfg["portfolio_metadata"]
        names = live_resource_names(self.cfg)
        self.assertTrue(names, "no resource-lane name — the resource router would register nothing")
        for tk in names:
            self.assertFalse(dual_sided.is_conventional(tk, pm),
                             f"{tk} is conventional-lane but leaked into the resource set")

    def test_departed_names_are_gone_from_every_ticker_keyed_block(self):
        """remove_holding's contract: a cut leaves no residue anywhere. Verified against the two
        names actually removed, so a partial removal is caught rather than discovered months later
        by a test failing for an unrelated-looking reason."""
        blocks = ("barbell_weights", "portfolio_metadata", "ballast_multiples", "ballast_valuation")
        for departed in ("URC.TO", "GMX.TO"):
            for block in blocks:
                self.assertNotIn(departed, self.cfg.get(block) or {},
                                 f"{departed} still present in {block} — remove_holding left residue")


if __name__ == "__main__":
    unittest.main()
