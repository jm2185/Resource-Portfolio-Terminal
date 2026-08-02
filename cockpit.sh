#!/usr/bin/env bash
#
# CommodityEx Cockpit — one command boots your whole desk and keeps it alive.
#
# A single persistent tmux session, "commodityex". The DEFAULT layout ("focus") gives the dashboard
# a FULL-SCREEN window — the reorg's in-dashboard AGENT COLUMN mirrors the agents, so the panes no
# longer need permanent real estate — and puts Claude / Operator on a second window
# you flip to instantly (⌥2, or Ctrl-b 2):
#
#   window 1 · desk                     window 2 · agents
#   ┌──────────────────────────────┐    ┌──────────────────────────────┐
#   │                              │    │ 🤖 CLAUDE                     │
#   │  📟 DASHBOARD (FULL SCREEN)  │ ⌥2 ├──────────────────────────────┤
#   │  commodityex_tui.py          │───►│ 🛠 OPERATOR (.venv)           │
#   │  ← the AGENT COLUMN is inside│    │                              │
#   └──────────────────────────────┘    └──────────────────────────────┘
#
# Prefer the agents always on-screen? `./cockpit.sh --desk` keeps the legacy single-window layout
# (dashboard ≈76% + a Claude / Operator stack down the right edge).
#
# The ENGINE runs OFF-pane as a hidden background daemon (logs to data/engine.log) — it persists
# across detach/close, and `./cockpit.sh kill` stops it. The whole fleet runs on Claude — the
# dashboard's `b` key red-teams the focused name via @bear (the Gemini/agy lane is retired).
#
# Persistence is the point: engine, dashboard and the Claude session keep running when you
# detach (Ctrl-b d), close the window, or sleep the laptop. Re-run to drop back in instantly.
#
# USAGE
#   ./cockpit.sh                 boot it (first run) or re-attach (every run after) — fast
#   ./cockpit.sh rebuild         tear down and build a fresh session
#   ./cockpit.sh kill            stop everything (engine, dashboard, agents)
#   ./cockpit.sh install         symlink a short `cex` command onto your PATH
#   ./cockpit.sh --focus         DEFAULT: dashboard full-screen window + agents on window 2 (⌥1/⌥2)
#   ./cockpit.sh --desk          legacy single-window: dashboard ≈76% + agent/operator right stack
#   ./cockpit.sh --two-window    a dashboard+agent window + a separate ops window
#   ./cockpit.sh --no-agents     just dashboard + operator (skip the Claude pane)
#   ./cockpit.sh --no-attach     build only, don't attach (scripting / CI)
#
# CONFIG (env, all optional)
#   CEX_CLAUDE_CMD       command that launches Claude       (default: claude)
#   CEX_ENGINE_URL       engine base URL                    (default: http://127.0.0.1:8000)
#   CEX_OPERATOR_TAPE=1  stream operator-pane commands onto the dashboard DESK TAPE (off by default)
#   CEX_MATRIX_HOST      LED panel host/IP (e.g. 192.168.250.32) — set to run the matrix display node
#   CEX_MATRIX_SELF_LOOP=1  matrix node uses device-autonomous rotation (default: host-driven)
#
# Requires: tmux (brew install tmux).  Dashboard pane wants: pip install textual.
# iTerm2 users get native split-pane integration automatically (tmux -CC).

set -u

SESSION="commodityex"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="${CEX_ENGINE_URL:-http://127.0.0.1:8000}"
CLAUDE_BIN="${CEX_CLAUDE_CMD:-claude}"

c_amber='\033[38;5;214m'; c_dim='\033[2m'; c_red='\033[31m'; c_grn='\033[32m'; c_off='\033[0m'
say()  { printf "%b\n" "$*"; }
die()  { printf "%b\n" "${c_red}✗ $*${c_off}" >&2; exit 1; }

