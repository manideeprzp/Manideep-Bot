#!/usr/bin/env python3
"""
Register a DevRev webhook for work_created events.
Your webhook server must be running and reachable at the given URL so DevRev can send the verify request.

Usage:
  python3 scripts/register_devrev_webhook.py --url https://your-public-url.example.com/webhooks/devrev

Requires DEVREV_API_KEY in scripts/.env (or environment).
Prints the webhook secret: set it as DEVREV_WEBHOOK_SECRET and restart the webhook server.
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
load_dotenv(PROJECT_ROOT / ".env")

DEVREV_BASE = "https://api.devrev.ai"


def main():
    parser = argparse.ArgumentParser(
        description="Register DevRev webhook for work_created. Server must be running at URL for verification."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Public HTTPS URL of your webhook endpoint (e.g. https://abc.ngrok.io/webhooks/devrev)",
    )
    parser.add_argument(
        "--event-types",
        nargs="+",
        default=["work_created"],
        help="Event types to subscribe to (default: work_created)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("DEVREV_API_KEY", "").strip()
    if not api_key:
        print("Set DEVREV_API_KEY in scripts/.env or environment.", file=sys.stderr)
        sys.exit(1)

    url = args.url.strip()
    if not url.startswith("https://"):
        print("URL must be HTTPS so DevRev can reach it.", file=sys.stderr)
        sys.exit(1)

    payload = {
        "event_types": args.event_types,
        "url": url,
    }
    resp = requests.post(
        f"{DEVREV_BASE}/webhooks.create",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        print(f"DevRev webhooks.create failed: {resp.status_code}", file=sys.stderr)
        print(resp.text, file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    webhook = data.get("webhook") or {}
    secret = webhook.get("secret", "")
    webhook_id = webhook.get("id", "")
    status = webhook.get("status", "")

    print("Webhook registered successfully.")
    print(f"  ID:     {webhook_id}")
    print(f"  Status: {status}")
    print(f"  URL:    {url}")
    if secret:
        print()
        print("Set the secret so your server can verify X-DevRev-Signature:")
        print(f"  export DEVREV_WEBHOOK_SECRET={secret}")
        print()
        print("Then restart the webhook server (manideep-bot-webhook).")
    else:
        print("(No secret in response; check DevRev API docs.)")


if __name__ == "__main__":
    main()
