#!/usr/bin/env python3
"""
Read data/my_solved_tickets.json and generate one skill file per ticket under solved/.
"""
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "my_solved_tickets.json"
SOLVED_DIR = PROJECT_ROOT / "solved"


def slug(s, max_len=50):
    s = re.sub(r"[^\w\s-]", "", (s or "").lower())
    s = re.sub(r"[-\s]+", "-", s).strip("-")
    return (s[:max_len] if len(s) > max_len else s) or "ticket"


def main():
    if not DATA_FILE.exists():
        print(f"Run fetch_my_solved.py first. Missing: {DATA_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(DATA_FILE) as f:
        data = json.load(f)

    tickets = data.get("tickets") or []
    SOLVED_DIR.mkdir(parents=True, exist_ok=True)

    for t in tickets:
        tid = t.get("display_id") or t.get("id") or "unknown"
        title = (t.get("title") or "").strip()
        body = (t.get("body") or "").strip()
        text = f"{title} {body[:200]}"
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
        keywords = list(dict.fromkeys(w.lower() for w in words[:15]))
        summary = body[:500] if body else title
        name = slug(title) or slug(tid)
        path = SOLVED_DIR / f"{name}.md"
        content = f"""---
source_ticket_id: {tid}
title: {title[:80]}
keywords: {", ".join(keywords[:10])}
---

# Solved: {title[:80]}

**DevRev:** {tid}

## Summary
{summary}

## Suggested steps (from resolution)
- Use this as reference when a new ticket is similar (same keywords/domain).
- Match repos: Booking_Service, campaigns_service, client_service, perks_service, rewards-marketplace, rewards-procurement.
"""
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path.name}", file=sys.stderr)

    print(f"Generated {len(tickets)} skills in {SOLVED_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
