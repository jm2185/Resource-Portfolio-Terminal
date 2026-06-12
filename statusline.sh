#!/bin/bash
#
# CommodityEx Claude Code statusline — your book, ambient in every prompt.
#
# Shows: ⛏ <branch> · <model> │ REGIME · MRI · top-pick   (live from the engine /state),
# or "engine offline" when :8000 isn't up. Fast (<0.5s, never blocks the prompt) and
# dependency-free — uses the macOS system python3, not the venv.
#
# Wire it in ~/.claude/settings.json:
#   { "statusLine": { "command": "/Users/joeymason/Macro/statusline.sh" } }
#
# Regime/MRI/top-pick plus the daily-brief per-name flag: a count of names BELOW their REP
# floor (the accumulate signal), shown as ⚑<n> — the Phase 12 daily_brief layer, ambient
# in every prompt.

PY=/usr/bin/python3
[ -x "$PY" ] || PY=python3

session_json="$(cat)"

# --- session bits (branch · short model) from Claude's stdin JSON ---
read -r BRANCH MODEL <<EOF
$(printf '%s' "$session_json" | "$PY" -c '
import sys, json
try: d = json.load(sys.stdin)
except Exception: d = {}
branch = d.get("branch") or d.get("gitBranch") or "main"
model = d.get("model") or ""
if isinstance(model, dict): model = model.get("id") or model.get("display_name") or ""
model = str(model).replace("claude-","").split("-2")[0][:14]
print(branch, model or "claude")
' 2>/dev/null)
EOF

# --- live book state from the engine ---
STATE="$(curl -sf --max-time 0.4 http://127.0.0.1:8000/state 2>/dev/null)"
if [ -n "$STATE" ]; then
  BOOK="$(printf '%s' "$STATE" | "$PY" -c '
import sys, json
try: d = json.load(sys.stdin)
except Exception: d = {}
conv = d.get("conviction_mode", {}) or {}
ctx  = conv.get("context", {}) or {}
regime = ctx.get("regime", "—")
mri = d.get("mri", ctx.get("mri", "—"))
try: mri = "%.0f" % float(mri)
except Exception: pass
top = conv.get("top_pick", "—")
# daily-brief per-name flag: how many names sit BELOW their REP floor (accumulate signal)
def _f(x):
    try: return float(x)
    except Exception: return None
below = 0
for b in (conv.get("baskets") or []):
    cov = _f(((b.get("pillars") or {}).get("V") or {}).get("floor_coverage"))
    if cov is not None and cov >= 1.0: below += 1
flag = f" · ⚑{below} below-floor" if below else ""
print(f"{regime} · MRI {mri} · top {top}{flag}")
' 2>/dev/null)"
else
  BOOK="engine offline"
fi

# ANSI: cyan branch, dim model, green/grey book
printf '⛏ \033[36m%s\033[0m \033[2m%s\033[0m │ %s' "${BRANCH:-main}" "${MODEL:-claude}" "${BOOK:-—}"
