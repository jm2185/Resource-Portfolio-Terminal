#!/usr/bin/env bash
#
# Cockpit agent-activity hook — stream what this Claude pane is doing into the CommodityEx
# cockpit's SIGNALS rail. Wired from .claude/settings.json on UserPromptSubmit / PostToolUse /
# Stop. The Claude Code event JSON arrives on stdin; _activity.py compacts it to a summary and
# this script POSTs it to the engine's /agent/activity (which rides terminal_state, so the
# dashboard shows it live).
#
# Deliberately unobtrusive: best-effort, backgrounded, short timeout, all errors swallowed — if
# the engine/cockpit isn't running the agent is never blocked or slowed.
#
# Disable any time: remove the "hooks" block from .claude/settings.json.

URL="${CEX_ENGINE_URL:-http://127.0.0.1:8000}"
KIND="${1:-note}"
AGENT="${CEX_AGENT_NAME:-claude}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$(command -v python3 || true)"; [ -z "$PY" ] && exit 0

# Event JSON flows from this script's stdin into the parser (which prints a payload, or nothing).
PAYLOAD="$("$PY" "$DIR/_activity.py" "$KIND" "$AGENT")" || exit 0
[ -z "$PAYLOAD" ] && exit 0

curl -s --max-time 0.6 -X POST "$URL/agent/activity" \
  -H 'Content-Type: application/json' -d "$PAYLOAD" >/dev/null 2>&1 &
exit 0
