"""
Seed / migrate existing research into Living Memory (Forge Phase 1).

Non-destructive and idempotent: scans data/decisions/*.md (the rendered research threads + pipeline
dossiers) and registers each as a ``thread`` memory entry pointing back at its markdown file. The
.md files remain the human-readable rendered view; Living Memory just indexes them so they are
queryable and connected. Safe to re-run — already-imported files (tracked by meta.source_file) are
skipped.

Run:  python seed_living_memory.py
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))  # repo root (script lives in scripts/bootstrap/)

import glob
import os
import re

import living_memory as lm

DECISIONS_DIR = "data/decisions"


def _parse_ticker(filename: str):
    """Recover a ticker from a decision filename: 'AGA_V_thread_...' -> 'AGA.V'. Pipeline/lost-chat
    files have no single name -> None (book-level)."""
    base = os.path.basename(filename)
    if base.lower().startswith(("pipeline_", "lost_chat", "lost-chat")):
        return None
    m = re.match(r"^([A-Z]{1,5})_([A-Z]{1,2})_thread", base)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    m = re.match(r"^([A-Z]{1,6})_thread", base)        # ticker with no exchange suffix
    if m:
        return m.group(1)
    return None


def _parse_ts(filename: str):
    """Recover an ISO-ish timestamp from a '..._YYYYMMDD-HHMMSS.md' filename, else None."""
    m = re.search(r"(\d{8})-(\d{6})", os.path.basename(filename))
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}Z"


def import_decisions(mem: lm.LivingMemory, decisions_dir: str = DECISIONS_DIR) -> dict:
    """Register every *.md decision/thread as a ``thread`` entry. Returns {imported, skipped}."""
    already = {(e.get("meta") or {}).get("source_file")
               for e in mem.all() if e.get("type") == "thread"}
    imported, skipped = 0, 0
    for path in sorted(glob.glob(os.path.join(decisions_dir, "*.md"))):
        rel = os.path.relpath(path)
        if rel in already:
            skipped += 1
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                body = fh.read()
        except OSError:
            continue
        # first line with real content (skip markdown headers' hashes and ===/--- decoration rules)
        title = rel
        for ln in body.splitlines():
            s = ln.lstrip("# ").strip()
            if s and re.search(r"[A-Za-z0-9]", s) and not re.fullmatch(r"[=\-_*\s]+", s):
                title = s
                break
        is_pipeline = os.path.basename(path).lower().startswith("pipeline_")
        mem.write(
            "thread",
            text=title[:240],
            ticker=_parse_ticker(path),
            ts=_parse_ts(path),
            tags=["imported"] + (["pipeline"] if is_pipeline else []),
            source="import",
            refs=[rel],
            meta={"source_file": rel, "kind": "pipeline" if is_pipeline else "research_thread",
                  "chars": len(body)},
        )
        imported += 1
    return {"imported": imported, "skipped": skipped, "store_total": mem.stats()["total"]}


def main():
    mem = lm.LivingMemory()
    res = import_decisions(mem)
    print(f"Living Memory seeded: imported {res['imported']} thread(s), "
          f"skipped {res['skipped']} (already present). Store total: {res['store_total']}.")
    print(f"Store: {mem.path}")


if __name__ == "__main__":
    main()
