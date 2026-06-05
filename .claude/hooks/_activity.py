#!/usr/bin/env python3
"""Compact a Claude Code hook event (JSON on stdin) into a cockpit agent-activity payload.

argv: <kind> <agent>.  Prints one JSON line to POST to /agent/activity, or nothing (skip).
Kept as a file (not an inline heredoc) so the event JSON on stdin isn't shadowed by the program.

Forge "nervous system" #2: this is where the OPERATOR's terminal actions enter the cockpit. The
PostToolUse hook fires for every tool Claude runs at your direction — so beyond book-relevant MCP
calls, we now also stream the actual Bash commands, file edits, and git operations as semantic
events (kind = ran / edited / git). Secrets are redacted before anything leaves this machine.
"""
import json
import os
import re
import sys

kind = sys.argv[1] if len(sys.argv) > 1 else "note"
agent = sys.argv[2] if len(sys.argv) > 2 else "claude"
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}

# Redact anything that looks like a secret (long opaque tokens, API keys, .env contents) so the
# desk tape can never surface a credential — the tape is shown on screen and rides terminal_state.
_SECRET = re.compile(r"[A-Za-z0-9_\-]{24,}")


def _redact(s: str) -> str:
    s = " ".join(str(s or "").split())
    if re.search(r"\.env\b|API_KEY|TOKEN|SECRET|PASSWORD|Authorization", s, re.I):
        return "‹redacted: touches a secret›"
    return _SECRET.sub("***", s)


def _relpath(p: str) -> str:
    p = str(p or "")
    cwd = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if cwd and p.startswith(cwd):
        p = p[len(cwd):].lstrip("/")
    return os.path.basename(p) if "/" not in p else p[-48:]


ev_kind, s = kind, ""
if kind == "prompt":
    s = d.get("prompt", "")
    # The cockpit prepends a "## DESK STATE" situational frame to the agents it spawns; that frame
    # is internal plumbing, not a research action — skip it so it never clutters the desk tape (the
    # cockpit already posts the operator's clean question separately).
    if "## DESK STATE" in str(s):
        sys.exit(0)
elif kind == "tool":
    name = str(d.get("tool_name", "") or "")
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    if name.startswith("mcp__"):                       # book-relevant MCP call (existing behaviour)
        short = name.split("__")[-1]
        arg = ""
        for k in ("ticker", "key", "name", "overrides", "action", "change_id"):
            if ti.get(k):
                arg = f" {ti[k]}"
                break
        s, ev_kind = f"{short}{arg}", "tool"
    elif name == "Bash":                               # the operator's shell actions
        cmd = _redact(ti.get("command", "")).split("\n")[0].split("&&")[0].strip()
        if cmd.startswith("git "):
            ev_kind, s = "git", " ".join(cmd.split()[:4])      # "git commit -m …" -> "git commit -m"
        else:
            ev_kind, s = "ran", cmd[:80]
    elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        ev_kind = "edited"
        s = _relpath(ti.get("file_path") or ti.get("notebook_path") or "")
    else:
        sys.exit(0)                                    # Read/Grep/Glob/etc — too noisy for the tape
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
    payload = {"agent": agent, "kind": ev_kind, "summary": s}
else:
    sys.exit(0)
print(json.dumps(payload))
