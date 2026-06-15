"""Tests for the matrix CLI arg parser (matrix/__main__.py) — pure, no I/O."""
import unittest

from matrix.__main__ import build_parser


class CliTests(unittest.TestCase):
    def test_host_and_self_loop(self):
        a = build_parser().parse_args(["--host", "192.168.250.32", "--self-loop"])
        self.assertEqual(a.host, "192.168.250.32")
        self.assertTrue(a.self_loop)
        self.assertFalse(a.claim)

    def test_claim_dry_run(self):
        a = build_parser().parse_args(["--claim", "--dry-run", "--host", "x"])
        self.assertTrue(a.claim)
        self.assertTrue(a.dry_run)

    def test_once_defaults(self):
        a = build_parser().parse_args(["--once"])
        self.assertTrue(a.once)
        self.assertFalse(a.self_loop)


if __name__ == "__main__":
    unittest.main()