# Launched from Finder / Automator (double-click) the PATH is minimal — make Homebrew/local
# tools (tmux, claude, the venv's python) findable just like in a normal login shell.
for d in /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in *":$d:"*) ;; *) [ -d "$d" ] && PATH="$d:$PATH" ;; esac
done
export PATH

# --------------------------------------------------------------------------- subcommands / flags
LAYOUT="focus"; WITH_AGENTS=1; ATTACH=1
[ -n "${COCKPIT_NO_ATTACH:-}" ] && ATTACH=0
case "${1:-}" in
  kill|stop|down)    tmux kill-session -t "$SESSION" 2>/dev/null && say "${c_grn}✓ cockpit stopped${c_off}" || say "no cockpit running"
                     if [ -f "$REPO/data/engine.pid" ]; then
                       kill "$(cat "$REPO/data/engine.pid" 2>/dev/null)" 2>/dev/null && say "${c_grn}✓ engine stopped${c_off}"
                       rm -f "$REPO/data/engine.pid"
                     fi
                     if [ -f "$REPO/data/matrix.pid" ]; then
                       kill "$(cat "$REPO/data/matrix.pid" 2>/dev/null)" 2>/dev/null && say "${c_grn}✓ matrix node stopped${c_off}"
                       rm -f "$REPO/data/matrix.pid"
                     fi
                     exit 0 ;;
  restart|redeploy)  # clean redeploy: kill the engine (a running process never reloads pulled code)
                     # then fall through to relaunch on the fresh checkout.
                     say "${c_dim}restarting on fresh code…${c_off}"
                     tmux kill-session -t "$SESSION" 2>/dev/null
                     [ -f "$REPO/data/engine.pid" ] && kill "$(cat "$REPO/data/engine.pid" 2>/dev/null)" 2>/dev/null
                     pkill -f 'engine\.py' 2>/dev/null
                     rm -f "$REPO/data/engine.pid" "$REPO/data/engine.sha"
                     if [ -f "$REPO/data/matrix.pid" ]; then
                       kill "$(cat "$REPO/data/matrix.pid" 2>/dev/null)" 2>/dev/null; rm -f "$REPO/data/matrix.pid"
                     fi
                     sleep 1
                     say "${c_grn}✓ stopped — relaunching${c_off}" ;;
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
  dash|dashboard)    # the visual glance cockpit — a browser page the engine serves at /dashboard
                     if ! curl -sf --max-time 1 "$URL/state" >/dev/null 2>&1; then
                       say "${c_dim}engine not up — start the cockpit first (./cockpit.sh)${c_off}"; exit 1
                     fi
                     say "${c_grn}✓ opening${c_off} $URL/dashboard"
                     if command -v open >/dev/null 2>&1; then open "$URL/dashboard"
                     elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL/dashboard"
                     else say "open $URL/dashboard in a browser"; fi
                     exit 0 ;;
  -h|--help|help)    sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
for a in "$@"; do case "$a" in
  --focus)      LAYOUT="focus" ;;    # default: dashboard full-screen window + agents on window 2
  --desk)       LAYOUT="desk" ;;     # legacy single-window right-stack
  --two-window) LAYOUT="two" ;;
  --no-agents)  WITH_AGENTS=0 ;;
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

