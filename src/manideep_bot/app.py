"""Manideep Bot: Slack Socket Mode.

Two distinct channels:
  watch_channel (C084W9R9T3J / #engage-production-issues)
    → Listens for new DevRev ticket notifications posted by DevRev itself.
    → Extracts ISS-XXXXXX from the message text OR Slack blocks.
    → Fetches the full ticket from DevRev in ONE API call (no pagination).
    → If the ticket is unassigned (owned by SVCACC-2): auto-assigns to Manideep immediately.
    → Posts AI analysis + skill suggestion as a THREAD REPLY (keeps the channel clean).
    → You reply "Yes" in the thread → skill runs; "Approve" → posts resolution + closes ticket.

  bucket_channel (C0AHL6C343V / your private bot channel)
    → Bot proactively posts updates about tickets already assigned to you.
    → New replies on your tickets, ticket stage changes, daily summary, etc.
    → Same Yes/Approve workflow to run skills and close tickets.
"""
import logging
import os
import re

from .config import load_config
from .agent import reply
from .enhanced_agent import enhanced_reply
from .claude_code_agent import claude_code_reply

logger = logging.getLogger(__name__)

# Per-thread state: (channel_id, thread_ts) -> dict
_thread_state = {}

# Skills safe to auto-run when ticket arrives (no "Yes" needed).
# These are read-only or reversible — output is reviewed before closing.
# Destructive skills (gc-cancellation, rmp-gandalf) are NOT here → always manual.
_AUTO_RUN_SKILLS = {
    "gc-redemption-report",
    "order-trace-debugger",
    "vishnu-terraform-kong-pr",
    "invalid-rewards-debugger",
}

# ── DevRev PSE dropdown enums (from ctype__custom_type_fragment/17305) ───────
_CAUSE_CODES = [
    "Caused by Incident",
    "Config Change",
    "Dev Intervention - Code Debugging",
    "Dev Intervention - Code Fix",
    "Dev Intervention - Data Fix",
    "Dev Intervention - Log/Tech Issue",
    "Dev Intervention - Product Bug",
    "Issue due to Internal stakeholder teams",
    "Issue due to externals partners",
    "No Response from Merchant/Business Teams",
    "Not via Standard Channel",
    "PSE - Code Debugging",
    "PSE - Code Fix",
    "PSE - Data Fix",
    "PSE - Level-2 Issue(Invalid PSE Involvement)",
    "PSE - Log/Tech Issue",
    "PSE - Product Bug",
    "Product Intervention - New Enhancement",
]

_BREACH_REASONS = [
    "SLA Not Breached",
    "Breached by Engineering",
    "Breached by PSE",
    "Delay Response from Merchant",
    "Delay from Gateway / Bank / NPCI",
    "Delay from Internal Teams",
    "Delay in Deployment / PR / Approvals",
    "Incorrect Priority / Severity by TS",
    "Priority / Severity Upgraded",
    "Ticket Reopened",
]


def _numbered_list(items: list) -> str:
    return "\n".join(f"{i+1}. {v}" for i, v in enumerate(items))


def _pick_from_list(text: str, options: list) -> str:
    """
    Match user input to an option list. Accepts:
      - a number (1-based index)
      - a partial case-insensitive string match
    Returns the matched option string or "" if no match.
    """
    text = text.strip()
    if not text or text.lower() in ("skip", "-", "none", "n/a"):
        return ""
    # Try numeric selection
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(options):
            return options[idx]
        return ""
    # Partial string match (case-insensitive)
    tl = text.lower()
    for opt in options:
        if tl == opt.lower():
            return opt
    for opt in options:
        if tl in opt.lower():
            return opt
    return ""


def _thread_key(event):
    ch = event.get("channel", "")
    ts = event.get("thread_ts") or event.get("ts", "")
    return (ch, ts)


def _normalize_approve(text):
    t = (text or "").strip().lower()
    if t in ("yes", "proceed", "y", "go", "run it", "done"):
        return "yes"
    if t in ("approve", "approved", "close it", "post and close"):
        return "approve"
    return None


