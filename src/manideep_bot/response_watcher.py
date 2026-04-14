"""Watches data/claude_responses/ for Claude Code responses and posts them to Slack."""
import json
import logging
import re
import time
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)

_RESPONSE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "claude_responses"
_MAPPING_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "thread_mappings.json"
_SEEN: set = set()


def _load_mappings() -> dict:
    if _MAPPING_FILE.exists():
        try:
            return json.loads(_MAPPING_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_mappings(mappings: dict):
    _MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MAPPING_FILE.write_text(json.dumps(mappings, indent=2))


def save_thread_mapping(ticket_id: str, channel: str, thread_ts: str):
    """Save which Slack channel/thread a ticket analysis should be posted to."""
    mappings = _load_mappings()
    mappings[ticket_id] = {"channel": channel, "thread_ts": thread_ts}
    _save_mappings(mappings)


def _md_to_slack(text: str) -> str:
    """Convert **bold** markdown to Slack's *bold* mrkdwn."""
    return re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)


def _extract_section(content: str, header: str) -> str:
    """Extract text following a **Header:** or **Header** pattern."""
    pattern = rf"\*\*{re.escape(header)}:?\*\*\s*(.*?)(?=\n\*\*[A-Z]|\Z)"
    m = re.search(pattern, content, re.S | re.I)
    return m.group(1).strip() if m else ""


def _format_approach(raw: str) -> str:
    """Format approach steps with bold numbers."""
    lines = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\.\s*(.*)", line)
        if m:
            lines.append(f"  *{m.group(1)}.* {_md_to_slack(m.group(2))}")
        else:
            lines.append(f"  {_md_to_slack(line)}")
    return "\n".join(lines)


def _build_attachments(content: str, ticket_id: str) -> list[dict]:
    """Build Slack attachments from analysis content for reliable rendering."""
    analysis = _extract_section(content, "Analysis")
    approach = _extract_section(content, "Approach")
    skill = _extract_section(content, "Skill to run")
    confidence = _extract_section(content, "Confidence")
    tags = _extract_section(content, "Suggested tags")
    fields = _extract_section(content, "Suggested fields")

    attachments = []

    # 1. Analysis (blue bar)
    if analysis:
        attachments.append({
            "color": "#0052CC",
            "text": _md_to_slack(analysis[:2900]),
            "mrkdwn_in": ["text"],
        })

    # 2. Approach (gray bar)
    if approach:
        attachments.append({
            "color": "#E0E0E0",
            "text": f"*Approach*\n{_format_approach(approach)}",
            "mrkdwn_in": ["text"],
        })

    # 3. Skill + Confidence + Tags + Fields (green/yellow/red bar based on confidence)
    conf_lower = (confidence or "").lower()
    bar_color = {"high": "#36a64f", "medium": "#daa038"}.get(conf_lower, "#cccccc")
    conf_emoji = {"high": ":large_green_circle:", "medium": ":large_yellow_circle:"}.get(conf_lower, ":white_circle:")

    meta_lines = []
    if skill:
        meta_lines.append(f"*Skill:*  `{skill}`")
    if confidence:
        meta_lines.append(f"*Confidence:*  {conf_emoji} {confidence}")
    if tags:
        meta_lines.append(f"*Tags:*  {_md_to_slack(tags.strip())}")
    if fields:
        meta_lines.append(f"*Fields:*  {_md_to_slack(fields.strip())}")

    if meta_lines:
        attachments.append({
            "color": bar_color,
            "text": "\n".join(meta_lines),
            "mrkdwn_in": ["text"],
        })

    # 4. Action prompt
    attachments.append({
        "color": "#F5F5F5",
        "text": "Reply  *Yes*  to run the skill  |  *No*  to skip",
        "mrkdwn_in": ["text"],
    })

    return attachments


