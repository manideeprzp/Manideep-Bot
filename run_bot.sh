#!/bin/bash
#
# Run bot + auto-watcher together
#
# This script starts both the Slack bot and the auto-watcher
# in the background so you only need one command.
#
# Usage:
#   ./run_bot.sh          # Start both in foreground
#   ./run_bot.sh daemon   # Start both in background

set -e

cd "$(dirname "$0")"

# Create logs directory
mkdir -p logs

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

if [ "$1" = "daemon" ]; then
    echo "🚀 Starting bot + auto-watcher in background..."

    # Start bot
    nohup python -m manideep_bot.app > logs/bot.log 2>&1 &
    BOT_PID=$!
    echo $BOT_PID > logs/bot.pid
    echo "✅ Bot started (PID: $BOT_PID)"

    # Start auto-watcher
    nohup python scripts/auto_watcher.py > logs/auto_watcher.log 2>&1 &
    WATCHER_PID=$!
    echo $WATCHER_PID > logs/auto_watcher.pid
    echo "✅ Auto-watcher started (PID: $WATCHER_PID)"

    echo ""
    echo "📋 View logs:"
    echo "   Bot:          tail -f logs/bot.log"
    echo "   Auto-watcher: tail -f logs/auto_watcher.log"
    echo ""
    echo "🛑 Stop both:"
    echo "   kill \$(cat logs/bot.pid) \$(cat logs/auto_watcher.pid)"
else
    echo "🚀 Starting bot + auto-watcher..."
    echo ""
    echo "This will run both processes. Press Ctrl+C to stop."
    echo ""

    # Trap Ctrl+C to kill both processes
    trap 'kill $BOT_PID $WATCHER_PID 2>/dev/null; wait; echo ""; echo "🛑 Stopped"; exit' INT TERM

    # Start bot in background
    python -m manideep_bot.app 2>&1 | sed 's/^/[BOT] /' &
    BOT_PID=$!

    # Start auto-watcher in background
    python scripts/auto_watcher.py 2>&1 | sed 's/^/[WATCHER] /' &
    WATCHER_PID=$!

    # Wait for both
    wait
fi
