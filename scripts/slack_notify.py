#!/usr/bin/env python3
"""
Send a Slack message for a new ticket with suggested approach.
Usage:
  python3 slack_notify.py --ticket-id ISSUE-123 --title "..." --suggestion "..."
Requires SLACK_WEBHOOK_URL in scripts/.env.
"""
import argparse
import os
import sys
from pathlib import Path

try:
    import requests
    from dotenv import load_dotenv
except ImportError:
    print("Install: pip install requests python-dotenv", file=sys.stderr)
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / "scripts" / ".env")

WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")


def send_via_webhook(text: str, blocks: list = None):
    if not WEBHOOK:
        print("Set SLACK_WEBHOOK_URL in scripts/.env", file=sys.stderr)
        return False
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    r = requests.post(WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--suggestion", default="")
    parser.add_argument("--link", default="")
    args = parser.parse_args()

    text = f"New ticket: *{args.ticket_id}* — {args.title}"
    if args.suggestion:
        text += f"\n\nSuggested approach (from past tickets):\n{args.suggestion}"
    text += "\n\nReply: Yes / No / Proceed"

    if args.link:
        text += f"\n<{args.link}|Open in DevRev>"

    if send_via_webhook(text):
        print("Slack notification sent", file=sys.stderr)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
