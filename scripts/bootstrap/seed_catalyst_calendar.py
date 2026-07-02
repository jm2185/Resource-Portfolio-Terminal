#!/usr/bin/env python3
"""
Seed the catalyst calendar with AGA.V (Silver47)'s GROUNDED 2026 catalyst windows.

Every window is straight-to-source (issuer PR / Newsfile / Junior Mining Network) and seeded at
confidence='estimated': the issuer SOURCED the drill / metallurgical PROGRAM but did not publish a
firm RESULT date, so the window is an honest approximation of result timing (flagged 'estimated',
NOT 'scheduled') carrying the source URL for provenance — grounded-or-silent.

Idempotent: re-running skips any window already present (same ticker + kind + source_url), so it is
safe to run repeatedly and safe to run after the engine has already created the calendar (it only
appends what's missing).

Run once on the engine host:

    python seed_catalyst_calendar.py            # writes to data/catalyst_calendar.jsonl
    python seed_catalyst_calendar.py PATH        # or an explicit path (used by tests)

Once seeded the windows feed the Sentinel's catalyst-window protection, the rotation catalyst-lock,
the cockpit's upcoming-catalysts strip, and the Phase-1 lifecycle (reconcile -> hit/missed).
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))  # repo root (script lives in scripts/bootstrap/)

import sys

from catalyst_calendar import CatalystCalendar

# (ticker, kind, title, window_start, window_end, confidence, source, source_url, notes)
WINDOWS = [
    ("AGA.V", "drill_result",
     "Red Mountain 2026 drill program (10,000 m, 3 rigs) — assay results",
     "2026-07-15", "2026-12-31", "estimated", "Newsfile",
     "https://www.juniorminingnetwork.com/junior-miner-news/press-releases/3384-tsx-venture/aga/205343-silver47-commences-fully-funded-10-000-meter-drill-program-at-the-red-mountain-silver-and-critical-minerals-project-alaska.html",
     "Flagship 10,000 m core program commenced 2026-06-12 (PR); 3 rigs by end-June. Result window "
     "estimated from the sourced program — issuer guided 'consistent news flow through year-end'."),

    ("AGA.V", "drill_result",
     "Hughes 2026 drill program (7,000 m, Tonopah E. extension) — assay results",
     "2026-06-17", "2026-09-30", "estimated", "Newsfile",
     "https://www.newsfilecorp.com/release/285850",
     "7,000 m program commenced 2026-03-23 targeting Ruby/Sapphire/Emerald; runs 'early March "
     "through to summer' (Kitco). Result window estimated."),

    ("AGA.V", "drill_result",
     "Mogollon 2026 winter program (Last Chance Vein) — assay results pending",
     "2026-06-17", "2026-09-30", "estimated", "Newsfile",
     "https://www.juniorminingnetwork.com/junior-miner-news/press-releases/3384-tsx-venture/aga/195493-silver47-launches-drilling-to-target-depth-extensions-of-high-grade-silver-at-mogollon-silver-gold-project-new-mexico.html",
     "Winter program launched 2026-01-21 (Last Chance Vein depth extensions); no assay PR released "
     "as of research — results pending. Estimated window."),

    ("AGA.V", "metallurgy",
     "Hughes Belmont tailings metallurgical (CIL) testwork results",
     "2026-06-17", "2026-09-30", "estimated", "Newsfile",
     "https://www.juniorminingnetwork.com/junior-miner-news/press-releases/3384-tsx-venture/aga/197634-silver47-begins-metallurgical-testwork-to-confirm-reprocessing-potential-of-historic-mine-tailings-at-hughes-nevada.html",
     "CIL metallurgical testwork on the Belmont historic tailings underway since 2026-02-19 "
     "(samples to Forte Analytical); result window estimated."),
]


def seed(path: str | None = None):
    """Append any missing AGA.V windows; return (written_titles, skipped_titles)."""
    cal = CatalystCalendar(path) if path else CatalystCalendar()
    existing = {(e.get("ticker"), e.get("kind"), e.get("source_url")) for e in cal.all()}
    written, skipped = [], []
    for tk, kind, title, ws, we, conf, src, url, notes in WINDOWS:
        key = (tk, kind, url)
        if key in existing:
            skipped.append(title)
            continue
        cal.write(ticker=tk, kind=kind, title=title, window_start=ws, window_end=we,
                  confidence=conf, source=src, source_url=url, notes=notes)
        existing.add(key)
        written.append(title)
    return written, skipped


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    written, skipped = seed(path)
    print(f"seeded {len(written)} window(s); skipped {len(skipped)} already present")
    for t in written:
        print("  + " + t)
    for t in skipped:
        print("  = " + t + "  (already seeded)")
