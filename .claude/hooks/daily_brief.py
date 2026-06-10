#!/usr/bin/env python3
"""SessionStart hook — greet every cockpit session with a live daily brief (COCKPIT.md Tier 1).

Whatever this prints to stdout is added to Claude's context at session start, so the agent
never opens blind: regime + posture, the rated book, working pipeline, recent Living Memory —
the same shared situational frame (world_state.render_brief) the desk agents already inherit.

Grounded-or-silent: engine offline → one honest line, never invented numbers. Fail-open
(always exit 0) so a hook hiccup can never block a session.
"""
import json
import os
import sys
import urllib.request

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
ENGINE = os.environ.get("CEX_ENGINE_URL", "http://127.0.0.1:8000")


def main() -> None:
    state = None
    try:
        with urllib.request.urlopen(f"{ENGINE}/state", timeout=2.5) as r:  # noqa: S310
            state = json.loads(r.read().decode("utf-8"))
    except Exception:
        pass
    if not state:
        print("## DAILY BRIEF — engine offline (start it with ./cockpit.sh); no live numbers yet.")
        return
    import world_state
    recent = None
    try:
        import living_memory
        mem = living_memory.LivingMemory(path=os.path.join(ROOT, "data", "living_memory.jsonl"))
        recent = mem.query(limit=5)
    except Exception:
        recent = None
    print("## DAILY BRIEF — cockpit session start")
    print(world_state.render_brief(world_state.build(state, recent_memory=recent)))
    # catalyst windows, straight from live state (grounded-or-silent: absent → say nothing)
    try:
        wins = []
        for b in ((state.get("conviction_mode") or {}).get("baskets") or []):
            for c in (b.get("catalysts") or [])[:1]:
                head = str(c.get("headline", "")).strip()
                if head:
                    wins.append(f"{b.get('ticker')}: {head[:60]}")
        if wins:
            print("- Catalyst watch: " + " · ".join(wins[:4]))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # the brief must never block a session
        print(f"## DAILY BRIEF — unavailable ({exc})")
    sys.exit(0)
