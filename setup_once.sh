#!/bin/bash
# One-time setup - run this once, then forget about it

echo "Setting up Manideep Bot (one-time setup)..."

cd "$(dirname "$0")"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate and install
source .venv/bin/activate
echo "Installing dependencies..."
pip install -r requirements.txt
pip install -e .

echo "Setup complete!"
echo ""
echo "Now you can run:"
echo "  ./run_bot.sh         # Start Slack bot + auto-watcher"
echo "  ./run-monitor.sh     # Start ticket monitor"
