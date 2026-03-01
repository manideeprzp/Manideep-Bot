"""CLI: run bucket watcher once (fetch my tickets, analyze, post to Slack)."""
import logging
import os
import sys

# Load .env so DEVREV + ANTHROPIC + SLACK are available
from pathlib import Path
_bot_root = Path(__file__).resolve().parent.parent.parent
_env = _bot_root / "scripts" / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env)
    except ImportError:
        pass

from .config import load_config
from .bucket import run_bucket_once


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    config = load_config()
    if not config.slack.bucket_channel_id:
        print("Set SLACK_BUCKET_CHANNEL_ID (or slack.bucket_channel_id in config). Invite the bot to a channel and use that channel ID.")
        sys.exit(1)
    if not config.slack.bot_token:
        print("Set SLACK_BOT_TOKEN")
        sys.exit(1)
    n = run_bucket_once(config)
    print(f"Bucket run complete: posted {n} ticket suggestion(s) to Slack.")


if __name__ == "__main__":
    main()
