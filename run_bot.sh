#!/bin/bash
#
# Run bot only (auto-watcher disabled — Claude scheduled task handles analysis)
#
# Analysis of claude_requests/ is now handled by the Claude scheduled task
# (runs every 10 min, Mon-Fri 10am-6pm). auto_watcher.py is intentionally
# NOT started here to avoid race conditions with the Claude analysis.
#
# Usage:
#   ./run_bot.sh          # Start bot in foreground
#   ./run_bot.sh daemon   # Start bot in background

set -e

cd "$(dirname "$0")"

# Create logs directory
mkdir -p logs

# Activate virtual environment and resolve python binary
if [ -d ".venv" ]; then
    source .venv/bin/activate
    PYTHON=".venv/bin/python3"
    # Install package if not already installed
    if ! .venv/bin/python3 -c "import manideep_bot" 2>/dev/null; then
        echo "📦 Installing manideep_bot package..."
        .venv/bin/python3 -m pip install -e . -q
    fi
elif [ -d "venv" ]; then
    source venv/bin/activate
    PYTHON="venv/bin/python3"
    if ! venv/bin/python3 -c "import manideep_bot" 2>/dev/null; then
        echo "📦 Installing manideep_bot package..."
        venv/bin/python3 -m pip install -e . -q
    fi
else
    PYTHON=$(command -v python3 || command -v python || echo "python3")
fi

if [ "$1" = "daemon" ]; then
    echo "🚀 Starting bot in background..."

    # Start bot
    nohup $PYTHON -m manideep_bot.app > logs/bot.log 2>&1 &
    BOT_PID=$!
    echo $BOT_PID > logs/bot.pid
    echo "✅ Bot started (PID: $BOT_PID)"
    echo "ℹ️  Analysis handled by Claude scheduled task (every 10 min, Mon-Fri 10am-6pm)"

    echo ""
    echo "📋 View logs:"
    echo "   Bot: tail -f logs/bot.log"
    echo ""
    echo "🛑 Stop:"
    echo "   kill \$(cat logs/bot.pid)"
else
    echo "🚀 Starting bot..."
    echo "ℹ️  Analysis handled by Claude scheduled task (every 10 min, Mon-Fri 10am-6pm)"
    echo ""
    echo "Press Ctrl+C to stop."
    echo ""

    # Trap Ctrl+C
    trap 'kill $BOT_PID 2>/dev/null; wait; echo ""; echo "🛑 Stopped"; exit' INT TERM

    # Start bot
    $PYTHON -m manideep_bot.app 2>&1 | sed 's/^/[BOT] /' &
    BOT_PID=$!

    # Wait
    wait
fi
