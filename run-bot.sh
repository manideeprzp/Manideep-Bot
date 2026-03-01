#!/bin/bash
# Run the Slack bot (handles venv internally - you never need to activate!)

cd "$(dirname "$0")"
source venv/bin/activate
python -m manideep_bot.app
