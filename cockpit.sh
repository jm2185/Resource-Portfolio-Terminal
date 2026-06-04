#!/usr/bin/env bash
#
# CommodityEx Cockpit — one command boots your whole desk and keeps it alive.
#
# A single persistent tmux session, "commodityex", with everything you work in visible at
# once (the agents live natively as panes — no extra windows to babysit):
#
#   ┌─────────────────────────────────┬────────────┐
#   │                                 │ 🤖 CLAUDE  │
#   │   📟 DASHBOARD                  │            │
#   │   commodityex_tui.py            ├────────────┤
#   │   (the big screen you live in)  │ 🛰 ENGINE  │
#   │                                 ├────────────┤
#   │                                 │ 🛠 OPERATOR │
#   └─────────────────────────────────┴────────────┘
#
# Claude is the one interactive agent. Antigravity (Gemini) is used headlessly for research —
# the dashboard's `b` key red-teams the focused name via the web-auth'd `agy` CLI and saves the
# result. Want it as a live pane too? boot with --agy.
#
# Persistence is the point: engine, dashboard and the Claude session keep running when you
# detach (Ctrl-b d), close the window, or sleep the laptop. Re-run to drop back in instantly.
#
# USAGE
#   ./cockpit.sh                 boot it (first run) or re-attach (every run after) — fast
#   ./cockpit.sh rebuild         tear down and build a fresh session
#   ./cockpit.sh kill            stop everything (engine, dashboard, agents)
#   ./cockpit.sh install         symlink a short `cex` command onto your PATH
#   ./cockpit.sh --two-window    calmer layout: a dashboard window + a separate ops window
#   ./cockpit.sh --agy           also open Antigravity as a live pane (default: headless)
#   ./cockpit.sh --no-agents     just engine + dashboard + operator (skip Claude/agy)
#   ./cockpit.sh --no-attach     build only, don't attach (scripting / CI)
#
# CONFIG (env, all optional)
#   CEX_CLAUDE_CMD   command that launches Claude   (default: claude)
#   CEX_AGY_CMD      command that launches Antigravity (default: agy)
#   CEX_ENGINE_URL   engine base URL                (default: http://127.0.0.1:8000)
#
# Requires: tmux (brew install tmux).  Dashboard pane wants: pip install textual.
# iTerm2 users get native split-pane integration automatically (tmux -CC).

set -u

SESSION="commodityex"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="${CEX_ENGINE_URL:-http://127.0.0.1:8000}"
CLAUDE_BIN="${CEX_CLAUDE_CMD:-claude}"
AGY_BIN="${CEX_AGY_CMD:-agy}"

c_amber='\033[38;5;214m'; c_dim='\033[2m'; c_red='\033[31m'; c_grn='\033[32m'; c_off='\033[0m'
say()  { printf "%b\n" "$*"; }
die()  { printf "%b\n" "${c_red}✗ $*${c_off}" >&2; exit 1; }

# Launched from Finder / Automator (double-click) the PATH is minimal — make Homebrew/local
# tools (tmux, claude, agy, the venv's python) findable just like in a normal login shell.
for d in /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in *":$d:"*) ;; *) [ -d "$d" ] && PATH="$d:$PATH" ;; esac
done
export PATH

# --------------------------------------------------------------------------- subcommands / flags
LAYOUT="desk"; WITH_AGENTS=1; ATTACH=1; WITH_AGY="${CEX_WITH_AGY:-0}"
[ -n "${COCKPIT_NO_ATTACH:-}" ] && ATTACH=0
case "${1:-}" in
  kill|stop|down)    tmux kill-session -t "$SESSION" 2>/dev/null && say "${c_grn}✓ cockpit stopped${c_off}" || say "no cockpit running"; exit 0 ;;
  rebuild|fresh)     tmux kill-session -t "$SESSION" 2>/dev/null; say "${c_dim}rebuilding…${c_off}" ;;
  install)           # drop a short `cex` launcher onto PATH (prefer a dir already on PATH)
                     TARGET=""
                     for d in "/opt/homebrew/bin" "/usr/local/bin" "$HOME/.local/bin" "$HOME/bin"; do
                       case ":$PATH:" in *":$d:"*) [ -w "$d" ] && { TARGET="$d"; break; } ;; esac
                     done
                     [ -z "$TARGET" ] && { TARGET="$HOME/.local/bin"; mkdir -p "$TARGET"; }
                     ln -sf "$REPO/cockpit.sh" "$TARGET/cex" \
                       && say "${c_grn}✓ installed:${c_off} $TARGET/cex -> cockpit.sh" || die "could not write $TARGET"
                     case ":$PATH:" in
                       *":$TARGET:"*) say "you can now run:  ${c_amber}cex${c_off}" ;;
                       *) say "add this to your shell rc (~/.zshrc), reopen the shell, then run ${c_amber}cex${c_off}:\n  export PATH=\"$TARGET:\$PATH\"" ;;
                     esac
                     exit 0 ;;
  -h|--help|help)    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
