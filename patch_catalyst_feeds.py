#!/usr/bin/env python3
"""
Phase 10 — patch the local catalyst config with straight-to-source company feeds.

WHY a script:  v5_config.json is gitignored (local-only on your machine), so it can't
be delivered through git like normal code. This script applies the change for you,
idempotently, with a timestamped backup.

What it does to  catalysts.providers[rss_news].params  (and nothing else):
  1. FIX a misidentification bug — GMX.TO is *Globex Mining Enterprises*, not
     "GoldMining Inc". Its ticker_aliases are corrected (goldmining -> globex).
  2. ADD per-company press-release feeds so the three Canadian names get catalyst
     coverage (EDGAR can't see .V/.TO filers; SEDAR+ is a disabled stub):
       • AGA.V (Silver47)        -> Newsfile issuer feed, BOUND to the ticker
                                    (every item is a real Silver47 PR -> relevance 1.0)
       • GMX.TO (Globex Mining)  -> Yahoo per-ticker feed, UNBOUND (alias-filtered, so
                                    only items naming Globex attribute -> drops market noise)
       • URC.TO (Uranium Royalty)-> Yahoo per-ticker feed, UNBOUND (alias-filtered)

Run:  python patch_catalyst_feeds.py          (uses ./v5_config.json)
      python patch_catalyst_feeds.py --config /path/to/v5_config.json
      python patch_catalyst_feeds.py --dry-run     (show changes, write nothing)

Safe to re-run: existing feeds/aliases are detected and not duplicated.
After it runs:  re-run ingestion (force=true, catalysts=true) and the 3 names should
attribute. The bound Newsfile feed is straight-from-the-issuer; the two Yahoo feeds
are ticker-exact aggregators (a fine stopgap until a per-company GlobeNewswire/wire
feed is wired for Globex/URC).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

# Corrected aliases (distinctive, >=5 chars, whole-word matched by the RSS adapter).
GMX_ALIASES_FIX = ["globex mining enterprises", "globex mining", "globex"]

# (url, ticker_or_None). ticker set -> feed is bound (relevance 1.0, trust the source is
# pure issuer PRs); ticker None -> alias-scored so only genuine company items attribute.
NEW_FEEDS = [
    ("https://feeds.newsfilecorp.com/company/10967", "AGA.V"),                                  # Silver47 — issuer wire
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=GMX.TO&region=US&lang=en-US", None),    # Globex — alias-filtered
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=URC.TO&region=US&lang=en-US", None),    # URC — alias-filtered
]


def _rss_params(cfg: dict) -> dict:
    providers = cfg.get("catalysts", {}).get("providers")
    if not isinstance(providers, list):
        raise SystemExit("error: catalysts.providers not found — is this a v5_config.json?")
    for p in providers:
        if isinstance(p, dict) and p.get("name") == "rss_news":
            return p.setdefault("params", {})
    raise SystemExit("error: rss_news provider not found in catalysts.providers")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Patch v5_config.json catalyst feeds (Phase 10).")
    ap.add_argument("--config", default="v5_config.json")
    ap.add_argument("--dry-run", action="store_true", help="print changes, write nothing")
    args = ap.parse_args(argv)

    path = Path(args.config)
    if not path.exists():
        raise SystemExit(f"error: {path} not found (run from the repo root, or pass --config)")

    cfg = json.loads(path.read_text())
    params = _rss_params(cfg)
    changes: list[str] = []

    # 1) Fix the GMX.TO misidentification.
    aliases = params.setdefault("ticker_aliases", {})
    if aliases.get("GMX.TO") != GMX_ALIASES_FIX:
        changes.append(f"GMX.TO aliases: {aliases.get('GMX.TO')!r} -> {GMX_ALIASES_FIX!r}")
        aliases["GMX.TO"] = GMX_ALIASES_FIX

    # 2) Add company feeds (idempotent on url).
    feeds = params.setdefault("feeds", [])
    have = {f.get("url") for f in feeds if isinstance(f, dict)}
    for url, ticker in NEW_FEEDS:
        if url in have:
            continue
        entry = {"url": url}
        if ticker:
            entry["ticker"] = ticker
        feeds.append(entry)
        changes.append(f"+ feed {'[' + ticker + '] ' if ticker else '(alias-filtered) '}{url}")

    if not changes:
        print("Nothing to do — config already patched. ✓")
        return 0

    print("Planned changes to %s:" % path)
    for c in changes:
        print("  " + c)

    if args.dry_run:
        print("\n--dry-run: no files written.")
        return 0

    backup = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy(path, backup)
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"\n✓ wrote {path}  (backup: {backup.name})")
    print("Next: re-run ingestion (force=true, catalysts=true) and check AGA.V / GMX.TO / URC.TO attribute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
