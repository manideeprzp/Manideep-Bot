#!/usr/bin/env python3
"""Analyze a specific DevRev ticket with the enhanced agent."""
import sys
from pathlib import Path

# Add src to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from manideep_bot.config import load_config
from manideep_bot import devrev_client
from manideep_bot.enhanced_agent import enhanced_reply


def analyze_ticket(display_id: str):
    """Fetch and analyze a ticket."""
    print(f"\n{'='*80}")
    print(f"ANALYZING TICKET: {display_id}")
    print(f"{'='*80}\n")

    config = load_config()

    # Fetch ticket from DevRev
    print(f"Fetching {display_id} from DevRev...")
    work = devrev_client.get_work_by_display_id(display_id)

    if not work:
        print(f"❌ Could not fetch {display_id} from DevRev")
        print("Possible reasons:")
        print("  - Ticket doesn't exist")
        print("  - DEVREV_API_KEY not set or invalid")
        print("  - Ticket is too old or in wrong state")
        sys.exit(1)

    # Extract ticket details
    work_id = work.get("id", "")
    title = work.get("title", "")
    body = work.get("body", "")
    owned_by = work.get("owned_by", [])
    stage = work.get("stage", {})
    tags = work.get("tags", [])

    print(f"✓ Fetched successfully\n")
    print(f"{'='*80}")
    print(f"TICKET DETAILS")
    print(f"{'='*80}")
    print(f"ID: {work_id}")
    print(f"Display ID: {display_id}")
    print(f"Title: {title}")
    print(f"Stage: {stage.get('name', 'unknown')}")
    print(f"Owned by: {len(owned_by)} user(s)")
    if tags:
        print(f"Tags: {', '.join([t.get('name', '') for t in tags[:5]])}")
    print(f"\nBody:\n{body[:500]}{'...' if len(body) > 500 else ''}")
    print(f"\n{'='*80}\n")

    # Prepare ticket text for analysis
    ticket_text = f"{title}\n\n{body}".strip()

    # Run enhanced agent
    print("Running enhanced agent analysis...\n")
    print(f"{'='*80}")
    print(f"ENHANCED AGENT RESPONSE")
    print(f"{'='*80}\n")

    response = enhanced_reply(ticket_text, config)
    print(response)

    print(f"\n{'='*80}")
    print(f"ANALYSIS COMPLETE")
    print(f"{'='*80}\n")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python analyze_ticket.py ISS-XXXXXX")
        print("\nExample:")
        print("  python analyze_ticket.py ISS-1632906")
        sys.exit(1)

    display_id = sys.argv[1].strip()

    # Normalize display_id
    if not display_id.startswith("ISS-"):
        if display_id.isdigit():
            display_id = f"ISS-{display_id}"
        else:
            print(f"Invalid ticket ID: {display_id}")
            print("Expected format: ISS-XXXXXX or just the number")
            sys.exit(1)

    analyze_ticket(display_id)


if __name__ == "__main__":
    main()
