"""
Bucket watcher: fetch tickets assigned to you from DevRev, analyze each (retriever + AI),
post suggestions to Slack. You reply Done → bot runs skill; Approve → post on DevRev and close.
No pasting: bot watches your bucket only.
"""
import hashlib
import json
import logging
import re
import time
from pathlib import Path

from .config import Config

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent.parent.parent
_BUCKET_STATE_FILE = _BOT_ROOT / "data" / "bucket_thread_state.json"


def _parse_skill_name(text: str) -> str:
    if not text:
        return "order-trace-debugger"
    m = re.search(r"skill[:\s]+([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    return "order-trace-debugger"


def _load_bucket_state() -> dict:
    if _BUCKET_STATE_FILE.exists():
        try:
            with open(_BUCKET_STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Bucket state file corrupted, starting fresh: %s", e)
    return {}


def _save_bucket_state(state: dict):
    _BUCKET_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_BUCKET_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_bucket_state_key(channel_id: str, thread_ts: str) -> str:
    return f"{channel_id}|{thread_ts}"


def get_thread_state_from_bucket(channel_id: str, thread_ts: str) -> dict | None:
    """Look up state for a thread (used by app when user replies in a bucket post thread)."""
    state = _load_bucket_state()
    return state.get(get_bucket_state_key(channel_id, thread_ts))


def set_bucket_thread_state(channel_id: str, thread_ts: str, value: dict):
    state = _load_bucket_state()
    state[get_bucket_state_key(channel_id, thread_ts)] = value
    _save_bucket_state(state)


def pop_bucket_thread_state(channel_id: str, thread_ts: str):
    state = _load_bucket_state()
    state.pop(get_bucket_state_key(channel_id, thread_ts), None)
    _save_bucket_state(state)


# ── Ticket → Slack thread mapping ────────────────────────────────────────────
# Stores: display_id (ISS-XXXXXX) → {channel, thread_ts, last_timeline_id}
# Used so monitor updates always reply in the SAME Slack thread, not a new one.

_TICKET_THREADS_FILE = _BOT_ROOT / "data" / "assigned_ticket_threads.json"


def _load_ticket_threads() -> dict:
    if _TICKET_THREADS_FILE.exists():
        try:
            with open(_TICKET_THREADS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_ticket_threads(data: dict):
    _TICKET_THREADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_TICKET_THREADS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_body_hash(title: str, body: str) -> str:
    """MD5 hash of title+body for change detection."""
    return hashlib.md5((title + body).encode()).hexdigest()


def save_ticket_thread(
    display_id: str,
    channel: str,
    thread_ts: str,
    last_timeline_id: str = "",
    last_body_hash: str = "",
    last_status_update_ts: float = 0.0,
):
    """Save the Slack thread for a ticket so monitor updates reply there."""
    data = _load_ticket_threads()
    existing = data.get(display_id, {})
    data[display_id] = {
        "channel": channel,
        "thread_ts": thread_ts,
        "last_timeline_id": last_timeline_id or existing.get("last_timeline_id", ""),
        "last_body_hash": last_body_hash or existing.get("last_body_hash", ""),
        "last_status_update_ts": last_status_update_ts or existing.get("last_status_update_ts", 0.0),
    }
    _save_ticket_threads(data)


def get_ticket_thread(display_id: str) -> dict | None:
    """Return {channel, thread_ts, last_timeline_id} for a ticket, or None."""
    return _load_ticket_threads().get(display_id)


def update_ticket_thread_timeline(display_id: str, last_timeline_id: str):
    """Update the last seen timeline entry ID for a ticket."""
    data = _load_ticket_threads()
    if display_id in data:
        data[display_id]["last_timeline_id"] = last_timeline_id
        _save_ticket_threads(data)


def update_ticket_thread_fields(display_id: str, **kwargs):
    """Update arbitrary fields on a ticket thread record (e.g. last_body_hash, last_status_update_ts)."""
    data = _load_ticket_threads()
    if display_id in data:
        data[display_id].update(kwargs)
        _save_ticket_threads(data)


def fetch_my_bucket_works(config: Config) -> list[dict]:
    """Fetch work items assigned to me in open states (full objects with title, body)."""
    from . import devrev_client
    user = devrev_client.get_self()
    user_id = user.get("id")
    if not user_id:
        return []
    states = getattr(config.bucket, "states", None) or ["open", "in_progress", "triaged", "backlog"]
    out = []
    cursor = None
    while True:
        data = devrev_client.works_list(
            owned_by=[user_id],
            state=states,
            limit=50,
            cursor=cursor,
        )
        works = data.get("works") or []
        out.extend(works)
        cursor = data.get("next_cursor") or None
        if cursor is None or not works:
            break
    return out


def run_bucket_once(config: Config) -> int:
    """
    Fetch my bucket tickets, analyze each (retriever + Claude), post to Slack.
    Returns number of tickets posted. Requires SLACK_BOT_TOKEN and SLACK_BUCKET_CHANNEL_ID.
    """
    from . import devrev_client
    from .agent import reply

    channel_id = (config.slack.bucket_channel_id or "").strip()
    if not channel_id:
        logger.warning("SLACK_BUCKET_CHANNEL_ID (or slack.bucket_channel_id) not set; skipping bucket run")
        return 0
    if not config.slack.bot_token:
        logger.warning("SLACK_BOT_TOKEN not set; skipping bucket run")
        return 0

    works = fetch_my_bucket_works(config)
    max_per_run = getattr(config.bucket, "max_tickets_per_run", 10)
    works = works[:max_per_run]
    if not works:
        logger.info("Bucket: no tickets assigned to you in open states")
        return 0

    try:
        from slack_sdk import WebClient
        client = WebClient(token=config.slack.bot_token)
    except ImportError:
        logger.error("Install: pip install slack-sdk")
        return 0

    posted = 0
    for w in works:
        work_id = w.get("id")  # don:core:...
        display_id = w.get("display_id") or work_id
        title = (w.get("title") or "")[:200]
        body = (w.get("body") or "")[:3000]
        ticket_text = f"{title}\n\n{body}".strip()
        if not ticket_text:
            ticket_text = str(display_id)

        try:
            from .retriever import find_relevant, format_related_ticket_links
            response = reply(ticket_text, config)
            relevant = find_relevant(ticket_text, config, top_k=5)
            related_line = format_related_ticket_links(
                relevant,
                app_base_url=getattr(config.devrev, "app_base_url", None) or "https://app.devrev.ai",
                max_items=5,
            )
        except Exception as e:
            logger.exception("Agent error for %s: %s", display_id, e)
            response = f"Could not analyze: {e}. Reply **Done** to try running a skill anyway."
            related_line = ""

        skill_name = _parse_skill_name(response)
        if len(response) > 2800:
            response = response[:2800] + "\n… (truncated)"

        message_parts = [
            f"*Ticket {display_id}* — {title}",
            "",
            response,
        ]
        if related_line:
            message_parts.append("")
            message_parts.append(related_line)
        message_parts.append("")
        message_parts.append("—_Reply **Done** in this thread to run the skill and see execution. Then **Approve** to post on DevRev and close._")
        text = "\n".join(message_parts)

        try:
            resp = client.chat_postMessage(
                channel=channel_id,
                text=text,
                unfurl_links=False,
                unfurl_media=False,
            )
            ts = resp.get("ts")
            if ts:
                set_bucket_thread_state(channel_id, ts, {
                    "step": "suggested",
                    "work_id": work_id,
                    "display_id": display_id,
                    "ticket_text": ticket_text,
                    "skill_name": skill_name,
                })
                posted += 1
        except Exception as e:
            logger.exception("Slack post for %s: %s", display_id, e)

    return posted