def _parse_work_id_from_event(event: dict):
    """
    Extract ISS-XXXXXX / TKT-XXXXXX from a Slack event.
    Checks:
      1. Message text
      2. Attachment text / fallback
      3. Block IDs (DevRev posts block_id = 'devrev-view-title-ISS-XXXXXX')
      4. Block text fields (rich_text sections, etc.)
    Returns the display_id string or None.
    """
    # We only deal with ISS issues; TKT tickets are out of our scope
    pattern = re.compile(r"\b(ISS|ISSUE)-(\d+)\b", re.I)

    def _search(s):
        if not s:
            return None
        m = pattern.search(str(s))
        return m.group(0) if m else None

    # 1. Direct text
    found = _search(event.get("text"))
    if found:
        return found

    # 2. Attachments
    for att in (event.get("attachments") or []):
        found = _search(att.get("text")) or _search(att.get("fallback")) or _search(att.get("pretext"))
        if found:
            return found

    # 3 & 4. Blocks (DevRev uses block_id like 'devrev-view-title-ISS-1659563')
    for block in (event.get("blocks") or []):
        found = _search(block.get("block_id"))
        if found:
            return found
        # Rich-text / section elements
        for element in (block.get("elements") or block.get("fields") or []):
            if isinstance(element, dict):
                found = _search(element.get("text")) or _search(element.get("block_id"))
                if found:
                    return found
                # Nested elements inside rich_text_section
                for sub in (element.get("elements") or []):
                    if isinstance(sub, dict):
                        found = _search(sub.get("text")) or _search(sub.get("url"))
                        if found:
                            return found

    # 5. DevRev URL in text (https://app.devrev.ai/razorpay/issue/ISS-1659563)
    url_m = re.search(r"devrev\.ai/[^/\s]+/[^/\s]+/([A-Za-z]+-\d+)", event.get("text") or "")
    if url_m:
        return url_m.group(1)

    return None


def _parse_work_id(text):
    """Extract ISS-XXXXXX display_id from plain text (used in mention / thread reply context)."""
    if not text:
        return None
    m = re.search(r"\b(ISS|ISSUE)-(\d+)\b", text, re.I)
    if m:
        return m.group(0)
    m = re.search(r"devrev\.ai/[^/\s]+/[^/\s]+/([A-Z]+-\d+)", text, re.I)
    if m:
        return m.group(1)
    return None


