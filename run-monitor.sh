#!/bin/bash
# Run the ticket monitor

cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

python -m manideep_bot.monitor_cli run
