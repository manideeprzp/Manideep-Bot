"""
Proactive monitor: (1) new tickets matching filters, (2) my tickets with new replies.
Persists last run state in data/monitor_state.json. Post findings to Slack (via webhook or bot).
"""
import json
import logging
import os
import time
from pathlib import Path

from .config import load_config

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _BOT_ROOT / "data" / "monitor_state.json"


def _load_state():
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_new_ticket_ids": [], "last_timeline_by_work": {}, "last_run_ts": None, "last_solved_fetch_ts": None}


def _save_state(state):
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _slack_post_interactive(text: str, config, work_id: str, display_id: str, ticket_text: str, skill_name: str):
    """Post to Slack bot channel with thread support (for interactive approval workflow)."""
    channel_id = config.slack.bucket_channel_id or os.environ.get("SLACK_BUCKET_CHANNEL_ID") or ""
    if not channel_id:
        logger.warning("SLACK_BUCKET_CHANNEL_ID not set; falling back to webhook/log")
        _slack_post_webhook(text, config)
        return

    if not config.slack.bot_token:
        logger.warning("SLACK_BOT_TOKEN not set; falling back to webhook/log")
        _slack_post_webhook(text, config)
        return

    try:
        from slack_sdk import WebClient
        from . import bucket as bucket_mod

        client = WebClient(token=config.slack.bot_token)
        resp = client.chat_postMessage(
            channel=channel_id,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
        )
        ts = resp.get("ts")
        if ts:
            # Store state for thread-based approval workflow
            bucket_mod.set_bucket_thread_state(channel_id, ts, {
                "step": "suggested",
                "work_id": work_id,
                "display_id": display_id,
                "ticket_text": ticket_text,
                "skill_name": skill_name,
            })
            logger.info("Posted to Slack thread: %s (state saved)", display_id)
    except Exception as e:
        logger.warning("Slack bot post failed: %s, falling back", e)
        _slack_post_webhook(text, config)