def _post_formatted(slack_client, channel: str, thread_ts: str, ticket_id: str, content: str):
    """Post analysis as Slack attachments with color bars for clean rendering."""
    try:
        attachments = _build_attachments(content, ticket_id)
        skill = _extract_section(content, "Skill to run") or "none"
        slack_client.chat_postMessage(
            channel=channel,
            text=f":mag: *Analysis: {ticket_id}* | Skill to run: `{skill}`",
            attachments=attachments,
            thread_ts=thread_ts,
        )
    except Exception as e:
        logger.warning("Formatted post failed (%s), falling back to plain text", e)
        fallback = _md_to_slack(content)
        if len(fallback) > 3900:
            fallback = fallback[:3900] + "\n... (truncated)"
        slack_client.chat_postMessage(
            channel=channel,
            text=fallback,
            thread_ts=thread_ts,
        )


_REQUEST_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "claude_requests"
_NOTIFIED: set = set()


def start_pending_notifier(slack_client, notify_channel: str, bot_user_id: str = ""):
    """
    Background thread: watches data/claude_requests/ for new ticket request files.
    When new files appear, posts a batched Slack notification — user replies
    '@ManideepBot check' in Slack to trigger analysis. No Claude Code needed.
    """
    def _notify():
        _REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Pending notifier started — watching %s", _REQUEST_DIR)
        mention = f"<@{bot_user_id}> check" if bot_user_id else "@ManideepBot check"
        while True:
            try:
                new_tickets = [
                    f.stem for f in _REQUEST_DIR.glob("ISS-*.md")
                    if f.stem not in _NOTIFIED
                ]
                if new_tickets:
                    count = len(new_tickets)
                    ticket_list = ", ".join(f"`{t}`" for t in new_tickets[:5])
                    if count > 5:
                        ticket_list += f" + {count - 5} more"
                    msg = (
                        f":inbox_tray: *{count} new ticket{'s' if count > 1 else ''} pending analysis*\n"
                        f"{ticket_list}\n\n"
                        f"Reply  *{mention}*  to analyze {'them' if count > 1 else 'it'}."
                    )
                    try:
                        slack_client.chat_postMessage(channel=notify_channel, text=msg)
                        logger.info("Notified Slack: %d pending tickets", count)
                    except Exception as e:
                        logger.error("Failed to post pending notification: %s", e)
                    for t in new_tickets:
                        _NOTIFIED.add(t)
            except Exception as e:
                logger.error("Pending notifier error: %s", e)
            time.sleep(10)

    t = Thread(target=_notify, daemon=True)
    t.start()
    return t


def start_response_watcher(slack_client):
    """
    Background thread: watches for .md files in data/claude_responses/.
    When a new file appears, posts the content to the correct Slack thread.
    """
    def _watch():
        _RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Response watcher started — watching %s", _RESPONSE_DIR)
        while True:
            try:
                for f in _RESPONSE_DIR.glob("*.md"):
                    if f.name in _SEEN:
                        continue
                    content = f.read_text().strip()
                    if not content:
                        continue

                    ticket_id = f.stem
                    _SEEN.add(f.name)
                    logger.info("Claude Code response received for %s", ticket_id)

                    mappings = _load_mappings()
                    mapping = mappings.get(ticket_id)
                    if mapping:
                        channel = mapping["channel"]
                        thread_ts = mapping["thread_ts"]
                        try:
                            _post_formatted(slack_client, channel, thread_ts, ticket_id, content)
                            logger.info("Posted analysis for %s to %s", ticket_id, channel)
                            # Set thread state so "yes" replies work correctly
                            try:
                                from . import app as _app
                                # Load ticket_text from the request file if available
                                _req_file = Path(__file__).resolve().parent.parent.parent / "data" / "claude_requests" / "done" / f"{ticket_id}.md"
                                _ticket_text = _req_file.read_text() if _req_file.exists() else ""
                                _app.set_thread_state_from_analysis(channel, thread_ts, ticket_id, content, _ticket_text)
                            except Exception as _se:
                                logger.warning("Could not set thread state for %s: %s", ticket_id, _se)
                        except Exception as e:
                            logger.error("Failed to post response for %s: %s", ticket_id, e)
                        mappings.pop(ticket_id, None)
                        _save_mappings(mappings)
                    else:
                        logger.warning("No thread mapping for %s — keeping file for retry", ticket_id)
                        _SEEN.discard(f.name)
                        continue
            except Exception as e:
                logger.error("Watcher error: %s", e)
            time.sleep(3)

    t = Thread(target=_watch, daemon=True)
    t.start()
    return t
