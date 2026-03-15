#!/bin/bash
#
# Run the auto-watcher in the background
#
# This script starts the automatic ticket analyzer that watches
# the analysis queue and analyzes new tickets as they arrive.
#
# Usage:
#   ./scripts/run_auto_watcher.sh          # Start in foreground
#   ./scripts/run_auto_watcher.sh daemon   # Start in background

set -e

cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

if [ "$1" = "daemon" ]; then
    echo "🚀 Starting auto-watcher in background..."
    nohup python scripts/auto_watcher.py > logs/auto_watcher.log 2>&1 &
    PID=$!
    echo $PID > logs/auto_watcher.pid
    echo "✅ Auto-watcher started (PID: $PID)"
    echo "📋 Logs: tail -f logs/auto_watcher.log"
    echo "🛑 Stop: kill $(cat logs/auto_watcher.pid)"
else
    echo "🚀 Starting auto-watcher..."
    python scripts/auto_watcher.py
fi
