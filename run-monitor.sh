#!/bin/bash
# Run the ticket monitor (handles venv internally - you never need to activate!)

cd "$(dirname "$0")"
source venv/bin/activate
python -m manideep_bot.monitor_cli run