# Engine: a hidden BACKGROUND DAEMON (no pane). Reuse an already-running one, else launch it
# detached (nohup) so it survives detach / window-close; logs to data/engine.log, pid to
# data/engine.pid (so `kill` can stop it). The dashboard waits (below) for /state before painting.
start_engine() {
  mkdir -p "$REPO/data"
  local head_sha; head_sha="$(cd "$REPO" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if curl -sf --max-time 1 "$URL/state" >/dev/null 2>&1; then
    # A running process does NOT reload edited/pulled files. If the live engine was started on an
    # older commit than the checkout, say so LOUDLY — this is the "restarted the UI, not the engine"
    # footgun that left stale prices reading as live.
    local run_sha; run_sha="$(cat "$REPO/data/engine.sha" 2>/dev/null || echo unknown)"
    if [ "$head_sha" != "unknown" ] && [ "$run_sha" != "$head_sha" ]; then
      say "${c_amber}⚠  engine is running OLDER code (${run_sha}) than the checkout (${head_sha}) — a running process never reloads files. Run  ./cockpit.sh restart  to apply.${c_off}"
    else
      say "${c_dim}🛰  engine already running ✓ (${run_sha}) — $URL${c_off}"
    fi
    return 0
  fi
  ( cd "$REPO" && exec nohup "$PYTHON" engine.py >> "$REPO/data/engine.log" 2>&1 ) &
  echo $! > "$REPO/data/engine.pid"
  echo "$head_sha" > "$REPO/data/engine.sha"
  say "${c_dim}🛰  engine started (${head_sha}, background daemon) → data/engine.log${c_off}"
  say "${c_dim}📊 glance cockpit → ${c_off}${c_amber}$URL/dashboard${c_off}${c_dim}  (or: ./cockpit.sh dash)${c_off}"
}

# Matrix display node: OPT-IN background daemon (only when CEX_MATRIX_HOST is set) that renders engine
# state to the LED panel. Logs to data/matrix.log, pid to data/matrix.pid (so `kill` stops it).
start_matrix() {
  [ -n "${CEX_MATRIX_HOST:-}" ] || return 0
  if [ -f "$REPO/data/matrix.pid" ] && kill -0 "$(cat "$REPO/data/matrix.pid" 2>/dev/null)" 2>/dev/null; then
    say "${c_dim}📟 matrix node already running ✓ → ${CEX_MATRIX_HOST}${c_off}"; return 0
  fi
  local loop=""; [ "${CEX_MATRIX_SELF_LOOP:-0}" = 1 ] && loop="--self-loop"
  ( cd "$REPO" && exec nohup "$PYTHON" -m matrix --host "$CEX_MATRIX_HOST" $loop >> "$REPO/data/matrix.log" 2>&1 ) &
  echo $! > "$REPO/data/matrix.pid"
  say "${c_dim}📟 matrix node started → ${CEX_MATRIX_HOST} (data/matrix.log)${c_off}"
}

# Operator pane: optionally wire the desk-tape capture hook (opt-in: CEX_OPERATOR_TAPE=1) so the
# commands you run here flow into the dashboard's DESK TAPE as "you" (Forge nervous system #2).
OP_TAPE=""
[ "${CEX_OPERATOR_TAPE:-0}" = 1 ] && OP_TAPE="export CEX_REPO='$REPO' CEX_ENGINE_URL='$URL'; . '$REPO/scripts/cex-operator-hook.sh'; "
OPERATOR_CMD="$V ${OP_TAPE}$(hdr "${c_amber}🛠  OPERATOR${c_off} ${c_dim}git · pip · ingestion · manual (.venv)${c_off}")"

# Dashboard: wait (bounded) for the engine to answer before painting, so the first frame is live.
TUI_CMD="$V $(hdr "${c_amber}📟  DASHBOARD${c_off}") \
  printf 'waiting for engine'; for i in \$(seq 1 40); do curl -sf --max-time 1 $URL/state >/dev/null 2>&1 && break; printf '.'; sleep 0.5; done; echo; \
  python commodityex_tui.py || { echo; echo 'dashboard needs textual →  pip install textual'; exec \$SHELL; }"

# The Claude agent lives natively as a pane; if the CLI exits you drop to a shell (↑ relaunches).
CLAUDE_CMD="$V $(hdr "${c_amber}🤖  CLAUDE${c_off} ${c_dim}@conviction-analyst · @catalyst-verifier · @data-integrity-auditor${c_off}") ${CLAUDE_BIN}; echo; echo '(claude exited — shell below)'; exec \$SHELL"