def _parse_skill_name(text):
    if not text:
        return None
    m = re.search(r"\*\*skill\s+to\s+run:\*\*\s*([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"skill[:\s]+([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    return None


def _parse_close_command(text: str):
    """Detect 'close ISS-XXXXXX' command. Returns display_id (uppercase) or None."""
    if not text:
        return None
    m = re.match(r"^close\s+((?:ISS|ISSUE)-\d+)\b", text.strip(), re.I)
    if m:
        return m.group(1).upper().replace("ISSUE-", "ISS-")
    return None


def _extract_field(text: str, *patterns) -> str:
    """Extract a value from a structured reply using one or more regex patterns."""
    for pattern in patterns:
        m = re.search(pattern, text, re.I | re.MULTILINE)
        if m:
            for g in (m.groups() or []):
                if g and g.strip():
                    return g.strip()
    return ""


def _is_unassigned(work: dict, svcacc_id: str) -> bool:
    """
    Return True if the ticket is effectively unassigned.
    DevRev sets owned_by = [SVCACC-2] for tickets with no real owner.
    Also treats empty owned_by as unassigned.
    """
    owners = work.get("owned_by") or []
    if not owners:
        return True
    owner_ids = [
        (o.get("id") if isinstance(o, dict) else str(o))
        for o in owners
    ]
    # If the only owner is SVCACC-2, it's unassigned
    if svcacc_id and all(oid == svcacc_id for oid in owner_ids):
        return True
    return False


def _get_analysis(ticket_text: str, config, ticket_id: str = None, channel: str = None, thread_ts: str = None):
    """
    Get ticket analysis using the best available method:
    1. If ANTHROPIC_API_KEY set → use enhanced_reply (Claude API) - returns str
    2. Otherwise → use claude_code_reply (local Claude Code analysis) - returns (str, timestamp)

    Returns:
        - If API key: str (analysis message)
        - If Claude Code: tuple (message, timestamp)
    """
    has_api_key = bool(getattr(config.anthropic, "api_key", None))

    if has_api_key:
        logger.debug("Using enhanced_reply (Anthropic API)")
        return enhanced_reply(ticket_text, config)
    else:
        logger.info("No API key - using Claude Code local analysis")
        return claude_code_reply(ticket_text, config, ticket_id, channel, thread_ts)


def _handle_close_request(display_id: str, event: dict, say, config, thread_key: tuple):
    """
    Start the close-ticket flow. Fetches the ticket, shows current values and
    numbered dropdown menus for cause_code + breach_reason, then waits for reply.
    """
    thread_ts = event.get("thread_ts") or event.get("ts")

    from . import devrev_client
    say(text=f":hourglass_flowing_sand: Fetching `{display_id}`...", thread_ts=thread_ts)
    work = devrev_client.get_work_by_display_id(display_id)
    if not work:
        say(text=f":x: Could not find ticket `{display_id}` in DevRev.", thread_ts=thread_ts)
        return

    work_id = work.get("id", "")
    title = (work.get("title") or "")[:120]
    stage = ((work.get("stage") or {}).get("name") or "unknown")
    current_tags = devrev_client.get_tags_from_work(work)
    tag_names_str = ", ".join(f"`{t['name']}`" for t in current_tags) if current_tags else "_none_"

    # Show current values if already set
    cf = devrev_client.get_custom_fields_from_work(work)
    current_cause = cf.get("ctype__cause_code", "")
    current_breach = cf.get("ctype__reason_for_breach", "")

    prompt = (
        f":memo: Closing *{display_id}* — _{title}_\n"
        f"Stage: `{stage}` → `{config.devrev.closed_stage_name}` | Tags: {tag_names_str}\n"
        f"Current cause code: `{current_cause or 'not set'}` | Breach reason: `{current_breach or 'not set'}`\n\n"
        f"*Cause Code* (pick a number or type partial name, or `skip`):\n"
        f"```\n{_numbered_list(_CAUSE_CODES)}\n```\n\n"
        f"*Breach Reason* (pick a number or type partial name, or `skip`):\n"
        f"```\n{_numbered_list(_BREACH_REASONS)}\n```\n\n"
        f"Reply with:\n"
        f"```\n"
        f"cause_code: <number or name>\n"
        f"breach_reason: <number or name>\n"
        f"tags: tag1, tag2\n"
        f"note: Short resolution note\n"
        f"```\n"
        f"All fields optional. Reply `confirm` to close with current values + `bot_resolved` tag."
    )
    say(text=prompt, thread_ts=thread_ts)

    _thread_state[thread_key] = {
        "step": "awaiting_close_info",
        "work_id": work_id,
        "display_id": display_id,
        "title": title,
        "current_cause": current_cause,
        "current_breach": current_breach,
    }


def run_slack_bot():
    config = load_config()
    if not config.slack.bot_token or not config.slack.app_token:
        logger.error("Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
        raise SystemExit(1)

    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        logger.error("Install: pip install slack-bolt slack-sdk")
        raise SystemExit(1)

    app = App(token=config.slack.bot_token)

    from .response_watcher import start_response_watcher, save_thread_mapping
    start_response_watcher(app.client)

    watch_ch = (config.slack.watch_channel_id or "").strip()
    bucket_ch = (config.slack.bucket_channel_id or "").strip()
    my_user_id = (config.devrev.my_user_id or "").strip()
    svcacc_id = (config.devrev.unassigned_svcacc_id or "").strip()

    logger.info(
        "Bot config — watch_channel: %s | bucket_channel: %s | my_user_id: %s",
        watch_ch or "(none)",
        bucket_ch or "(none)",
        my_user_id or "(not set — auto-assign disabled)",
    )

    # ── Mention handler ──────────────────────────────────────────────────────

    def handle_mention(event, say, client):
        thread_ts = event.get("thread_ts") or event.get("ts")
        user_id = event.get("user", "")
        text = re.sub(r"<@\w+>", "", (event.get("text") or "")).strip()

        if config.slack.allowed_user_ids and user_id not in config.slack.allowed_user_ids:
            say(text="You are not allowed to use this bot.", thread_ts=thread_ts)
            return

        if not text:
            from .commands import get_commands_help
            say(text=get_commands_help(), thread_ts=thread_ts)
            return

        from .commands import get_command_id, is_bot_command, run_command
        if is_bot_command(text):
            cmd_id = get_command_id(text)
            say(text="Running...", thread_ts=thread_ts)
            reply_text = run_command(cmd_id, config)
            say(text=reply_text, thread_ts=thread_ts)
            return

        # ── Close command: @bot close ISS-XXXXXX ─────────────────────────────
        close_id = _parse_close_command(text)
        if close_id:
            _handle_close_request(close_id, event, say, config, _thread_key(event))
            return

        say(text=":hourglass_flowing_sand: Analysing...", thread_ts=thread_ts)
        try:
            channel = event.get("channel")
            ticket_id = _parse_work_id(text)
            result = _get_analysis(text, config, ticket_id, channel, thread_ts)

            if isinstance(result, tuple):
                response, returned_ticket_id = result
                if returned_ticket_id:
                    save_thread_mapping(returned_ticket_id, channel, thread_ts)
                say(text=response, thread_ts=thread_ts)
            else:
                response = result
                from .response_watcher import _post_formatted
                _post_formatted(app.client, channel, thread_ts, ticket_id or "ticket", response)

            key = _thread_key(event)
            display_id = _parse_work_id(text)
            from . import devrev_client
            work_id = devrev_client.display_id_to_work_id(display_id) if display_id else None
            _thread_state[key] = {
                "step": "suggested",
                "ticket_text": text,
                "work_id": work_id,
                "display_id": display_id,
                "skill_name": _parse_skill_name(response) or "order-trace-debugger",
            }
        except Exception as e:
            logger.exception("Agent error")
            say(text=f"Error: {e}", thread_ts=thread_ts)

    # ── Thread reply handler ─────────────────────────────────────────────────

    def handle_message(event, say, client):
        thread_ts = event.get("thread_ts")
        if not thread_ts:
            return
        ch = event.get("channel", "")
        key = (ch, thread_ts)
        state = _thread_state.get(key)
        from . import bucket as bucket_mod
        if not state:
            state = bucket_mod.get_thread_state_from_bucket(ch, thread_ts)
            is_bucket = bool(state)
        else:
            is_bucket = False
        if not state:
            return

        text = (event.get("text") or "").strip()
        cmd = _normalize_approve(text)

        # ── Close-ticket flow ─────────────────────────────────────────────────
        if state.get("step") == "awaiting_close_info":
            work_id = state.get("work_id", "")
            display_id = state.get("display_id", "")

            # Parse structured fields from the reply
            tags_raw = _extract_field(text,
                r"^tags?[\s:：]+(.+)$",
                r"tags?[\s:：]+(.+)")
            cause_raw = _extract_field(text,
                r"^cause_?code[\s:：]+(.+)$",
                r"cause_?code[\s:：]+(.+)")
            breach_raw = _extract_field(text,
                r"^breach_?reason[\s:：]+(.+)$",
                r"^reason_?for_?breach[\s:：]+(.+)$",
                r"^breach[\s:：]+(.+)$",
                r"breach_?reason[\s:：]+(.+)")
            note = _extract_field(text,
                r"^note[\s:：]+(.+)$",
                r"note[\s:：]+(.+)")

            # Resolve dropdown selections (number or partial string)
            cause_code = _pick_from_list(cause_raw, _CAUSE_CODES) if cause_raw else state.get("current_cause", "")
            breach_reason = _pick_from_list(breach_raw, _BREACH_REASONS) if breach_raw else state.get("current_breach", "")

            # Build tag list
            from . import devrev_client as dc
            extra_tags = []
            if tags_raw:
                for t in [x.strip() for x in re.split(r"[,;]", tags_raw) if x.strip()]:
                    extra_tags.append({"name": t, "value": ""})
            tags_to_add = dc.build_tags_for_closure(extra_tags=extra_tags)

            # Custom fields — ctype__ fields go into the custom_fields nested dict via works.update
            custom_fields = {}
            if cause_code:
                custom_fields["ctype__cause_code"] = cause_code
            if breach_reason:
                custom_fields["ctype__reason_for_breach"] = breach_reason

            # Warn if neither field resolved from input
            if cause_raw and not cause_code:
                say(text=f":warning: `{cause_raw}` didn't match any cause code — skipping. Reply `close {display_id}` to retry.", thread_ts=thread_ts)
            if breach_raw and not breach_reason:
                say(text=f":warning: `{breach_raw}` didn't match any breach reason — skipping. Reply `close {display_id}` to retry.", thread_ts=thread_ts)

            # Resolution comment
            summary = note or "Ticket closed via Manideep Bot close command."
            resolution_comment = dc.build_resolution_comment(summary=summary)

            try:
                dc.work_update_full(
                    work_id=work_id,
                    stage_name=config.devrev.closed_stage_name,
                    tags_to_add=tags_to_add,
                    comment=resolution_comment,
                    custom_fields=custom_fields if custom_fields else None,
                )

                from .monitor import append_solved_ticket_after_approve
                append_solved_ticket_after_approve(config, work_id)

                tag_names = [t["name"] for t in tags_to_add]
                confirm_parts = [
                    f":white_check_mark: *{display_id}* closed — stage set to `{config.devrev.closed_stage_name}`.",
                    f"*Tags:* {', '.join(f'`{t}`' for t in tag_names)}" if tag_names else "",
                    f"*Cause code:* `{cause_code}`" if cause_code else "",
                    f"*Breach reason:* `{breach_reason}`" if breach_reason else "",
                    f"*Note posted:* _{note}_" if note else "",
                ]
                say(text="\n".join(p for p in confirm_parts if p), thread_ts=thread_ts)
            except Exception as e:
                logger.exception("Close ticket failed for %s", display_id)
                say(text=f":x: Failed to close `{display_id}`: {e}", thread_ts=thread_ts)

            if is_bucket:
                bucket_mod.pop_bucket_thread_state(ch, thread_ts)
            else:
                _thread_state.pop(key, None)
            return

        if cmd == "yes" and state.get("step") == "suggested":
            from . import skill_runner
            ticket_text = state.get("ticket_text") or ""
            skill_name = state.get("skill_name") or "order-trace-debugger"
            out, ok = skill_runner.run_skill(skill_name, ticket_text)
            if not ok:
                say(text=f"Could not run skill: {out}\nReply **Done** again after adding missing info (e.g. order_id).", thread_ts=thread_ts)
                return
            say(
                text=f"Work done. Output:\n```\n{out[:2500]}\n```\n\nReview. If correct, reply **Approve** to post this on the ticket and close it.",
                thread_ts=thread_ts,
            )
            state["step"] = "pending_approve"
            state["output"] = out
            state["summary"] = out[:500]
            if is_bucket:
                bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
            else:
                _thread_state[key] = state
            return

        if state.get("step") == "pending_approve" and not state.get("work_id"):
            wid = _parse_work_id(text)
            if wid:
                state["work_id"] = state.get("work_id") or wid
                state["display_id"] = wid
                if is_bucket:
                    bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
                else:
                    _thread_state[key] = state
                say(text=f"Got ticket ID: {wid}. Reply **Approve** to post the resolution and close it.", thread_ts=thread_ts)
                return

        if cmd == "approve" and state.get("step") == "pending_approve":
            work_id = state.get("work_id")
            if not work_id:
                say(
                    text="I don't have the ticket ID. Please paste the DevRev work ID (e.g. ISS-123) so I can post the update and close it.",
                    thread_ts=thread_ts,
                )
                return
            try:
                from . import devrev_client
                from .monitor import append_solved_ticket_after_approve
                from .claude_code_agent import load_similar_data

                summary = state.get("summary") or state.get("output") or "Resolved by Manideep Bot."
                skill_name = (state.get("skill_name") or "").strip()
                display_id = state.get("display_id") or ""

                # Load similar ticket data (tags + fields saved during analysis)
                similar_data = load_similar_data(display_id) if display_id else {}
                similar_tags = similar_data.get("suggested_tags") or []
                similar_fields = similar_data.get("suggested_fields") or {}
                similar_tickets = similar_data.get("similar_tickets") or []
                best_similar_id = similar_tickets[0].get("display_id", "") if similar_tickets else ""

                # 1. Build structured resolution comment
                resolution_comment = devrev_client.build_resolution_comment(
                    summary=summary,
                    skill_name=skill_name,
                    similar_ticket_id=best_similar_id,
                )

                # 2. Build tags: similar ticket tags + skill tag + bot_resolved
                tags_to_add = devrev_client.build_tags_for_closure(
                    skill_name=skill_name,
                    similar_ticket_tags=similar_tags,
                )

                # 3. Comprehensive update: comment + tags + stage + custom fields
                devrev_client.work_update_full(
                    work_id=work_id,
                    stage_name=config.devrev.closed_stage_name,
                    tags_to_add=tags_to_add,
                    comment=resolution_comment,
                    custom_fields=similar_fields if similar_fields else None,
                )

                append_solved_ticket_after_approve(config, work_id)

                # Build Slack confirmation with details
                tag_names = [t["name"] for t in tags_to_add]
                confirm_parts = [
                    f"Posted resolution on ticket and set stage to *{config.devrev.closed_stage_name}*.",
                    f"Tags added: {', '.join(f'`{t}`' for t in tag_names)}" if tag_names else "",
                    f"Similar ticket referenced: `{best_similar_id}`" if best_similar_id else "",
                    "Done.",
                ]
                say(text="\n".join(p for p in confirm_parts if p), thread_ts=thread_ts)
            except Exception as e:
                logger.exception("DevRev post/close: %s", e)
                say(text=f"Failed to post/close: {e}", thread_ts=thread_ts)
            if is_bucket:
                bucket_mod.pop_bucket_thread_state(ch, thread_ts)
            else:
                _thread_state.pop(key, None)
            return

    # ── New-issue notification handler ───────────────────────────────────────

    def handle_new_issue_notification(event, say, client):
        """
        Watches #engage-production-issues (watch_channel_id) for new DevRev ticket posts.

        Flow:
          1. Extract ISS-XXXXXX from message text OR blocks (handles all DevRev message formats).
          2. Fetch ticket from DevRev in a SINGLE API call (fast path: construct DON ID directly).
          3. If unassigned (owned by SVCACC-2 or empty): auto-assign to Manideep immediately.
          4. Post AI analysis as a thread reply — channel stays clean for everyone else.
          5. Yes/Approve flow works in that thread.
        """
        ch = event.get("channel", "")
        target_ch = (config.slack.watch_channel_id or config.slack.bucket_channel_id or "").strip()
        if not target_ch or ch != target_ch:
            return False
        # Only react to top-level posts (not replies in existing threads)
        if event.get("thread_ts"):
            return False
        # Skip messages from bots that are not DevRev (don't recurse on our own replies)
        bot_id = event.get("bot_id") or ""
        subtype = event.get("subtype") or ""
        # Allow bot messages (DevRev posts as a bot), but not message_changed / message_deleted
        if subtype in ("message_changed", "message_deleted", "bot_remove", "bot_add"):
            return False

        display_id = _parse_work_id_from_event(event)
        if not display_id:
            logger.debug("watch_channel message has no ISS/TKT ID — skipping (bot_id=%s)", bot_id)
            return False

        from . import devrev_client
        from . import bucket as bucket_mod

        # FAST: single API call using constructed DON ID
        work = devrev_client.get_work_by_display_id(display_id)
        if not work:
            logger.warning("Could not fetch %s from DevRev — skipping", display_id)
            return True  # don't spam the global channel with errors

        work_id = work.get("id", "")
        title = (work.get("title") or "")[:200]
        body = (work.get("body") or "")[:3000]
        ticket_text = f"{title}\n\n{body}".strip() or str(display_id)
        msg_ts = event.get("ts")

        # ── Auto-assign if unassigned ──────────────────────────────────────
        assigned_now = False
        skip_reason = None
        if my_user_id and _is_unassigned(work, svcacc_id):
            # Check if user already has too many tickets
            try:
                current_count = devrev_client.count_open_tickets_for_user(my_user_id)
                if current_count >= 15:
                    skip_reason = f"Already have {current_count} open tickets (limit: 15)"
                    logger.info("Skipping auto-assign for %s: %s", display_id, skip_reason)
                else:
                    devrev_client.work_assign(work_id, my_user_id)
                    assigned_now = True
                    logger.info("Auto-assigned %s to Manideep (%s) — now %d tickets", display_id, my_user_id, current_count + 1)
            except Exception as e:
                logger.error("Auto-assign failed for %s: %s", display_id, e)

        # ── AI analysis → post to YOUR private bucket channel only ──────────
        # Zero messages in the watch channel. Just silent auto-assign above.
        if not bucket_ch:
            logger.warning("bucket_channel_id not set — cannot post analysis for %s", display_id)
            return True

        try:
            from .response_watcher import _post_formatted

            app_base = getattr(config.devrev, "app_base_url", None) or "https://app.devrev.ai"
            ticket_url = f"{app_base}/razorpay/issue/{display_id}"
            if assigned_now:
                status_line = ":white_check_mark: Auto-assigned to you"
            elif skip_reason:
                status_line = f":no_entry_sign: Not assigned: {skip_reason}"
            else:
                status_line = "_(already assigned)_"

            # 1. Post ticket notification (top-level message in bucket channel)
            notify_result = client.chat_postMessage(
                channel=bucket_ch,
                text=f"{display_id} — {title[:80]}",
                attachments=[{
                    "color": "#0052CC",
                    "title": f"{display_id} — {title[:80]}",
                    "title_link": ticket_url,
                    "text": status_line,
                    "footer": "DevRev · PSE",
                }],
            )
            posted_ts = notify_result["ts"]

            # 2. Get analysis
            result = _get_analysis(ticket_text, config, display_id)

            ticket_timestamp = None
            if isinstance(result, tuple):
                response, ticket_timestamp = result
            else:
                response = result

            skill_name = _parse_skill_name(response) or "order-trace-debugger"

            if ticket_timestamp:
                save_thread_mapping(ticket_timestamp, bucket_ch, posted_ts)
            else:
                _post_formatted(client, bucket_ch, posted_ts, display_id, response)

            # ── Auto-run safe skills immediately (no "Yes" needed) ────────────
            if skill_name in _AUTO_RUN_SKILLS:
                logger.info("Auto-running skill '%s' for %s", skill_name, display_id)
                client.chat_postMessage(
                    channel=bucket_ch,
                    thread_ts=posted_ts,
                    text=f":robot_face: *Auto-running* `{skill_name}` — no approval needed for this skill...",
                )
                from . import skill_runner
                out, ok = skill_runner.run_skill(skill_name, ticket_text)
                if ok:
                    client.chat_postMessage(
                        channel=bucket_ch,
                        thread_ts=posted_ts,
                        text=(
                            f":white_check_mark: Skill `{skill_name}` completed.\n"
                            f"```\n{out[:2500]}\n```\n\n"
                            f"Review the output above. Reply *Approve* to post this on the ticket and close it, "
                            f"or *No* to cancel."
                        ),
                    )
                    bucket_mod.set_bucket_thread_state(bucket_ch, posted_ts, {
                        "step": "pending_approve",
                        "work_id": work_id,
                        "display_id": display_id,
                        "ticket_text": ticket_text,
                        "skill_name": skill_name,
                        "output": out,
                        "summary": out[:500],
                    })
                else:
                    # Skill failed (e.g. missing card number) — fall back to manual
                    client.chat_postMessage(
                        channel=bucket_ch,
                        thread_ts=posted_ts,
                        text=(
                            f":warning: Auto-run failed: {out}\n\n"
                            f"Please reply *Yes* after adding the missing info to run manually."
                        ),
                    )
                    bucket_mod.set_bucket_thread_state(bucket_ch, posted_ts, {
                        "step": "suggested",
                        "work_id": work_id,
                        "display_id": display_id,
                        "ticket_text": ticket_text,
                        "skill_name": skill_name,
                    })
            else:
                # Manual skill — wait for "Yes"
                bucket_mod.set_bucket_thread_state(bucket_ch, posted_ts, {
                    "step": "suggested",
                    "work_id": work_id,
                    "display_id": display_id,
                    "ticket_text": ticket_text,
                    "skill_name": skill_name,
                })

            logger.info(
                "Processed %s in bucket channel %s (skill=%s, auto=%s, assigned=%s)",
                display_id, bucket_ch, skill_name,
                skill_name in _AUTO_RUN_SKILLS, assigned_now,
            )
        except Exception as e:
            logger.exception("Notification handler error for %s: %s", display_id, e)
        return True

    # ── Register handlers ────────────────────────────────────────────────────

    @app.event("app_mention")
    def on_mention(event, say, client):
        handle_mention(event, say, client)

    @app.event("message")
    def on_message(event, say, client):
        if handle_new_issue_notification(event, say, client):
            return
        if event.get("bot_id"):
            return
        handle_message(event, say, client)

    handler = SocketModeHandler(app, config.slack.app_token)
    logger.info(
        "Manideep Bot starting (Socket Mode) | watch=%s | bucket=%s | auto-assign=%s",
        watch_ch or "none",
        bucket_ch or "none",
        "ON" if my_user_id else "OFF (set DEVREV_MY_USER_ID)",
    )
    handler.start()


def run():
    from pathlib import Path
    try:
        from dotenv import load_dotenv
        _root = Path(__file__).resolve().parent.parent.parent
        load_dotenv(_root / "scripts" / ".env")
    except ImportError:
        pass
    env = os.environ.get("APP_ENV", "dev")
    logging.basicConfig(
        level=logging.DEBUG if env == "dev" else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    logger.info("Loading config and starting Manideep Bot...")
    try:
        run_slack_bot()
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("Bot failed to start: %s", e)
        raise


if __name__ == "__main__":
    run()
