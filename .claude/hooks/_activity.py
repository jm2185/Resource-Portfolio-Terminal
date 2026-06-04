#!/usr/bin/env python3
"""Compact a Claude Code hook event (JSON on stdin) into a cockpit agent-activity payload.

argv: <kind> <agent>.  Prints one JSON line to POST to /agent/activity, or nothing (skip).
Kept as a file (not an inline heredoc) so the event JSON on stdin isn't shadowed by the program.
"""
import json
import sys

kind = sys.argv[1] if len(sys.argv) > 1 else "note"
agent = sys.argv[2] if len(sys.argv) > 2 else "claude"
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}

if kind == "prompt":
    s = d.get("prompt", "")
elif kind == "tool":
    name = str(d.get("tool_name", "") or "")
    if not name.startswith("mcp__"):          # keep the stream signal-rich: book-relevant MCP only
        sys.exit(0)
    short = name.split("__")[-1]
    ti = d.get("tool_input") or {}
    arg = ""
    if isinstance(ti, dict):
        for k in ("ticker", "key", "name", "overrides", "action", "change_id"):
            if ti.get(k):
                arg = f" {ti[k]}"
                break
    s = f"{short}{arg}"
elif kind == "response":
    s = "responded"
else:
    s = d.get("hook_event_name", kind)

s = " ".join(str(s).split())[:200]
if not s:
    sys.exit(0)
print(json.dumps({"agent": agent, "kind": kind, "summary": s}))
