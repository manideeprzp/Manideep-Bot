"""
Bot commands: run from Slack in the same channel as ticket threads.
Keeps ticket-related threads and operational commands (fetch tickets, cron approval, etc.) in one place.
Add new commands here and register in app.py so the bot stays well-structured.
"""
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent.parent.parent


def _normalize_command(text: str) -> Optional[str]:
    """Recognize command from user message (strip @mention, lowercase, trim)."""
    if not text:
        return None
    t = text.strip().lower()
    if "fetch updated tickets" in t or "refresh solved tickets" in t or "refresh tickets" in t:
        return "fetch_updated_tickets"
    if t in ("fetch solved", "fetch tickets", "run cron", "run scheduled fetch", "run solved fetch"):
        return "fetch_updated_tickets"
    if t in ("help", "commands"):
        return "help"
    return None


def get_command_id(text: str) -> Optional[str]:
    """Return command id if message is a known command, else None."""
    return _normalize_command(text)


def is_bot_command(text: str) -> bool:
    """True if the message is a known bot command (not ticket paste / Yes/Approve)."""
    return get_command_id(text) is not None


def run_command(command_id: str, config) -> str:
    """
    Execute a bot command and return the reply text.
    command_id comes from _normalize_command. Add new branches for new commands.
    """
    if command_id == "fetch_updated_tickets":
        return _run_fetch_updated_tickets(config)
    if command_id == "help":
        return get_commands_help()
    return f"Unknown command: `{command_id}`. Say `help` for commands."


def _run_fetch_updated_tickets(config) -> str:
    """Run scripts/fetch_my_solved.py with --no-timeline so it finishes in Slack (no timeout)."""
    script = _BOT_ROOT / "scripts" / "fetch_my_solved.py"
    if not script.exists():
        return "Script `scripts/fetch_my_solved.py` not found."
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--no-timeline"],
            cwd=str(_BOT_ROOT),
            env=os.environ.copy(),
            timeout=300,
            capture_output=True,
            text=True,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0:
            return f"Fetch failed (exit {result.returncode}). Stderr: {err[:400]}"
        for line in (err or "").strip().split("\n"):
            if "Wrote" in line:
                return line.strip() + "\n_(Quick refresh, no timeline. For thread text run locally: `python3 scripts/fetch_my_solved.py`)_"
        return "Solved tickets refreshed (quick refresh, no timeline)."
    except subprocess.TimeoutExpired:
        return "Fetch timed out. Run locally: `python3 scripts/fetch_my_solved.py --no-timeline`"
    except Exception as e:
        logger.exception("Fetch command failed")
        return f"Error: {e}"


def get_commands_help() -> str:
    """Short help for supported commands (for bot reply when user says 'help' or similar)."""
    return (
        "*Commands (say in channel or thread):*\n\n"
        "*Close a ticket directly:*\n"
        "- `close ISS-XXXXXX` -- Start the close flow. Bot fetches the ticket and prompts for:\n"
        "  `tags:` `cause_code:` `breach_reason:` `note:` (all optional)\n"
        "  Reply `confirm` to close immediately with just `bot_resolved` tag.\n\n"
        "*Analyze a ticket:*\n"
        "- Paste a ticket ID or description -- I'll suggest an approach and skill.\n"
        "  Reply *Yes* to run the skill, then *Approve* to post resolution + close.\n\n"
        "*Fetch tickets:*\n"
        "- `fetch updated tickets` / `refresh solved tickets` -- Quick refresh from DevRev.\n"
        "  For full refresh run `python3 scripts/fetch_my_solved.py` locally."
    )
