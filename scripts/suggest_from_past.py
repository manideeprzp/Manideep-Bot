#!/usr/bin/env python3
"""
Test the "understand issue + find relevant past solved tickets" flow.
Usage:
  # Dry-run: retrieval only, no AI (no API key needed)
  .venv/bin/python scripts/suggest_from_past.py --dry-run "Blinkit GC redemption code not received"
  .venv/bin/python scripts/suggest_from_past.py "Order 757987924 fulfillment in progress"   # same as --dry-run
  # Full AI suggestion (needs ANTHROPIC_API_KEY)
  .venv/bin/python scripts/suggest_from_past.py --suggest "Wallet closure request for merchant X"
"""
import argparse
import os
import sys
from pathlib import Path

# Project root = parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env for DEVREV / ANTHROPIC
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / "scripts" / ".env")
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser(
        description="Find relevant past solved tickets (BM25 + tags). Dry-run = retrieval only; --suggest = add AI."
    )
    parser.add_argument("query", nargs="*", help="Issue title/description (or pass as single string)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Retrieval only: print top past tickets, do not call Claude (default when --suggest is not set)",
    )
    parser.add_argument("--suggest", action="store_true", help="Also call Claude to suggest approach (needs ANTHROPIC_API_KEY)")
    parser.add_argument("-n", "--top", type=int, default=None, help="Number of past tickets (default: from config, usually 12)")
    parser.add_argument("--no-bm25", action="store_true", help="Use word-overlap only instead of BM25")
    args = parser.parse_args()
    query = " ".join(args.query).strip()
    if not query:
        parser.error("Provide issue text, e.g. suggest_from_past.py 'GC redemption not received'")
        return

    from manideep_bot.config import load_config
    from manideep_bot.retriever import find_relevant, format_relevant_for_prompt

    config = load_config()
    top_k = args.top if args.top is not None else getattr(config.retriever, "top_k", 12)
    use_bm25 = not args.no_bm25

    print("Query:", query[:200] + ("…" if len(query) > 200 else ""), "\n")

    relevant = find_relevant(query, config, top_k=top_k, use_bm25=use_bm25)
    if not relevant:
        print("No relevant past tickets found. Run scripts/fetch_my_solved.py first and ensure data/my_solved_tickets.json exists.")
        return

    print(f"Top {len(relevant)} relevant past tickets (score = BM25 + tag boost):\n")
    for i, t in enumerate(relevant, 1):
        print(f"  {i}. [{t['display_id']}] (score={t['score']}) {t['title'][:80]}")
        if t.get("tag_names"):
            print(f"      Tags: {', '.join(t['tag_names'])}")
        if t.get("body_snippet"):
            print(f"      Snippet: {t['body_snippet'][:120]}…")
        print()

    if args.suggest:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY for --suggest (e.g. in scripts/.env)")
            return
        from manideep_bot.agent import reply
        print("--- AI suggestion ---\n")
        suggestion = reply(query, config)
        print(suggestion)
    else:
        print("(Dry-run: retrieval only.) Run with --suggest to get full AI approach and skill (requires ANTHROPIC_API_KEY).")


if __name__ == "__main__":
    main()
