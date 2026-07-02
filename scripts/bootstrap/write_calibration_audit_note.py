"""
P1.4 — append the CALIBRATION audit as a typed, append-only note to Living Memory (the cockpit's
audit trail every view/agent reads). Idempotent: re-running is a no-op once the note exists.

Run:  python scripts/write_calibration_audit_note.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import living_memory  # noqa: E402

GUARD_TAG = "p1-audit-2026-06-20"

TEXT = (
    "CALIBRATION AUDIT (action-plan P1) — T·Q·V scoring factors. "
    "T (tailwind) made FORWARD-STRUCTURAL: backward-looking momentum stripped from the commodity "
    "regime (uranium was 100% price-momentum, gold 40% dollar-momentum) into a separate, labeled "
    "compute_momentum() that never enters T; a strong-secular/weak-tape gold royalty (GROY shape) "
    "now scores ~+1.1 higher tailwind. Q VERIFIED-FIXED and locked with regression guardrails "
    "(archetype tag · pre-PEA stage penalty · archetype-specific Q-weight · JSF universal gate). "
    "V legibility deepened to Q's depth incl. the self-inverting property (high V = entry; V "
    "compressing on strength = thesis working) and a V<->Q cross-link. V-vs-coverage curve audited: "
    "the linear support term FLAT-SHELFS at phi=1.25 (over-credits a marginal entry); a "
    "depth-sensitive curve is implemented behind conviction_mode.support_curve='depth' (default "
    "stays 'linear' — proposal-gated /confirm). Deferred: two upstream engine momentum terms in MRI "
    "/ alpha_option remain (proposal-gated follow-up). Full audit: docs/archive/CALIBRATION_AUDIT_2026-06-20.md."
)


def main():
    mem = living_memory.LivingMemory()
    existing = mem.query(type="note", tag=GUARD_TAG, limit=1)
    if existing:
        print(f"note already present ({existing[0]['id']}) — skipping (append-only, idempotent).")
        return
    entry = mem.write(
        "note", text=TEXT, source="calibration",
        tags=["calibration", "audit", "scoring", "tailwind", "value", GUARD_TAG],
        meta={"doc": "docs/archive/CALIBRATION_AUDIT_2026-06-20.md",
              "curve": "docs/archive/v_coverage_curve.md",
              "workstreams": ["P1.1", "P1.2", "P1.3", "P1.4", "P1.5"],
              "proposal": "conviction_mode.support_curve='depth' (P1.5) — awaiting /confirm"},
    )
    print(f"wrote CALIBRATION audit note → {entry['id']}")


if __name__ == "__main__":
    main()