for a in "$@"; do case "$a" in
  --two-window) LAYOUT="two" ;;
  --no-agents)  WITH_AGENTS=0 ;;
  --agy)        WITH_AGY=1 ;;        # opt-in: Antigravity as a live pane (default: headless via `b`)
  --no-attach)  ATTACH=0 ;;
esac; done

# --------------------------------------------------------------------------- preflight
command -v tmux >/dev/null 2>&1 || die "tmux not found — install it:  brew install tmux"
PYTHON="python"; [ -x "$REPO/.venv/bin/python" ] && PYTHON="$REPO/.venv/bin/python"
command -v "$PYTHON" >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || die "no python found"
# Non-fatal capability hints (printed once, only when something useful is missing).
"$PYTHON" -c "import textual" >/dev/null 2>&1 || \
  say "${c_dim}hint: dashboard pane needs textual →  pip install textual${c_off}"
if [ "$WITH_AGENTS" = 1 ]; then
  command -v "${CLAUDE_BIN%% *}" >/dev/null 2>&1 || say "${c_dim}hint: '${CLAUDE_BIN}' not on PATH (set CEX_CLAUDE_CMD, or it may be a shell alias)${c_off}"
  command -v "${AGY_BIN%% *}"    >/dev/null 2>&1 || say "${c_dim}hint: '${AGY_BIN}' not on PATH (set CEX_AGY_CMD, or it may be a shell alias)${c_off}"
fi

attach() {
  [ "$ATTACH" = 1 ] || { say "${c_grn}✓ session '$SESSION' ready${c_off} (not attaching)"; exit 0; }
  if [ -n "${TMUX:-}" ]; then              # already inside tmux — switch, don't nest (avoids the warning)
    tmux switch-client -t "$SESSION" 2>/dev/null || say "already in the cockpit (jump windows with Ctrl-b w)"
    exit 0
  fi
  if [ "${TERM_PROGRAM:-}" = "iTerm.app" ]; then exec tmux -CC attach -t "$SESSION"; else exec tmux attach -t "$SESSION"; fi
}

# Already up? Re-attach instantly — that's the persistence win.
tmux has-session -t "$SESSION" 2>/dev/null && attach

# --------------------------------------------------------------------------- pane command builders
V='[ -f .venv/bin/activate ] && source .venv/bin/activate; '
# A coloured banner the *pane's* shell renders (escapes stay as backslashes in the payload, so no
# raw ESC bytes are ever typed into an interactive readline pane).
hdr()  { printf "clear; printf '%%b\\n\\n' '%s';" "$1"; }
# Type a command line into a pane. Strips a trailing ';'/space first: tmux's lexer treats a
# trailing ';' as a command separator, which would otherwise swallow the Enter (C-m) keypress.
send() {
  local pane="$1" cmd="$2"
  while [ -n "$cmd" ] && { [ "${cmd: -1}" = ";" ] || [ "${cmd: -1}" = " " ]; }; do cmd="${cmd%?}"; done
  tmux send-keys -t "$pane" "$cmd" C-m
}

# Engine: reuse an already-running engine, else start it (so dashboard/statusline have /state).
ENGINE_CMD="$V $(hdr "${c_amber}🛰  ENGINE${c_off} ${c_dim}$URL/state${c_off}") \
  (curl -sf --max-time 1 $URL/state >/dev/null 2>&1 && echo 'already running ✓' && exec \$SHELL || python engine.py); exec \$SHELL"

OPERATOR_CMD="$V $(hdr "${c_amber}🛠  OPERATOR${c_off} ${c_dim}git · pip · ingestion · manual${c_off}")"

# Dashboard: wait (bounded) for the engine to answer before painting, so the first frame is live.
TUI_CMD="$V $(hdr "${c_amber}📟  DASHBOARD${c_off}") \
  printf 'waiting for engine'; for i in \$(seq 1 40); do curl -sf --max-time 1 $URL/state >/dev/null 2>&1 && break; printf '.'; sleep 0.5; done; echo; \
  python commodityex_tui.py || { echo; echo 'dashboard needs textual →  pip install textual'; exec \$SHELL; }"

# Agents live natively as panes; if the CLI exits you drop to a shell (↑ relaunches).
CLAUDE_CMD="$V $(hdr "${c_amber}🤖  CLAUDE${c_off} ${c_dim}@conviction-analyst · @catalyst-verifier · @data-integrity-auditor${c_off}") ${CLAUDE_BIN}; echo; echo '(claude exited — shell below)'; exec \$SHELL"
AGY_CMD="$V $(hdr "${c_amber}🪐  ANTIGRAVITY${c_off} ${c_dim}independent analyst / red-team${c_off}") ${AGY_BIN}; echo; echo '(agy exited — shell below)'; exec \$SHELL"