# --------------------------------------------------------------------------- build
start_engine                       # hidden engine daemon first, so the dashboard has /state to paint
start_matrix                       # optional LED panel node (only if CEX_MATRIX_HOST is set)
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
# copy is native-feeling: drag = selection, double-click = word, triple-click = line — all to the
# macOS clipboard (pbcopy). To select with the terminal's OWN native selection instead (bypassing
# tmux entirely), hold Option(⌥) and drag in Terminal.app (or Cmd in iTerm2). Cmd+V pastes natively.
tmux bind -T copy-mode    MouseDragEnd1Pane send -X copy-pipe-and-cancel "pbcopy" 2>/dev/null
tmux bind -T copy-mode-vi MouseDragEnd1Pane send -X copy-pipe-and-cancel "pbcopy" 2>/dev/null
# Paste the macOS clipboard into any pane: ⌥V (no prefix) or Ctrl-b v. Cmd+V also works natively
# (iTerm2 with tmux -CC gives native Cmd+C/Cmd+V; in Terminal.app, ⌥-drag selects natively).
tmux bind -n M-v run -b "pbpaste 2>/dev/null | tmux load-buffer - 2>/dev/null && tmux paste-buffer -p" 2>/dev/null
tmux bind    v   run -b "pbpaste 2>/dev/null | tmux load-buffer - 2>/dev/null && tmux paste-buffer -p" 2>/dev/null
# ⌥O / ø — ops shell popup: activates .venv, prints close hint, starts interactive shell.
# Binds M-o (iTerm2 / Terminal.app with meta ON) and ø (Terminal.app default, Option+O without meta).
# Falls back to new-window for tmux < 3.2 (no display-popup).
_OPS_CMD="printf \"\033[2m  ops shell -- Ctrl-D or exit to close -- .venv active\033[0m\n\n\"; [ -f .venv/bin/activate ] && . .venv/bin/activate; exec $SHELL"
tmux bind -n M-o run-shell "tmux display-popup -w 82% -h 70% -E -d '$REPO' '$SHELL' -c '$_OPS_CMD' 2>/dev/null || tmux new-window -n ops -c '$REPO'" 2>/dev/null
tmux bind -n 'ø'  run-shell "tmux display-popup -w 82% -h 70% -E -d '$REPO' '$SHELL' -c '$_OPS_CMD' 2>/dev/null || tmux new-window -n ops -c '$REPO'" 2>/dev/null
# ⌥R — hot-restart the focused pane (respawn with the same original command; tmux's hot-reload)
tmux bind -n M-r respawn-pane -k 2>/dev/null
tmux bind -n DoubleClick1Pane copy-mode -M \; send -X select-word \; send -X copy-pipe-no-clear "pbcopy" 2>/dev/null
tmux bind -n TripleClick1Pane copy-mode -M \; send -X select-line \; send -X copy-pipe-no-clear "pbcopy" 2>/dev/null
tmux bind -T copy-mode    y send -X copy-pipe-and-cancel "pbcopy" 2>/dev/null
tmux bind -T copy-mode-vi y send -X copy-pipe-and-cancel "pbcopy" 2>/dev/null
# Ctrl-b m toggles mouse mode off/on — flip it OFF for 100% native terminal select/copy on the shells
tmux bind m set -g mouse \; display-message "mouse #{?mouse,ON (tmux select),OFF (native select)}" 2>/dev/null

label() { tmux select-pane -t "$1" -T "$2" 2>/dev/null; }

