#!/bin/bash
#
# CommodityEx "cockpit" launcher (macOS / Terminal.app).
# Opens three Terminal windows in the repo root with the venv activated:
#
#   1) OPERATOR  — plain shell for `git pull`, pip, and manual commands
#   2) CLAUDE    — the Claude Code CLI (`claude`) wired to the commodity-ex MCP server
#   3) ANTIGRAVITY — the Antigravity CLI (`agy`)  wired to the commodity-ex MCP server
#
# Usage:
#   chmod +x start-cockpit.command      # once
#   double-click it in Finder           # or:  ./start-cockpit.command
#
# Auto-start at login:
#   System Settings → General → Login Items → "+" → choose this file.
#
# Portable: it resolves its own folder, so it works no matter where the repo lives
# or what it's named. (The Claude *desktop/web* app is opened separately — it isn't
# a terminal window.)

REPO="$(cd "$(dirname "$0")" && pwd)"

osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "cd '$REPO' && source .venv/bin/activate && clear && echo '🛠  OPERATOR  —  git pull · pip · manual commands'"
  do script "cd '$REPO' && source .venv/bin/activate && clear && echo '🤖 CLAUDE CLI (Max plan) — starting…' && claude"
  do script "cd '$REPO' && source .venv/bin/activate && clear && echo '🪐 ANTIGRAVITY CLI (agy) — starting…' && agy"
end tell
APPLESCRIPT
