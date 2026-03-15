#!/usr/bin/env python3
"""Manually post Claude Code analysis to Slack thread."""
import sys
import json
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from manideep_bot.config import load_config

def post_analysis(response_file: Path, thread_ts: str):
    """Post analysis response to Slack thread."""
    config = load_config()

    try:
        from slack_sdk import WebClient
    except ImportError:
        print("Install slack-sdk: pip install slack-sdk")
        sys.exit(1)

    client = WebClient(token=config.slack.bot_token)

    # Read response
    with open(response_file) as f:
        data = json.load(f)

    analysis = data.get("analysis", "No analysis provided")
    ticket_id = data.get("ticket_id", "N/A")

    # Post to Slack
    result = client.chat_postMessage(
        channel=config.slack.bucket_channel_id,
        text=analysis,
        thread_ts=thread_ts
    )

    print(f"✅ Posted analysis to thread {thread_ts}")
    print(f"   Message TS: {result['ts']}")

    # Mark response as consumed
    consumed_file = response_file.with_suffix('.consumed')
    response_file.rename(consumed_file)
    print(f"✅ Marked response as consumed: {consumed_file.name}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python post_analysis_to_slack.py <response_file> <thread_ts>")
        print("\nExample:")
        print("  python post_analysis_to_slack.py \\")
        print("    data/analysis_queue/ticket_123_response.json \\")
        print("    1773176033.420549")
        sys.exit(1)

    response_path = Path(sys.argv[1])
    if not response_path.is_absolute():
        response_path = _root / response_path

    thread_ts = sys.argv[2]

    post_analysis(response_path, thread_ts)