if [ "$LAYOUT" = "focus" ]; then
  # --- DEFAULT: the dashboard owns a FULL-SCREEN window. Its in-dashboard AGENT COLUMN mirrors the
  #     agents (in-flight runs, proposals, desk tape, memory), so the panes no longer need permanent
  #     real estate — Claude / Operator move to a second window you flip to with ⌥2
  #     (or Ctrl-b 2). The a/b/x dispatch keys still reach the agent pane across windows. ---
  DASH=$(tmux display -t "$SESSION:desk" -p '#{pane_id}'); label "$DASH" "📟 DASHBOARD"
  send "$DASH" "$TUI_CMD"                                  # no split — full width & height
  if [ "$WITH_AGENTS" = 1 ]; then
    tmux new-window -t "$SESSION" -n agents -c "$REPO"
    CLA=$(tmux display -t "$SESSION:agents" -p '#{pane_id}'); label "$CLA" "🤖 CLAUDE"
    send "$CLA" "$CLAUDE_CMD"
    OPR=$(tmux split-window -v -t "$CLA" -c "$REPO" -P -F '#{pane_id}'); label "$OPR" "🛠 OPERATOR"
    send "$OPR" "$OPERATOR_CMD"
    tmux select-layout -t "$SESSION:agents" even-vertical 2>/dev/null
  else
    tmux new-window -t "$SESSION" -n ops -c "$REPO"        # ops = operator shell (engine is a daemon)
    OPR=$(tmux display -t "$SESSION:ops" -p '#{pane_id}'); label "$OPR" "🛠 OPERATOR"
    send "$OPR" "$OPERATOR_CMD"
  fi
  # prefix-less window flips (⌥1 desk · ⌥2 / ⌥` the other). ⌥O ops-shell popup is bound globally.
  tmux bind -n M-1 select-window -t "$SESSION:desk"  2>/dev/null
  tmux bind -n M-2 last-window                       2>/dev/null
  tmux bind -n 'M-`' last-window                     2>/dev/null
  tmux select-window -t "$SESSION:desk"
elif [ "$LAYOUT" = "two" ]; then
  # --- calmer two-window layout: a dashboard window (+ the Claude pane) and a separate ops window ---
  DASH=$(tmux display -t "$SESSION:desk" -p '#{pane_id}'); label "$DASH" "📟 DASHBOARD"
  send "$DASH" "$TUI_CMD"
  if [ "$WITH_AGENTS" = 1 ]; then
    CLA=$(tmux split-window -h -t "$DASH" -c "$REPO" -P -F '#{pane_id}'); label "$CLA" "🤖 CLAUDE"
    send "$CLA" "$CLAUDE_CMD"
    tmux resize-pane -t "$DASH" -x 74% 2>/dev/null
  fi
  tmux new-window -t "$SESSION" -n ops -c "$REPO"        # ops = operator shell (engine is a daemon)
  OPR=$(tmux display -t "$SESSION:ops" -p '#{pane_id}'); label "$OPR" "🛠 OPERATOR"
  send "$OPR" "$OPERATOR_CMD"
  tmux select-window -t "$SESSION:desk"
else
  # --- single-window trading desk: a big FULL-HEIGHT dashboard, with the Claude agent + the operator
  #     as a thin VERTICAL stack down the right edge — Claude tall, Operator a short strip. The
  #     engine runs off-pane as a daemon, so it no longer steals a slot. ---
  DASH=$(tmux display -t "$SESSION:desk" -p '#{pane_id}'); label "$DASH" "📟 DASHBOARD"
  send "$DASH" "$TUI_CMD"
  RIGHT=$(tmux split-window -h -t "$DASH" -c "$REPO" -P -F '#{pane_id}')    # narrow right column
  if [ "$WITH_AGENTS" = 1 ]; then
    label "$RIGHT" "🤖 CLAUDE"; send "$RIGHT" "$CLAUDE_CMD"
    OPR=$(tmux split-window -v -t "$RIGHT" -c "$REPO" -P -F '#{pane_id}'); label "$OPR" "🛠 OPERATOR"
    send "$OPR" "$OPERATOR_CMD"
  else
    OPR="$RIGHT"; label "$OPR" "🛠 OPERATOR"; send "$OPR" "$OPERATOR_CMD"
  fi
  # proportions: a big dashboard (≈76% wide, FULL height); operator is a short strip at the bottom
  tmux resize-pane -t "$DASH" -x 76% 2>/dev/null
  tmux resize-pane -t "$OPR" -y 7 2>/dev/null
  tmux select-pane -t "$DASH"
fi

attach
