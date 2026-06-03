#!/bin/bash
#
# Double-click launcher (macOS / Finder): opens Terminal.app and attaches the
# persistent tmux cockpit (see cockpit.sh). Everything inside survives closing this
# window — re-run to re-attach exactly where you left off.
#
# Terminal users can skip this and just run:   ./cockpit.sh
# iTerm2 users: run ./cockpit.sh from iTerm2 for native split-pane integration (-CC).

REPO="$(cd "$(dirname "$0")" && pwd)"

osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "cd '$REPO' && ./cockpit.sh"
end tell
APPLESCRIPT