def _slack_post_webhook(text: str, config):
    """Fallback: Post to Slack webhook (fire-and-forget, no thread support)."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook:
        try:
            import requests
            requests.post(webhook, json={"text": text}, timeout=10)
        except Exception as e:
            logger.warning("Slack webhook failed: %s", e)
        return
    logger.info("Slack (no webhook): %s", text[:200])


def _fetch_my_ticket_ids(config):
    """Fetch work IDs owned by me in open states."""
    from . import devrev_client
    user = devrev_client.get_self()
    user_id = user.get("id")
    if not user_id:
        return []
    ids = []
    cursor = None
    while True:
        data = devrev_client.works_list(
            owned_by=[user_id],
            state=config.monitor.my_tickets_states,
            limit=50,
            cursor=cursor,
        )
        works = data.get("works") or []
        ids.extend([w["id"] for w in works])
        cursor = data.get("next_cursor")
        if not cursor or not works:
            break
    return ids


def _resolve_part_names_to_ids(part_names: list) -> list:
    """Resolve part names to DevRev part IDs via parts.list (name filter). Returns list of part IDs."""
    names = [(n or "").strip() for n in part_names if (n or "").strip()]
    if not names:
        return []
    from . import devrev_client
    part_ids = []
    try:
        # DevRev parts.list accepts name: [list] – returns parts matching any of the names
        data = devrev_client.parts_list(name=names, limit=50)
        for p in (data.get("parts") or []):
            pid = p.get("id")
            if pid:
                part_ids.append(pid)
    except Exception as e:
        logger.warning("Resolving part names %r: %s", names, e)
    return part_ids


def _fetch_new_tickets(config):
    """Fetch new tickets matching filters (parts + state), then filter by stage and unassigned if set."""
    from . import devrev_client
    parts = list(config.monitor.new_ticket_filter_parts or [])
    part_names = getattr(config.monitor, "new_ticket_filter_part_names", None) or []
    if part_names:
        resolved = _resolve_part_names_to_ids(part_names)
        for pid in resolved:
            if pid not in parts:
                parts.append(pid)
    states = config.monitor.new_ticket_states
    stage_names = getattr(config.monitor, "new_ticket_stage_names", None) or []
    unassigned_only = getattr(config.monitor, "new_ticket_unassigned_only", False)
    if not states:
        return []
    out = []
    cursor = None
    while True:
        data = devrev_client.works_list(
            state=states,
            applies_to_part=parts if parts else None,
            limit=50,
            cursor=cursor,
        )
        works = data.get("works") or []
        out.extend(works)
        cursor = data.get("next_cursor")
        if not cursor or not works:
            break
    # Filter by stage name (e.g. "triage") – case-insensitive
    if stage_names:
        stage_set = {s.strip().lower() for s in stage_names if s}
        out = [
            w for w in out
            if ((w.get("stage") or {}).get("name") or "").strip().lower() in stage_set
        ]
    # Filter to unassigned only (no owner)
    if unassigned_only:
        out = [w for w in out if not (w.get("owned_by") or [])]
    return out


def _get_timeline_entry_ids(work_id):
    """Get list of timeline entry IDs for a work (newest first)."""
    from . import devrev_client
    data = devrev_client.timeline_entries_list(work_id, limit=20)
    entries = data.get("timeline_entries") or []
    return [e["id"] for e in entries]


def _get_latest_timeline_entry(work_id):
    """Get the latest timeline entry content for analysis."""
    from . import devrev_client
    data = devrev_client.timeline_entries_list(work_id, limit=5)
    entries = data.get("timeline_entries") or []
    if not entries:
        return None, None
    latest = entries[0]
    entry_id = latest.get("id")
    # Extract text body from entry
    body_parts = latest.get("body_parts") or []
    text = ""
    for part in body_parts:
        if part.get("type") == "text":
            text += part.get("text", "") + "\n"
    return entry_id, text.strip()


def _parse_skill_name(text: str) -> str:
    """Extract skill name from agent response."""
    if not text:
        return "order-trace-debugger"
    import re
    # Try structured format
    m = re.search(r"\*\*skill\s+to\s+run:\*\*\s*([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    # Try legacy format
    m = re.search(r"skill[:\s]+([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    return "order-trace-debugger"


def run_once(config):
    """One monitor run: diff new tickets + my tickets (new replies), post to Slack."""
    from . import devrev_client
    state = _load_state()
    last_new = set(state.get("last_new_ticket_ids") or [])
    last_timeline = state.get("last_timeline_by_work") or {}

    # 1) New tickets (filtered by parts, state, stage, unassigned)
    new_tickets = []
    if config.monitor.new_ticket_states:
        try:
            all_new = _fetch_new_tickets(config)
            for w in all_new:
                wid = w.get("id")
                if wid and wid not in last_new:
                    new_tickets.append(w)
            state["last_new_ticket_ids"] = [w["id"] for w in all_new[:100]]
        except Exception as e:
            logger.exception("Fetch new tickets: %s", e)

    # 2) My tickets – new replies (timeline)
    my_ids = []
    try:
        my_ids = _fetch_my_ticket_ids(config)
    except Exception as e:
        logger.exception("Fetch my tickets: %s", e)

    new_replies = []  # list of (work, latest_entry_id, is_awaiting_info)
    for wid in my_ids:
        try:
            ids_now = _get_timeline_entry_ids(wid)
            prev_ids = last_timeline.get(wid) or []
            if ids_now and (not prev_ids or ids_now[0] != prev_ids[0]):
                new_replies.append((wid, ids_now[0] if ids_now else None))
            last_timeline[wid] = ids_now[:10]
        except Exception as e:
            logger.warning("Timeline for %s: %s", wid, e)

    state["last_timeline_by_work"] = {k: v for k, v in list(last_timeline.items())[:200]}
    state["last_run_ts"] = time.time()
    _save_state(state)

    # Post to Slack: new PSE tickets with AI suggestion (analyze each) - INTERACTIVE
    for w in new_tickets[:10]:
        title = (w.get("title") or "")[:200]
        body = (w.get("body") or "")[:3000]
        work_id = w.get("id")  # Full don:core:... ID
        display_id = w.get("display_id") or work_id
        ticket_text = f"{title}\n\n{body}".strip() or str(display_id)

        try:
            from .agent import reply
            response = reply(ticket_text, config)
            skill_name = _parse_skill_name(response)
            if len(response) > 2800:
                response = response[:2800] + "\n… (truncated)"
        except Exception as e:
            logger.warning("Agent analysis for %s: %s", display_id, e)
            response = f"Could not analyze: {e}"
            skill_name = "order-trace-debugger"

        message_text = (
            f"🆕 *New PSE Ticket (Triage, unassigned)*\n"
            f"*{display_id}* — {title[:80]}\n\n"
            f"{response}\n\n"
            f"—_Reply **Yes** to run the skill, then **Approve** to post resolution and close ticket._"
        )

        _slack_post_interactive(
            text=message_text,
            config=config,
            work_id=work_id,
            display_id=display_id,
            ticket_text=ticket_text,
            skill_name=skill_name,
        )

    # Post to Slack: assigned ticket updates with NEW CONTENT ANALYSIS - INTERACTIVE
    for wid, latest_entry_id in new_replies[:10]:
        try:
            from . import devrev_client
            from .agent import reply

            # Fetch the work to get title and current state
            work_data = devrev_client.works_list(work_ids=[wid], limit=1)
            works = work_data.get("works") or []
            if not works:
                logger.warning("Could not fetch work %s", wid)
                continue

            work = works[0]
            title = (work.get("title") or "")[:200]
            display_id = work.get("display_id") or wid
            stage_name = (work.get("stage") or {}).get("name") or "Unknown"

            # Get the latest timeline entry content
            _, new_content = _get_latest_timeline_entry(wid)
            if not new_content:
                new_content = "(No text content in latest update)"

            # Analyze the UPDATE (not the whole ticket)
            analysis_text = f"Ticket: {title}\nStage: {stage_name}\n\nLatest update:\n{new_content[:1500]}"
            response = reply(analysis_text, config)
            skill_name = _parse_skill_name(response)

            if len(response) > 2800:
                response = response[:2800] + "\n… (truncated)"

            message_text = (
                f"📝 *Assigned Ticket Update*\n"
                f"*{display_id}* — {title[:80]} (Stage: {stage_name})\n\n"
                f"*Latest update:*\n{new_content[:400]}\n\n"
                f"*AI Analysis:*\n{response}\n\n"
                f"—_Reply **Yes** to run the skill, then **Approve** to post resolution._"
            )

            _slack_post_interactive(
                text=message_text,
                config=config,
                work_id=wid,
                display_id=display_id,
                ticket_text=analysis_text,
                skill_name=skill_name,
            )

        except Exception as e:
            logger.exception("Analyze assigned ticket update %s: %s", wid, e)
            # Fallback: simple notification
            _slack_post_webhook(
                f"My ticket update: <https://app.devrev.ai|{wid}> — new reply/activity.",
                config,
            )

    return len(new_tickets), len(new_replies)


def _run_solved_fetch_if_due(config):
    """Run fetch_my_solved.py once per solved_fetch_interval_hours (e.g. once per day)."""
    import subprocess
    import sys
    state = _load_state()
    last_ts = state.get("last_solved_fetch_ts")
    interval_hours = getattr(config.monitor, "solved_fetch_interval_hours", 24.0) or 24.0
    now = time.time()
    if last_ts is not None and (now - last_ts) < interval_hours * 3600:
        return
    script = _BOT_ROOT / "scripts" / "fetch_my_solved.py"
    if not script.exists():
        logger.warning("scripts/fetch_my_solved.py not found; skipping daily solved fetch")
        return
    try:
        logger.info("Running daily solved tickets fetch (once per %.0fh)", interval_hours)
        subprocess.run(
            [sys.executable, str(script)],
            cwd=str(_BOT_ROOT),
            env=os.environ.copy(),
            timeout=120,
            capture_output=True,
        )
        state = _load_state()
        state["last_solved_fetch_ts"] = now
        _save_state(state)
    except Exception as e:
        logger.warning("Daily solved fetch failed: %s", e)


def run_loop(config):
    """Run monitor every interval_minutes until interrupted."""
    while True:
        try:
            # Skip automatic solved tickets fetch - you already have 923 tickets cached
            # Uncomment this if you want to refresh solved tickets daily:
            # _run_solved_fetch_if_due(config)

            run_once(config)
        except Exception as e:
            logger.exception("Monitor run: %s", e)
        time.sleep(max(1, config.monitor.interval_minutes * 60))
