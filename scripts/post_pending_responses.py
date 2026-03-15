#!/usr/bin/env python3
"""Post all pending Claude Code responses to their Slack threads.

Usage:
    python scripts/post_pending_responses.py

This reads all *_response.json files in the queue, looks up their
thread mappings, and posts them to the correct Slack threads.
"""
import json
import os
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv(_root / "scripts" / ".env")
except ImportError:
    pass

from manideep_bot.config import load_config
from manideep_bot.response_watcher import find_pending_responses, post_response_to_slack


def main():
    print("=" * 80)
    print("POST PENDING RESPONSES TO SLACK")
    print("=" * 80)
    print()

    # Load config
    config = load_config()

    # Check Slack tokens
    if not config.slack.bot_token:
        print("❌ ERROR: SLACK_BOT_TOKEN not set")
        print("   Set it in scripts/.env or config/env.dev.yaml")
        return 1

    # Initialize Slack client
    try:
        from slack_sdk import WebClient
        slack_client = WebClient(token=config.slack.bot_token)
    except ImportError:
        print("❌ ERROR: slack-sdk not installed")
        print("   Run: pip install slack-sdk")
        return 1

    # Find pending responses
    pending = find_pending_responses()

    if not pending:
        print("✅ No pending responses to post!")
        return 0

    print(f"📬 Found {len(pending)} pending response(s):\n")

    for response_file in pending:
        print(f"Processing: {response_file.name}")

        # Read the response
        with open(response_file) as f:
            data = json.load(f)

        ticket_id = data.get("ticket_id", "unknown")
        print(f"  Ticket: {ticket_id}")

        # Post to Slack
        success = post_response_to_slack(response_file, slack_client, config)

        if success:
            print(f"  ✅ Posted to Slack and marked as consumed")
        else:
            print(f"  ❌ Failed to post (check logs above)")

        print()

    print("=" * 80)
    print("DONE!")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
