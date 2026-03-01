#!/usr/bin/env python3
"""
Fetch tickets to monitor: either (1) unassigned in a pod, or (2) assigned to me.
Usage:
  python3 fetch_tickets_to_monitor.py --mode unassigned   # needs DEVREV_POD_PART_ID
  python3 fetch_tickets_to_monitor.py --mode assigned-to-me
Writes data/tickets_to_monitor.json.
"""
import argparse
import json
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
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "tickets_to_monitor.json"
load_dotenv(PROJECT_ROOT / "scripts" / ".env")

DEVREV_BASE = "https://api.devrev.ai"
API_KEY = os.getenv("DEVREV_API_KEY")
POD_PART_ID = os.getenv("DEVREV_POD_PART_ID")


def get_self():
    r = requests.get(
        f"{DEVREV_BASE}/dev-users.self",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("dev_user", {})


def list_works_post(body, limit=50, cursor=None):
    if cursor:
        body["cursor"] = cursor
    body["limit"] = limit
    r = requests.post(
        f"{DEVREV_BASE}/works.list",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_assigned_to_me(user_id):
    open_states = ["open", "in_progress", "in progress", "triaged"]
    all_works = []
    cursor = None
    while True:
        data = list_works_post(
            {"owned_by": [user_id], "state": open_states},
            cursor=cursor,
        )
        works = data.get("works") or []
        all_works.extend(works)
        cursor = data.get("next_cursor")
        if not cursor or not works:
            break
    return all_works


def fetch_unassigned_in_pod(part_id):
    all_works = []
    cursor = None
    open_states = ["open", "triaged", "backlog"]
    while True:
        body = {"applies_to_part": [part_id], "state": open_states}
        data = list_works_post(body, cursor=cursor)
        works = data.get("works") or []
        unassigned = [w for w in works if not (w.get("owned_by") or [])]
        all_works.extend(unassigned)
        cursor = data.get("next_cursor")
        if not cursor or not works:
            break
    return all_works


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["unassigned", "assigned-to-me"], required=True)
    args = parser.parse_args()

    if not API_KEY:
        print("Set DEVREV_API_KEY in scripts/.env", file=sys.stderr)
        sys.exit(1)

    user = get_self()
    user_id = user.get("id")
    if not user_id:
        print("Could not get current user", file=sys.stderr)
        sys.exit(1)

    if args.mode == "unassigned":
        if not POD_PART_ID:
            print("Set DEVREV_POD_PART_ID in .env for unassigned mode", file=sys.stderr)
            sys.exit(1)
        works = fetch_unassigned_in_pod(POD_PART_ID)
        label = "unassigned (pod)"
    else:
        works = fetch_assigned_to_me(user_id)
        label = "assigned to me"

    out = [
        {
            "id": w.get("id"),
            "display_id": w.get("display_id"),
            "title": w.get("title"),
            "body": (w.get("body") or "")[:5000],
            "state": w.get("state"),
            "stage": (w.get("stage") or {}).get("name"),
            "created_date": w.get("created_date"),
            "type": w.get("type"),
        }
        for w in works
    ]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"mode": args.mode, "user_id": user_id, "tickets": out}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Found {len(out)} tickets ({label}) -> {OUTPUT_FILE}", file=sys.stderr)
    for t in out[:10]:
        print(f"  - {t.get('display_id')} {t.get('title')[:60]}", file=sys.stderr)
    if len(out) > 10:
        print(f"  ... and {len(out) - 10} more", file=sys.stderr)
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