# --------------------------------------------------------------------------- build
say "${c_dim}building cockpit…${c_off}"
tmux new-session -d -s "$SESSION" -n desk -c "$REPO" -x 220 -y 50
tmux set -g  mouse on            2>/dev/null
tmux set -g  history-limit 50000 2>/dev/null
tmux set -g  pane-border-status top 2>/dev/null
tmux set -g  pane-border-format ' #{pane_title} ' 2>/dev/null
# --- native-feeling, macOS-style controls (so you rarely touch the Ctrl-b prefix) ---
tmux set -g  set-clipboard on    2>/dev/null   # yanks go to the macOS clipboard
tmux set -g  escape-time 0       2>/dev/null   # no Esc lag
tmux set -g  mode-keys emacs     2>/dev/null   # familiar text-editing keys in scrollback
# click a pane to focus it; trackpad scroll works (mouse on). Option(⌥)+Arrow jumps panes — no prefix:
tmux bind -n M-Left  select-pane -L 2>/dev/null
tmux bind -n M-Right select-pane -R 2>/dev/null
tmux bind -n M-Up    select-pane -U 2>/dev/null
tmux bind -n M-Down  select-pane -D 2>/dev/null
# drag-select with the trackpad copies straight to the macOS clipboard
tmux bind -T copy-mode    MouseDragEnd1Pane send -X copy-pipe-and-cancel "pbcopy" 2>/dev/null
tmux bind -T copy-mode-vi MouseDragEnd1Pane send -X copy-pipe-and-cancel "pbcopy" 2>/dev/null

label() { tmux select-pane -t "$1" -T "$2" 2>/dev/null; }

if [ "$LAYOUT" = "two" ]; then
  # --- calmer two-window layout (dashboard window + ops window) ---
  DASH=$(tmux display -t "$SESSION:desk" -p '#{pane_id}'); label "$DASH" "📟 DASHBOARD"
  send "$DASH" "$TUI_CMD"
  if [ "$WITH_AGENTS" = 1 ]; then
    CLA=$(tmux split-window -h -t "$DASH" -c "$REPO" -P -F '#{pane_id}'); label "$CLA" "🤖 CLAUDE"
    send "$CLA" "$CLAUDE_CMD"
    if [ "$WITH_AGY" = 1 ]; then
      AGY=$(tmux split-window -v -t "$CLA" -c "$REPO" -P -F '#{pane_id}'); label "$AGY" "🪐 ANTIGRAVITY"
      send "$AGY" "$AGY_CMD"
    fi
    tmux resize-pane -t "$DASH" -x 74% 2>/dev/null
  fi
  tmux new-window -t "$SESSION" -n ops -c "$REPO"
  ENG=$(tmux display -t "$SESSION:ops" -p '#{pane_id}'); label "$ENG" "🛰 ENGINE"
  send "$ENG" "$ENGINE_CMD"
  OPR=$(tmux split-window -v -t "$ENG" -c "$REPO" -P -F '#{pane_id}'); label "$OPR" "🛠 OPERATOR"
  send "$OPR" "$OPERATOR_CMD"
  tmux resize-pane -t "$OPR" -y 10 2>/dev/null
  tmux select-window -t "$SESSION:desk"
else
  # --- single-window trading desk: a big dashboard, with agents + control as a thin VERTICAL
  #     stack down the right edge (Claude tall, engine/operator as short strips beneath) ---
  DASH=$(tmux display -t "$SESSION:desk" -p '#{pane_id}'); label "$DASH" "📟 DASHBOARD"
  send "$DASH" "$TUI_CMD"
  # narrow right column; everything in it is stacked vertically
  RIGHT=$(tmux split-window -h -t "$DASH" -c "$REPO" -P -F '#{pane_id}')
  if [ "$WITH_AGENTS" = 1 ]; then
    label "$RIGHT" "🤖 CLAUDE"; send "$RIGHT" "$CLAUDE_CMD"
    if [ "$WITH_AGY" = 1 ]; then
      AGY=$(tmux split-window -v -t "$RIGHT" -c "$REPO" -P -F '#{pane_id}'); label "$AGY" "🪐 ANTIGRAVITY"
      send "$AGY" "$AGY_CMD"
      ENG=$(tmux split-window -v -t "$AGY" -c "$REPO" -P -F '#{pane_id}')
    else
      ENG=$(tmux split-window -v -t "$RIGHT" -c "$REPO" -P -F '#{pane_id}')
    fi
  else
    ENG="$RIGHT"
  fi
  label "$ENG" "🛰 ENGINE"; send "$ENG" "$ENGINE_CMD"
  OPR=$(tmux split-window -v -t "$ENG" -c "$REPO" -P -F '#{pane_id}'); label "$OPR" "🛠 OPERATOR"
  send "$OPR" "$OPERATOR_CMD"
  # proportions: a big dashboard (≈76% wide); engine + operator are short strips so Claude stays tall
  tmux resize-pane -t "$DASH" -x 76% 2>/dev/null
  tmux resize-pane -t "$ENG" -y 8 2>/dev/null
  tmux resize-pane -t "$OPR" -y 7 2>/dev/null
  tmux select-pane -t "$DASH"
fi

attach
