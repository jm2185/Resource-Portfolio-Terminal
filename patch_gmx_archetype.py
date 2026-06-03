#!/usr/bin/env python3
"""
Phase 11 — re-route GMX.TO (Globex Mining) to the correct cash-flow archetype.

Globex Mining Enterprises is an asset-light **prospect-generator / royalty** company:
it options ground to others for cash + shares and retains NSR royalties (Berrigan,
Mont Sorcier iron, Kewagama, …), holds an equity portfolio, and does NOT develop or
operate mines. It was mis-modelled as a `developer / DFS / commodity_cyclical` name,
which applies spot-margin operating leverage it does not have.

This re-routes it to `asset_light_yield` — the same archetype as your GROY / URC.TO
royalties — so its Conviction rating is NAV / recurring-cash-flow driven (Q-weighted)
instead of producer-style commodity-cyclical. Routing precedence (archetypes.py):
an explicit `portfolio_metadata[ticker].archetype` wins, else `type` → archetype map;
this sets both consistently (`type: royalty` also maps to `asset_light_yield`).

Kept as-is (accurate for Quebec-focused Globex): `jurisdiction: CAN`, `fraser_index`,
and your analyst `management_score` — change those yourself if you want.

v5_config.json is gitignored (local-only), so this applies the change for you,
idempotently, with a timestamped backup.

Run:  python patch_gmx_archetype.py   [--config v5_config.json] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

TICKER = "GMX.TO"
# Mirror the GROY / URC.TO royalty template so GMX routes through AssetLightYieldArchetype.
FIX = {"type": "royalty", "stage": "PRODUCING", "archetype": "asset_light_yield"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Re-route GMX.TO to asset_light_yield (Phase 11).")
    ap.add_argument("--config", default="v5_config.json")
    ap.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = ap.parse_args(argv)

    path = Path(args.config)
    if not path.exists():
        raise SystemExit(f"error: {path} not found (run from the repo root, or pass --config)")

    cfg = json.loads(path.read_text())
    pm = cfg.get("portfolio_metadata", {})
    if TICKER not in pm:
        raise SystemExit(f"error: portfolio_metadata[{TICKER!r}] not found")
    meta = pm[TICKER]

    changes = [f"{k}: {meta.get(k)!r} -> {v!r}" for k, v in FIX.items() if meta.get(k) != v]
    if not changes:
        print("Nothing to do — GMX.TO already routes through asset_light_yield. ✓")
        return 0

    print(f"Planned changes to portfolio_metadata[{TICKER}]:")
    for c in changes:
        print("  " + c)

    if args.dry_run:
        print("\n--dry-run: no files written.")
        return 0

    backup = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy(path, backup)
    meta.update(FIX)
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"\n✓ wrote {path}  (backup: {backup.name})")
    print("Next: restart the engine (run_engine action=restart) so the new archetype takes effect, "
          "then check GMX.TO's Conviction rating.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
