cd ~/Macro

cat > launch-cockpit.sh << 'EOF'
#!/bin/zsh

# Explicit PATH for reliability
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Activate virtual environment
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
elif [ -f ~/.venv/bin/activate ]; then
  source ~/.venv/bin/activate
else
  echo "⚠️  Could not find virtual environment"
fi

# Check tmux
if ! command -v tmux >/dev/null 2>&1; then
  echo "❌ tmux not found. Install with: brew install tmux"
  read -p "Press Enter to exit..."
  exit 1
fi

# Create or attach to the financial cockpit
if ! tmux has-session -t financial 2>/dev/null; then
  echo "🚀 Creating new financial cockpit session..."

  tmux new-session -d -s financial -n DASHBOARD
  tmux send-keys -t financial:DASHBOARD 'python commodityex_tui.py' C-m

  tmux new-window -t financial -n AGENTS
  tmux send-keys -t financial:AGENTS 'claude' C-m

  tmux new-window -t financial -n OPS
fi

echo "✅ Attaching to financial cockpit..."
tmux attach -t financial
EOF

chmod +x launch-cockpit.sh