"""
Watch-bench loader (Forge-Matrix) — the operator/agent list of names monitored for rotation/watch.

There is no persisted standing bench in the engine today (the matchup desk's bench is session-only,
research_cache holds PEERS, and the EVAL set is empty), so the cockpit owns a simple, explicit list at
``data/matrix_bench.json``. The M5 orchestrator reads it, prices the names via FMP, and injects them as
``monitored`` into ``build_matrix_state`` (which appends them as eval_only WatchItems for the crawl's
WATCH section). Pure stdlib; absent/unreadable file -> empty list (the WATCH section just doesn't show).
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "matrix_bench.json")


def load_bench(path: Optional[str] = None) -> List[str]:
    """Return the bench tickers (upper-cased), or [] if the file is missing/unreadable."""
    try:
        with open(path or _PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        names = d.get("bench") if isinstance(d, dict) else d
        return [str(t).upper() for t in (names or []) if str(t).strip()]
    except Exception:
        return []
