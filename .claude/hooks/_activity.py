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

# On a Stop, lift the agent's final message out of the transcript so the cockpit can show the
# actual reply (its prompt-output panel), not just "responded". Best-effort; falls back silently.
reply_text = ""
if kind == "response":
    tp = d.get("transcript_path")
    if tp:
        try:
            last = ""
            with open(tp, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    msg = o.get("message") or {}
                    if o.get("type") == "assistant" or msg.get("role") == "assistant":
                        c = msg.get("content")
                        if isinstance(c, list):
                            t = " ".join(b.get("text", "") for b in c
                                         if isinstance(b, dict) and b.get("type") == "text")
                        else:
                            t = str(c or "")
                        if t.strip():
                            last = t.strip()
            reply_text = last
        except Exception:
            reply_text = ""

s = " ".join(str(s).split())[:200]
if reply_text:
    payload = {"agent": agent, "kind": "reply",
               "summary": " ".join(reply_text.split())[:180], "text": reply_text[:6000]}
elif s:
    payload = {"agent": agent, "kind": kind, "summary": s}
else:
    sys.exit(0)
print(json.dumps(payload))
