cd ~/Macro

cat > launch-cockpit.sh << 'EOF'
#!/bin/zsh

X Full explicit PATH to handle Automator / .app launches
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Activate venv
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
elif [ -f ~/.venv/bin/activate ]; then
  source ~/.venv/bin/activate
else
  echo "Warning: Could not find virtual environment"
fi

# Check for tmux and start the session
if ! command -v tmux >/dev/null 2>&1; then
  echo "Error: tmux is not installed or not in PATH."
  echo "Install with: brew install tmux"
  read -p "Press Enter to exit..."
  exit 1
fi

# Create or attach to financial session
tmux has-session -t financial 2>/dev/null

if [ $? != 0 ]; then
  echo "Creating new financial cockpit session..."

  tmux new-session -d -s financial -n DASHBOARD
  tmux send-keys -t financial:DASHBOARD 'python commodityex_tui.py' C-m

  tmux new-window -t financial -n AGENTS
  tmux send-keys -t financial:AGENTS 'claude' C-m

  tmux new-window -t financial -n OPS

  tmux select-window -t financial:DASHBOARD
fi

echo "Attaching to financial cockpit..."
tmux attach -t financial
EOF

chmod +x launch-cockpit.sh