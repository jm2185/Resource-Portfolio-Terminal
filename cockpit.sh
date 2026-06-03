#!/bin/bash
#
# CommodityEx tmux cockpit (Tier 0).
#
# One persistent tmux session, "commodityex", with two windows:
#   [1] cockpit : live TUI dashboard (left) · Claude CLI (top-right) · Antigravity agy (bottom-right)
#   [2] ops     : the engine (serves /state) · an operator shell (git/pip/manual)
#
# Persistence is the point: the engine, dashboard and your agent sessions keep
# running when you detach or close the window. Re-attach any time with the same
# command and the whole cockpit is exactly as you left it.
#
# Usage:
#   ./cockpit.sh                 # build (first run) or re-attach
#   COCKPIT_NO_ATTACH=1 ./cockpit.sh   # build only, don't attach (scripting/CI)
#   tmux kill-session -t commodityex   # tear it down
#
# iTerm2 users get native integration automatically (tmux -CC). Terminal.app users
# get plain tmux (enable the mouse to click panes — this script turns it on).
# Requires: tmux (brew install tmux). The TUI pane wants: pip install textual.

SESSION="commodityex"
REPO="$(cd "$(dirname "$0")" && pwd)"

command -v tmux >/dev/null 2>&1 || { echo "tmux not found — install it:  brew install tmux"; exit 1; }

attach_cockpit() {
  [ -n "${COCKPIT_NO_ATTACH:-}" ] && { echo "session '$SESSION' ready (not attaching; COCKPIT_NO_ATTACH set)"; exit 0; }
  if [ "${TERM_PROGRAM:-}" = "iTerm.app" ]; then exec tmux -CC attach -t "$SESSION"; else exec tmux attach -t "$SESSION"; fi
}

# Already running? Just re-attach — that's the persistence win.
if tmux has-session -t "$SESSION" 2>/dev/null; then attach_cockpit; fi

# Activate the venv inside each pane if present (no-op otherwise).
V='[ -f .venv/bin/activate ] && source .venv/bin/activate; '

# Engine: re-use an already-running engine, else start it (so the TUI/statusline have /state).
ENGINE="$V clear && echo '🛰  ENGINE — http://127.0.0.1:8000/state' && (curl -sf --max-time 1 http://127.0.0.1:8000/state >/dev/null 2>&1 && echo 'already running ✓' && exec \$SHELL || python engine.py)"
OPERATOR="$V clear && echo '🛠  OPERATOR — git pull · pip · manual commands'"
TUI="$V clear && (python commodityex_tui.py || { echo; echo 'TUI needs textual:  pip install textual'; exec \$SHELL; })"
CLAUDE="$V clear && echo '🤖 CLAUDE — invoke agents on demand: @agent-conviction-analyst · @agent-catalyst-verifier · @agent-data-integrity-auditor' && (claude || true); exec \$SHELL"
AGY="$V clear && echo '🪐 ANTIGRAVITY (agy) — independent analyst / red-team' && (agy || true); exec \$SHELL"

# --- Window 2: ops (engine + operator) ---
tmux new-session -d -s "$SESSION" -n ops -c "$REPO"
# Server-wide quality-of-life (set once the server/session exists): click-to-focus + scrollback.
tmux set -g mouse on 2>/dev/null
tmux set -g history-limit 20000 2>/dev/null
tmux send-keys  -t "$SESSION:ops" "$ENGINE" C-m
tmux split-window -v -t "$SESSION:ops" -c "$REPO"
tmux send-keys  -t "$SESSION:ops" "$OPERATOR" C-m
tmux resize-pane -t "$SESSION:ops.1" -y 8 2>/dev/null   # small operator strip under the engine log

# --- Window 1: cockpit (TUI + claude + agy) ---
tmux new-window -t "$SESSION" -n cockpit -c "$REPO"
tmux send-keys  -t "$SESSION:cockpit" "$TUI" C-m
tmux split-window -h -t "$SESSION:cockpit" -c "$REPO"
tmux send-keys  -t "$SESSION:cockpit" "$CLAUDE" C-m
tmux split-window -v -t "$SESSION:cockpit" -c "$REPO"
tmux send-keys  -t "$SESSION:cockpit" "$AGY" C-m
tmux select-layout -t "$SESSION:cockpit" main-vertical   # big TUI on the left, claude/agy stacked right
tmux select-pane   -t "$SESSION:cockpit.1"               # land in the Claude pane

tmux select-window -t "$SESSION:cockpit"
attach_cockpit
