#!/usr/bin/env python3
"""
Fetch all DevRev tickets (works) that the current user has solved.
Uses DEVREV_API_KEY and DEVREV_SOLVED_STATES from .env.
Writes data/my_solved_tickets.json in the project root.
"""
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

# Project root = parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_FILE = DATA_DIR / "my_solved_tickets.json"
load_dotenv(PROJECT_ROOT / "scripts" / ".env")

DEVREV_BASE = "https://api.devrev.ai"
API_KEY = os.getenv("DEVREV_API_KEY")
SOLVED_STATES = [s.strip() for s in (os.getenv("DEVREV_SOLVED_STATES") or "closed,done,resolved").split(",") if s.strip()]


def get_self():
    r = requests.get(
        f"{DEVREV_BASE}/dev-users.self",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("dev_user", {})


def list_works(owned_by_ids, state_filter, limit=50, cursor=None):
    body = {
        "owned_by": owned_by_ids,
        "state": state_filter,
        "limit": limit,
    }
    if cursor:
        body["cursor"] = cursor
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


def main():
    if not API_KEY:
        print("Set DEVREV_API_KEY in scripts/.env", file=sys.stderr)
        sys.exit(1)

    user = get_self()
    user_id = user.get("id")
    if not user_id:
        print("Could not get current user from DevRev", file=sys.stderr)
        sys.exit(1)
    print(f"Current user: {user.get('full_name') or user.get('email')} ({user_id})", file=sys.stderr)

    all_works = []
    cursor = None
    while True:
        data = list_works([user_id], SOLVED_STATES, limit=50, cursor=cursor)
        works = data.get("works") or []
        all_works.extend(works)
        cursor = data.get("next_cursor")
        if not cursor or not works:
            break

    def extract_tags(work):
        tags_raw = work.get("tags") or []
        tags = [
            {"name": (t.get("tag") or {}).get("name") or "", "value": t.get("value") or ""}
            for t in tags_raw
        ]
        # Flat list of "name" or "name: value" for easy filter/sort
        tag_names = []
        for t in tags:
            if t["name"]:
                tag_names.append(f"{t['name']}:{t['value']}" if t["value"] else t["name"])
        return tags, tag_names

    out = []
    for w in all_works:
        tags_list, tag_names = extract_tags(w)
        out.append({
            "id": w.get("id"),
            "display_id": w.get("display_id"),
            "title": w.get("title"),
            "body": (w.get("body") or "")[:5000],
            "state": w.get("state"),
            "stage": (w.get("stage") or {}).get("name"),
            "created_date": w.get("created_date"),
            "modified_date": w.get("modified_date"),
            "type": w.get("type"),
            "tags": tags_list,
            "tag_names": tag_names,
        })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"user_id": user_id, "solved_states": SOLVED_STATES, "tickets": out}, f, indent=2)

    print(f"Wrote {len(out)} solved tickets to {OUTPUT_FILE}", file=sys.stderr)
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
