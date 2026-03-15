#!/usr/bin/env python3
"""Claude Code Ticket Analyzer - Interactive analysis tool.

This script helps Claude Code (you) analyze tickets submitted by the bot.

Usage:
    # List pending tickets
    python scripts/claude_code_analyzer.py list

    # Analyze a specific ticket
    python scripts/claude_code_analyzer.py analyze data/analysis_queue/ticket_123456.json

    # Watch for new tickets (continuous monitoring)
    python scripts/claude_code_analyzer.py watch
"""
import sys
import json
import time
from pathlib import Path

# Add src to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from manideep_bot.claude_code_agent import (
    list_pending_tickets,
    list_completed_responses,
    create_analysis_template,
)


def list_tickets():
    """List all pending tickets."""
    pending = list_pending_tickets()

    if not pending:
        print("📭 No pending tickets in the queue.\n")
        return

    print(f"📬 {len(pending)} pending ticket(s):\n")
    print(f"{'#':<4} {'Timestamp':<25} {'File':<40}")
    print("-" * 80)

    for i, ticket_file in enumerate(pending, 1):
        try:
            with open(ticket_file) as f:
                data = json.load(f)
            timestamp = data.get("submitted_at", "unknown")
            ticket_id = data.get("ticket_id", "unknown")
            print(f"{i:<4} {timestamp:<25} {ticket_file.name:<40}")
            if ticket_id != "unknown":
                print(f"     Ticket ID: {ticket_id}")
        except Exception as e:
            print(f"{i:<4} Error reading file: {e}")

    print("\nTo analyze a ticket:")
    print(f"  python scripts/claude_code_analyzer.py analyze {pending[0]}")
    print()


def show_ticket(ticket_file: Path):
    """Display ticket details for analysis."""
    if not ticket_file.exists():
        print(f"❌ Ticket file not found: {ticket_file}")
        return

    with open(ticket_file) as f:
        data = json.load(f)

    print("=" * 80)
    print("TICKET FOR ANALYSIS")
    print("=" * 80)
    print(f"File: {ticket_file.name}")
    print(f"Ticket ID: {data.get('ticket_id', 'N/A')}")
    print(f"Submitted: {data.get('submitted_at', 'N/A')}")
    print(f"Status: {data.get('status', 'unknown')}")
    print("\n" + "=" * 80)
    print("TICKET CONTENT")
    print("=" * 80)
    print(data.get("ticket_text", "No content"))
    print("\n" + "=" * 80)
    print()


def create_response_template(ticket_file: Path):
    """Create a response template file for Claude Code to fill in."""
    response_file = ticket_file.parent / f"{ticket_file.stem}_response.json"

    if response_file.exists():
        print(f"⚠️  Response file already exists: {response_file}")
        print("Delete it first if you want to recreate it.")
        return

    template = create_analysis_template(ticket_file)

    with open(response_file, "w") as f:
        json.dump(template, f, indent=2)

    print(f"✅ Created response template: {response_file}")
    print("\nEdit this file with your analysis, then save.")
    print("The bot will pick it up automatically within 2 seconds.")
    print()


def watch_queue():
    """Continuously watch for new tickets."""
    print("👀 Watching for new tickets... (Ctrl+C to stop)\n")

    seen_tickets = set(t.name for t in list_pending_tickets())

    try:
        while True:
            current_tickets = list_pending_tickets()
            current_names = set(t.name for t in current_tickets)

            new_tickets = current_names - seen_tickets

            if new_tickets:
                for ticket_name in new_tickets:
                    ticket_file = next(t for t in current_tickets if t.name == ticket_name)
                    print(f"\n🆕 New ticket detected: {ticket_name}")
                    show_ticket(ticket_file)
                    print(f"To analyze: python scripts/claude_code_analyzer.py analyze {ticket_file}\n")

                seen_tickets = current_names

            time.sleep(3)  # Check every 3 seconds

    except KeyboardInterrupt:
        print("\n\n👋 Stopped watching.")


def analyze_interactive(ticket_file: Path):
    """Interactive analysis - ask Claude Code to provide analysis."""
    show_ticket(ticket_file)

    print("=" * 80)
    print("YOUR ANALYSIS INSTRUCTIONS")
    print("=" * 80)
    print("""
Claude Code (you) should now analyze this ticket.

Use all your tools:
- Search past solved tickets
- Pattern matching
- Code repository search if needed
- Enhanced agent logic

Then provide a response in this format:

🟢 Confidence: [0-100]%

**Analysis:** [What is this ticket about?]

**Approach:**
1. [Step 1]
2. [Step 2]
3. [Step 3]

**Skill to run:** [skill-name]

**Reasoning:** [Why this skill and confidence score?]

**Required data:** [What data is present?]

**Missing data:** [What's missing, if anything?]

**Recommendation:** [auto_execute | ask_approval | need_info]

---

Reply **Yes** to run the skill, or **No** to cancel.
""")

    print("=" * 80)
    print()

    # Ask if user wants to create response template
    response = input("Create response template file? (y/n): ").strip().lower()
    if response in ("y", "yes"):
        create_response_template(ticket_file)
    else:
        print("\nProvide your analysis, and I'll help you create the response file.")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/claude_code_analyzer.py list")
        print("  python scripts/claude_code_analyzer.py analyze <ticket_file>")
        print("  python scripts/claude_code_analyzer.py watch")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "list":
        list_tickets()

    elif command == "watch":
        watch_queue()

    elif command == "analyze":
        if len(sys.argv) < 3:
            print("Error: Provide ticket file path")
            print("Example: python scripts/claude_code_analyzer.py analyze data/analysis_queue/ticket_123.json")
            sys.exit(1)

        ticket_path = Path(sys.argv[2])
        if not ticket_path.is_absolute():
            ticket_path = _root / ticket_path

        analyze_interactive(ticket_path)

    else:
        print(f"Unknown command: {command}")
        print("Available commands: list, analyze, watch")
        sys.exit(1)


if __name__ == "__main__":
    main()
