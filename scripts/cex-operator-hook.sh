# Operator-action capture for the CommodityEx cockpit DESK TAPE (Forge nervous system #2).
#
# Sourced into the OPERATOR pane (only when CEX_OPERATOR_TAPE=1) by cockpit.sh. It posts each
# interactive command you run to the engine's /agent/activity as "you", so your terminal work flows
# into the dashboard's desk tape next to agent work and state events. Best-effort, silent, backgrounded
# — it never blocks the prompt. Works in bash and zsh.
#
# Manual use:  CEX_REPO=/path/to/repo CEX_ENGINE_URL=http://127.0.0.1:8000  source scripts/cex-operator-hook.sh

__cex_repo="${CEX_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd)}"
__cex_py="$__cex_repo/.venv/bin/python"
[ -x "$__cex_py" ] || __cex_py="$(command -v python3 || command -v python)"

__cex_tape() { [ -n "$1" ] && "$__cex_py" "$__cex_repo/cex_optape.py" "$1" >/dev/null 2>&1 & }

if [ -n "${ZSH_VERSION:-}" ]; then
  autoload -Uz add-zsh-hook 2>/dev/null
  __cex_precmd() { __cex_tape "$(fc -ln -1 2>/dev/null)"; }
  add-zsh-hook precmd __cex_precmd 2>/dev/null || precmd() { __cex_tape "$(fc -ln -1 2>/dev/null)"; }
elif [ -n "${BASH_VERSION:-}" ]; then
  __cex_prompt() { __cex_tape "$(history 1 | sed 's/^ *[0-9]* *//')"; }
  case "${PROMPT_COMMAND:-}" in
    *__cex_prompt*) ;;                                      # already wired — don't double-register
    *) PROMPT_COMMAND="__cex_prompt${PROMPT_COMMAND:+; $PROMPT_COMMAND}" ;;
  esac
fi
