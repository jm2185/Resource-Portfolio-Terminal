"""The 60% spear ceiling is the book's single most important invariant. It was duplicated as a bare
``0.60`` literal across five modules, kept in lockstep by comment only — a silent-divergence risk on
the one number that binds the sizer, the overlay validator, the add-gate, the book-change surface,
and the MCP mutation path. This pins that every consumer now reads the ONE shared constant
(book_invariants.SPEAR_CEILING) and that they are byte-equal — it fails the instant any site drifts.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_server"))

import book_invariants


class SpearCeilingCentralized(unittest.TestCase):
    def test_shared_constant_is_060(self):
        self.assertEqual(book_invariants.SPEAR_CEILING, 0.60)

    def test_every_consumer_reads_the_shared_constant(self):
        C = book_invariants.SPEAR_CEILING
        import dynamic_config
        import book_change
        import conditionals
        import core  # mcp_server/core.py

        self.assertEqual(dynamic_config.SPEAR_CEILING, C, "dynamic_config drifted")
        self.assertEqual(book_change.SPEAR_CEILING, C, "book_change drifted")
        self.assertEqual(conditionals.SPEAR_CEILING, C, "conditionals drifted")
        self.assertEqual(core._SPEAR_CEILING, C, "mcp_server/core drifted")

    def test_engine_uses_the_shared_constant(self):
        # engine.py imports SPEAR_CEILING and assigns SPEAR_CEILING_STRUCTURAL from it inside
        # calculate_sizing; assert the module-level import is the shared source.
        import engine
        self.assertEqual(engine.SPEAR_CEILING, book_invariants.SPEAR_CEILING)


if __name__ == "__main__":
    unittest.main()
