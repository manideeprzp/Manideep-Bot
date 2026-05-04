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
import time

from .config import load_config
from .agent import reply
from .enhanced_agent import enhanced_reply
from .claude_code_agent import claude_code_reply

logger = logging.getLogger(__name__)

# Per-thread state: (channel_id, thread_ts) -> dict
_thread_state = {}

# Persist thread state to disk so restarts don't lose it
import json as _json
from pathlib import Path as _Path
_STATE_FILE = _Path(__file__).resolve().parents[2] / "data" / "thread_state.json"


def _load_persisted_state():
    """Load thread state from disk on startup."""
    try:
        if _STATE_FILE.exists():
            raw = _json.loads(_STATE_FILE.read_text())
            # Keys are stored as "channel::thread_ts" strings, convert back to tuples
            return {tuple(k.split("::", 1)): v for k, v in raw.items()}
    except Exception:
        pass
    return {}


def _save_persisted_state():
    """Save current thread state to disk."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        serializable = {"::".join(k): v for k, v in _thread_state.items()}
        _STATE_FILE.write_text(_json.dumps(serializable, indent=2))
    except Exception as e:
        logger.warning("Could not save thread state: %s", e)


def _set_state(key, state):
    """Update in-memory thread state AND persist to disk immediately."""
    _thread_state[key] = state
    _save_persisted_state()


# Load persisted state on startup
_thread_state.update(_load_persisted_state())


def set_thread_state_from_analysis(channel: str, thread_ts: str, ticket_id: str, content: str, ticket_text: str = ""):
    """Called by response_watcher after posting an analysis, so 'yes' replies work correctly."""
    skill = _parse_skill_name(content) or "none"
    key = (channel, thread_ts)
    _thread_state[key] = {
        "step": "suggested",
        "skill_name": skill,
        "display_id": ticket_id,
        "ticket_text": ticket_text,
        "channel": channel,
        "thread_ts": thread_ts,
    }
    _save_persisted_state()
    logger.info("Thread state set for %s: skill=%s", ticket_id, skill)

# Skills safe to auto-run when ticket arrives (no "Yes" needed).
# These are read-only or reversible — output is reviewed before closing.
# Destructive skills (gc-cancellation, rmp-gandalf) are NOT here → always manual.
_AUTO_RUN_SKILLS = {
    "gc-redemption-report",
    "order-trace-debugger",
    "vishnu-terraform-kong-pr",
    "invalid-rewards-debugger",
    "github-pr",  # Read-only: fetch PR details / list PRs
    "wallet-closure",  # Wallet closure via Claude Code CLI
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
    # Strip Slack MCP footer: "yes *Sent using* <@U...>" → "yes"
    t = re.sub(r"\s*\*sent using\*.*$", "", t).strip()
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
    # Pattern 1: **Skill to run:** `gc-redemption-report` (response file format)
    m = re.search(r"\*\*skill\s+to\s+run:\*\*\s*`*([a-z0-9-]+)`*", text, re.I)
    if m:
        val = m.group(1).strip().strip("`")
        return val if val and val != "none" else None
    # Pattern 2: *Skill:*  `order-trace-debugger` (Slack attachment format from _build_attachments)
    m = re.search(r"\*skill:\*\s*`+([a-z0-9-]+)`+", text, re.I)
    if m:
        val = m.group(1).strip().strip("`")
        return val if val and val != "none" else None
    # Pattern 3: Skill: `order-trace-debugger` or Skill: order-trace-debugger (plain text)
    m = re.search(r"^skill:\s*`*([a-z0-9-]+)`*$", text, re.I | re.M)
    if m:
        val = m.group(1).strip().strip("`")
        return val if val and val != "none" else None
    return None


_KNOWN_SKILLS = {
    "gc-redemption-report", "gc-cancellation", "cancel-gc",
    "order-trace-debugger", "vishnu-terraform-kong-pr", "vishnu-kong-pr",
    "kong-pr", "dns-pr", "github-pr", "voucher-benefit-upload",
    "invalid-rewards-debugger", "rmp-gandalf", "wallet-closure",
}


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


_STATUS_UPDATE_COOLDOWN = 4 * 3600  # 4 hours in seconds


def _update_existing_threads(has_thread_works: list, slack_client, bucket_ch: str, config):
    """
    For assigned tickets that ALREADY have a Slack thread:
      - If ticket body changed → re-detect skill, post re-analysis
      - Else → post status update (stage, age, SLA) if >4h since last
    Returns count of tickets updated.
    """
    from . import bucket as bucket_mod
    from .enhanced_agent import detect_skill as _detect_skill
    from .scripts_utils import build_inline_analysis
    from .response_watcher import _post_formatted
    import time as _time
    from datetime import datetime, timezone

    updated = 0
    now = _time.time()

    for w in has_thread_works:
        display_id = w.get("display_id") or w.get("id", "")
        thread_info = bucket_mod.get_ticket_thread(display_id)
        if not thread_info:
            continue

        channel = thread_info.get("channel", bucket_ch)
        thread_ts = thread_info.get("thread_ts", "")
        stored_hash = thread_info.get("last_body_hash", "")
        last_status_ts = thread_info.get("last_status_update_ts", 0.0)

        title = (w.get("title") or "")[:200]
        body = (w.get("body") or "")[:3000]
        current_hash = bucket_mod.get_body_hash(title, body)
        ticket_text = f"{title}\n\n{body}".strip()

        try:
            if stored_hash and current_hash != stored_hash:
                # ── Body changed → re-analyze ──────────────────────────────
                skill_name, confidence = _detect_skill(ticket_text)
                skill_name = skill_name or "none"

                slack_client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=":arrows_counterclockwise: *Ticket updated* — re-analyzing with new content...",
                )

                response = build_inline_analysis(ticket_text, display_id, skill_name, confidence)
                _post_formatted(slack_client, channel, thread_ts, display_id, response)

                # Update bucket thread state with new skill
                bucket_mod.set_bucket_thread_state(channel, thread_ts, {
                    "step": "suggested",
                    "work_id": w.get("id", ""),
                    "display_id": display_id,
                    "ticket_text": ticket_text,
                    "skill_name": skill_name,
                })
                bucket_mod.update_ticket_thread_fields(
                    display_id,
                    last_body_hash=current_hash,
                    last_status_update_ts=now,
                )
                updated += 1
                logger.info("Re-analyzed %s (body changed)", display_id)

            elif (now - last_status_ts) > _STATUS_UPDATE_COOLDOWN:
                # ── No body change, cooldown passed → status update ────────
                stage_name = (w.get("stage") or {}).get("name") or "Unknown"
                priority = "P" + str((w.get("priority_v2") or {}).get("id", "?"))
                if priority == "P?":
                    priority = "Unknown"

                # Compute age
                created_date = w.get("created_date") or ""
                if created_date:
                    try:
                        created_dt = datetime.fromisoformat(created_date.replace("Z", "+00:00"))
                        age_days = (datetime.now(timezone.utc) - created_dt).days
                        age_str = f"{age_days}d"
                    except Exception:
                        age_str = "?"
                else:
                    age_str = "?"

                # SLA
                sla_summary = w.get("sla_summary") or {}
                sla_stage = sla_summary.get("stage") or "unknown"

                slack_client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=(
                        f":bar_chart: *Status update* — `{display_id}`\n"
                        f"Stage: `{stage_name}` | Age: {age_str} | "
                        f"SLA: `{sla_stage}` | Priority: `{priority}`"
                    ),
                )
                bucket_mod.update_ticket_thread_fields(
                    display_id,
                    last_body_hash=current_hash,
                    last_status_update_ts=now,
                )
                updated += 1
                logger.info("Status update for %s (stage=%s)", display_id, stage_name)
            else:
                # Update hash silently (first time or no change + cooldown not passed)
                if not stored_hash:
                    bucket_mod.update_ticket_thread_fields(display_id, last_body_hash=current_hash)
                logger.debug("Skipped %s — no change, cooldown not passed", display_id)

        except Exception as e:
            logger.error("Failed to update thread for %s: %s", display_id, e)

    return updated


def _handle_check(event: dict, say, config, slack_client=None):
    """
    Handle '@bot check' from Slack — two actions:
    1. Process all pending claude_requests (unassigned tickets queued for analysis)
    2. Surface assigned tickets that have no Slack thread yet (create one per ticket)
    Everything stays in Slack. No new Claude sessions spawned.
    """
    from pathlib import Path
    from .response_watcher import save_thread_mapping
    from . import bucket as bucket_mod

    requests_dir = Path(__file__).resolve().parents[2] / "data" / "claude_requests"
    responses_dir = Path(__file__).resolve().parents[2] / "data" / "claude_responses"
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    bucket_ch = (config.slack.bucket_channel_id or "").strip() or channel

    # Load auto_watcher deps once
    import sys
    scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    try:
        from auto_watcher import analyze as aw_analyze, _load_deps
        detect_skill_fn, find_relevant, format_relevant, load_config = _load_deps()
        aw_config = load_config()
        deps = {
            "detect_skill": detect_skill_fn,
            "find_relevant": find_relevant,
            "format_relevant": format_relevant,
            "config": aw_config,
        }
    except Exception as e:
        logger.error("Failed to load auto_watcher: %s", e)
        say(text=f":x: Could not load analysis engine: {e}", thread_ts=thread_ts)
        return

    # ── Part 1: Process pending unassigned request files ────────────────────
    pending = [
        f for f in requests_dir.glob("ISS-*.md")
        if not (responses_dir / f.name).exists()
    ]

    processed = 0
    if pending:
        say(
            text=f":hourglass_flowing_sand: Processing *{len(pending)}* pending ticket{'s' if len(pending) > 1 else ''}...",
            thread_ts=thread_ts,
        )
        for req_file in pending:
            ticket_id = req_file.stem
            try:
                response_text = aw_analyze(req_file, deps)
                resp_file = responses_dir / req_file.name
                resp_file.write_text(response_text)
                save_thread_mapping(ticket_id, channel, thread_ts)
                bucket_mod.save_ticket_thread(ticket_id, channel, thread_ts)
                processed += 1
                logger.info("check: analysed %s", ticket_id)
            except Exception as e:
                logger.error("check: failed to analyse %s: %s", ticket_id, e)
                say(text=f":x: Failed to analyse `{ticket_id}`: {e}", thread_ts=thread_ts)

        if processed:
            say(
                text=f":white_check_mark: Done — *{processed}* ticket{'s' if processed > 1 else ''} analysed. Results posting now...",
                thread_ts=thread_ts,
            )

    # ── Part 2: Assigned tickets with no Slack thread yet ───────────────────
    if not slack_client:
        if not pending:
            say(text=":white_check_mark: No pending tickets — all clear!", thread_ts=thread_ts)
        return

    try:
        from . import devrev_client
        from .enhanced_agent import detect_skill as _detect_skill
        from .response_watcher import _post_formatted

        my_user_id = (config.devrev.my_user_id or "").strip()
        if not my_user_id:
            if not pending:
                say(text=":white_check_mark: No pending tickets — all clear!", thread_ts=thread_ts)
            return

        user = devrev_client.get_self()
        user_id = user.get("id") or my_user_id

        data = devrev_client.works_list(
            owned_by=[user_id],
            state=config.monitor.my_tickets_states,
            limit=30,
        )
        assigned_works = data.get("works") or []

        no_thread = [
            w for w in assigned_works
            if not bucket_mod.get_ticket_thread(w.get("display_id") or "")
        ]
        has_thread = [
            w for w in assigned_works
            if bucket_mod.get_ticket_thread(w.get("display_id") or "")
        ]

        if not no_thread and not has_thread:
            if not pending:
                say(text=":white_check_mark: All caught up — no pending tickets and no assigned tickets.", thread_ts=thread_ts)
            return

        # ── Part 2a: Create threads for tickets without one ────────────────
        if no_thread:
            say(
                text=f":file_folder: Found *{len(no_thread)}* assigned ticket{'s' if len(no_thread) > 1 else ''} with no thread — creating now...",
                thread_ts=thread_ts,
            )

            app_base = getattr(config.devrev, "app_base_url", None) or "https://app.devrev.ai"
            for w in no_thread[:10]:
                display_id = w.get("display_id") or w.get("id", "")
                title = (w.get("title") or "")[:100]
                body = (w.get("body") or "")[:2000]
                stage_name = (w.get("stage") or {}).get("name") or "Unknown"
                ticket_text = f"{title}\n\n{body}".strip()

                try:
                    skill_name, confidence = _detect_skill(ticket_text)
                    skill_name = skill_name or "none"

                    ticket_url = f"{app_base}/razorpay/issue/{display_id}"
                    post_result = slack_client.chat_postMessage(
                        channel=bucket_ch,
                        text=f"{display_id} — {title}",
                        attachments=[{
                            "color": "#6B47DC",
                            "title": f"{display_id} — {title}",
                            "title_link": ticket_url,
                            "text": f"Stage: `{stage_name}` | Assigned to you",
                            "footer": "DevRev · PSE · My Tickets",
                        }],
                    )
                    posted_ts = post_result["ts"]

                    from .scripts_utils import build_inline_analysis
                    response = build_inline_analysis(ticket_text, display_id, skill_name, confidence)
                    _post_formatted(slack_client, bucket_ch, posted_ts, display_id, response)

                    body_hash = bucket_mod.get_body_hash(title, body)
                    bucket_mod.save_ticket_thread(display_id, bucket_ch, posted_ts, last_body_hash=body_hash)
                    bucket_mod.set_bucket_thread_state(bucket_ch, posted_ts, {
                        "step": "suggested",
                        "work_id": w.get("id", ""),
                        "display_id": display_id,
                        "ticket_text": ticket_text,
                        "skill_name": skill_name,
                    })
                    logger.info("check: created thread for assigned ticket %s", display_id)
                except Exception as e:
                    logger.error("check: failed to create thread for %s: %s", display_id, e)

        # ── Part 2b: Update existing threads (status or re-analyze) ────────
        if has_thread:
            updated_count = _update_existing_threads(has_thread, slack_client, bucket_ch, config)
            if updated_count:
                say(
                    text=f":arrows_counterclockwise: Updated *{updated_count}* existing thread{'s' if updated_count > 1 else ''}.",
                    thread_ts=thread_ts,
                )

        if not no_thread and not has_thread and not pending:
            say(text=":white_check_mark: All caught up — no pending tickets.", thread_ts=thread_ts)

    except Exception as e:
        logger.error("check: assigned ticket scan failed: %s", e)
        if not pending:
            say(text=":white_check_mark: No pending tickets — all clear!", thread_ts=thread_ts)


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

    # Carry over skill_name from existing thread state (e.g. if user ran a skill
    # in this thread and then issued "close ISS-XXXXX" to complete the flow).
    prior_skill = (_thread_state.get(thread_key) or {}).get("skill_name", "")
    _thread_state[thread_key] = {
        "step": "awaiting_close_info",
        "work_id": work_id,
        "display_id": display_id,
        "title": title,
        "current_cause": current_cause,
        "current_breach": current_breach,
        "skill_name": prior_skill,  # auto-tag with skill on close if known
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

    from .response_watcher import start_response_watcher, start_pending_notifier, save_thread_mapping
    start_response_watcher(app.client)

    watch_ch = (config.slack.watch_channel_id or "").strip()
    bucket_ch = (config.slack.bucket_channel_id or "").strip()

    # Fetch the bot's own Slack user ID so the notifier can mention it correctly
    _bot_user_id = ""
    try:
        _auth = app.client.auth_test()
        _bot_user_id = _auth.get("user_id", "")
    except Exception:
        pass

    # Notify user in Slack when new tickets arrive — user replies "@ManideepBot check"
    # in Slack to trigger analysis. No Claude Code sessions spawned.
    notify_ch = bucket_ch or watch_ch
    if notify_ch:
        start_pending_notifier(app.client, notify_ch, bot_user_id=_bot_user_id)
        logger.info("Pending notifier started — will ping %s when new tickets land", notify_ch)
    else:
        logger.warning("No channel configured — pending notifier disabled (set bucket_channel_id)")
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

        # Strip Slack MCP "Sent using" footer from text before processing
        text = re.sub(r"\s*\*[Ss]ent using\*.*$", "", text).strip()

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

        # ── Check command: @bot check — process all pending tickets now ────────
        if text.lower().strip() in ("check", "check pending", "process"):
            _handle_check(event, say, config, slack_client=client)
            return

        # ── If "@bot yes/approve" in a thread, delegate to handle_message ────
        # Users often type "@bot yes" instead of just "yes" in a thread reply.
        _mention_cmd = _normalize_approve(text)
        if _mention_cmd and event.get("thread_ts"):
            logger.info("Mention '%s' in thread — delegating to handle_message", _mention_cmd)
            handle_message(event, say, client)
            return

        say(text=":hourglass_flowing_sand: Analysing...", thread_ts=thread_ts)
        try:
            channel = event.get("channel")
            display_id = _parse_work_id(text)
            from . import devrev_client
            from .enhanced_agent import detect_skill as _detect_skill

            # Step 1: Fetch full ticket from DevRev
            ticket_text = text
            work_id = None
            work = None
            if display_id:
                work_id = devrev_client.display_id_to_work_id(display_id)
                try:
                    work = devrev_client.get_work_by_display_id(display_id)
                    if work:
                        _title = (work.get("title") or "")
                        _body = (work.get("body") or "")[:3000]
                        ticket_text = f"{_title}\n\n{_body}".strip() or text
                except Exception as e:
                    logger.warning("Could not fetch ticket body for %s: %s", display_id, e)

            # Step 2: Detect skill directly — no file queue, no waiting
            _skill, _conf = _detect_skill(ticket_text)

            # Step 3: If Anthropic key set, use LLM for richer analysis
            has_api_key = bool(getattr(config.anthropic, "api_key", None))
            if has_api_key:
                response = enhanced_reply(ticket_text, config)
                _skill = _skill or _parse_skill_name(response) or "none"
                from .response_watcher import _post_formatted
                _post_formatted(app.client, channel, thread_ts, display_id or "ticket", response)
            else:
                # No Anthropic key — queue for Claude scheduled task (every 10 min, Mon-Fri 10am-6pm)
                from .claude_code_agent import claude_code_reply
                from .response_watcher import save_thread_mapping
                req_ticket_id = display_id or f"ticket_{int(time.time())}"
                if display_id:
                    save_thread_mapping(display_id, channel, thread_ts)
                claude_code_reply(ticket_text, config, ticket_id=req_ticket_id)
                say(text="⏳ Queued for Claude analysis — response will appear in this thread within 10 minutes.", thread_ts=thread_ts)

            _skill = _skill or "none"
            key = _thread_key(event)
            _thread_state[key] = {
                "step": "suggested",
                "ticket_text": ticket_text,
                "work_id": work_id,
                "display_id": display_id,
                "skill_name": _skill,
            }
            _save_persisted_state()
            logger.info("handle_mention: %s → skill=%s conf=%s", display_id, _skill, _conf)
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
        user_text = (event.get("text") or "").strip()
        logger.info("[MSG] ch=%s thread=%s text=%r", ch, thread_ts, user_text[:80])
        state = _thread_state.get(key)
        from . import bucket as bucket_mod
        if not state:
            state = bucket_mod.get_thread_state_from_bucket(ch, thread_ts)
            is_bucket = bool(state)
            if state:
                logger.info("[MSG] State from bucket: step=%s skill=%s", state.get("step"), state.get("skill_name"))
            else:
                logger.info("[MSG] No state found (in-memory or bucket)")
        else:
            is_bucket = False
            logger.info("[MSG] State from memory: step=%s skill=%s", state.get("step"), state.get("skill_name"))

        # If no state but user said "yes" — recover from Slack thread history
        text_raw = (event.get("text") or "").strip()
        cmd_raw = _normalize_approve(text_raw)
        if not state and cmd_raw == "yes":
            try:
                history = client.conversations_replies(channel=ch, ts=thread_ts, limit=20)
                messages = history.get("messages", [])
                recovered_skill, recovered_display_id, recovered_ticket_text = None, None, ""
                for msg in messages:
                    msg_text = msg.get("text", "")
                    # Also search attachment texts — bot posts skill name inside attachments
                    for att in msg.get("attachments", []):
                        att_text = att.get("text", "")
                        if att_text:
                            msg_text += "\n" + att_text
                    # Look for bot analysis messages with skill info
                    _s = _parse_skill_name(msg_text)
                    if _s and _s != "none":
                        recovered_skill = _s
                    # Look for ticket ID in any message
                    _d = _parse_work_id(msg_text)
                    if _d:
                        recovered_display_id = _d
                    # Use bot analysis text as ticket context
                    if msg.get("bot_id") and "Analysis:" in msg.get("text", ""):
                        recovered_ticket_text = msg_text[:3000]
                if recovered_skill:
                    # Re-fetch full ticket body from DevRev (thread history only has analysis text)
                    if recovered_display_id and not recovered_ticket_text:
                        try:
                            from . import devrev_client as _dc
                            _work = _dc.get_work_by_display_id(recovered_display_id)
                            if _work:
                                _title = (_work.get("title") or "")
                                _body = (_work.get("body") or "")[:3000]
                                recovered_ticket_text = f"{_title}\n\n{_body}".strip()
                        except Exception:
                            pass
                    # Even if we have analysis text, re-fetch to get card numbers etc.
                    if recovered_display_id and recovered_ticket_text and not re.search(r"\d{10,}", recovered_ticket_text):
                        try:
                            from . import devrev_client as _dc
                            _work = _dc.get_work_by_display_id(recovered_display_id)
                            if _work:
                                _title = (_work.get("title") or "")
                                _body = (_work.get("body") or "")[:3000]
                                recovered_ticket_text = f"{_title}\n\n{_body}".strip()
                        except Exception:
                            pass
                    state = {
                        "step": "suggested",
                        "skill_name": recovered_skill,
                        "display_id": recovered_display_id or "",
                        "ticket_text": recovered_ticket_text,
                        "channel": ch,
                        "thread_ts": thread_ts,
                    }
                    _set_state(key, state)
                    is_bucket = False
                    logger.info("Recovered state from thread history: skill=%s display_id=%s", recovered_skill, recovered_display_id)
            except Exception as _re:
                logger.warning("Could not recover state from thread history: %s", _re)

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

            # Build tag list — include skill tag if a skill was used in this thread
            from . import devrev_client as dc
            extra_tags = []
            if tags_raw:
                for t in [x.strip() for x in re.split(r"[,;]", tags_raw) if x.strip()]:
                    extra_tags.append({"name": t, "value": ""})
            skill_name_for_tag = (state.get("skill_name") or "").strip()
            tags_to_add = dc.build_tags_for_closure(
                skill_name=skill_name_for_tag,
                extra_tags=extra_tags,
            )

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

        # ── Handle missing-info reply: user provides card number / URL / order_id
        # When step=suggested and the reply is NOT yes/no/approve, treat it as
        # extra context, append to ticket_text, and auto-re-run the skill.
        if (state.get("step") == "suggested"
                and cmd not in ("yes", "no", "approve", "confirm", "done")
                and state.get("awaiting_info")):
            from . import skill_runner
            ticket_text = (state.get("ticket_text") or "") + "\n" + text
            state["ticket_text"] = ticket_text
            state.pop("awaiting_info", None)
            skill_name = state.get("skill_name", "none")
            # If user typed a skill name directly (e.g. "gc-redemption-report"), use it
            _cmd_clean = cmd.strip().strip("`").lower()
            if _cmd_clean in _KNOWN_SKILLS:
                skill_name = _cmd_clean
                state["skill_name"] = skill_name
            # If skill still none, try parsing from the text itself
            if not skill_name or skill_name == "none":
                _parsed = _parse_skill_name(text)
                if _parsed:
                    skill_name = _parsed
                    state["skill_name"] = skill_name
            say(text=":hourglass_flowing_sand: Got it — re-running skill...", thread_ts=thread_ts)
            out, ok = skill_runner.run_skill(skill_name, ticket_text, ticket_id=state.get("display_id", ""))
            if not ok:
                state["awaiting_info"] = True
                if is_bucket:
                    bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
                else:
                    _set_state(key, state)
                say(text=f":warning: {out}", thread_ts=thread_ts)
                return
            say(
                text=f"{out[:2500]}\n\nReply *Approve* to post this on the ticket and close it.",
                thread_ts=thread_ts,
            )
            state["step"] = "pending_approve"
            state["output"] = out
            state["summary"] = out[:500]
            if is_bucket:
                bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
            else:
                _set_state(key, state)
            return

        logger.info("[MSG] cmd=%r step=%r is_bucket=%s", cmd, state.get("step"), is_bucket)
        if cmd == "yes" and state.get("step") == "suggested":
            logger.info("[MSG] >>> Running skill for 'yes': skill=%s display_id=%s", state.get("skill_name"), state.get("display_id"))
            from . import skill_runner
            ticket_text = state.get("ticket_text") or ""
            skill_name = (state.get("skill_name") or "").strip()
            display_id = state.get("display_id") or ""

            # If display_id or skill_name missing, recover from thread history
            if not display_id or not skill_name or skill_name == "none":
                try:
                    history = client.conversations_replies(channel=ch, ts=thread_ts, limit=20)
                    for msg in (history.get("messages") or []):
                        msg_text = msg.get("text", "")
                        for att in msg.get("attachments", []):
                            msg_text += "\n" + (att.get("text", "") or "") + "\n" + (att.get("fallback", "") or "")
                        if not display_id:
                            _d = _parse_work_id(msg_text)
                            if _d:
                                display_id = _d
                                state["display_id"] = display_id
                        if not skill_name or skill_name == "none":
                            _s = _parse_skill_name(msg_text)
                            if _s and _s != "none":
                                skill_name = _s
                                state["skill_name"] = skill_name
                    if display_id or skill_name:
                        logger.info("Recovered from thread history: display_id=%s skill=%s", display_id, skill_name)
                except Exception as _re:
                    logger.warning("Thread history recovery failed: %s", _re)

            # Recover skill from response file if still "none"
            if not skill_name or skill_name == "none":
                if display_id:
                    import pathlib
                    _data_root = pathlib.Path(__file__).resolve().parents[3] / "data"
                    # Check both active and done folders (scheduled task archives to done/)
                    for _resp_file in [
                        _data_root / "claude_responses" / f"{display_id}.md",
                        _data_root / "claude_responses" / "done" / f"{display_id}.md",
                    ]:
                        if _resp_file.exists():
                            _resp_content = _resp_file.read_text()
                            _recovered = _parse_skill_name(_resp_content)
                            if _recovered and _recovered != "none":
                                skill_name = _recovered
                                state["skill_name"] = skill_name
                                # Also enrich ticket_text from the response if current is bare mention
                                if len(ticket_text) < 50:
                                    ticket_text = _resp_content[:3000]
                                    state["ticket_text"] = ticket_text
                                break
                # Final fallback: re-detect from ticket_text
                if not skill_name or skill_name == "none":
                    from .enhanced_agent import detect_skill as _detect_skill
                    _sk, _ = _detect_skill(ticket_text)
                    skill_name = _sk or "none"

            # If ticket_text is empty/short, fetch from DevRev before running skill
            if len(ticket_text) < 50 and display_id:
                try:
                    from . import devrev_client as _dc
                    _work = _dc.get_work_by_display_id(display_id)
                    if _work:
                        _title = (_work.get("title") or "")
                        _body = (_work.get("body") or "")[:3000]
                        ticket_text = f"{_title}\n\n{_body}".strip()
                        state["ticket_text"] = ticket_text
                        logger.info("Fetched ticket body for %s (was empty)", display_id)
                        # Re-detect skill with actual body
                        if not skill_name or skill_name == "none":
                            from .enhanced_agent import detect_skill as _detect_skill2
                            _sk2, _ = _detect_skill2(ticket_text)
                            if _sk2 and _sk2 != "none":
                                skill_name = _sk2
                                state["skill_name"] = skill_name
                                logger.info("Re-detected skill from fetched body: %s", skill_name)
                except Exception as _fe:
                    logger.warning("Could not fetch ticket body for %s: %s", display_id, _fe)

            out, ok = skill_runner.run_skill(skill_name, ticket_text, ticket_id=state.get("display_id", ""))
            if not ok:
                # Mark that we're waiting for missing info — next reply auto-reruns
                state["awaiting_info"] = True
                if is_bucket:
                    bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
                else:
                    _set_state(key, state)
                say(text=f":warning: {out}", thread_ts=thread_ts)
                return
            say(
                text=f"{out[:2500]}\n\nReview. If correct, reply *Approve* to post this on the ticket and close it.",
                thread_ts=thread_ts,
            )
            state["step"] = "pending_approve"
            state["output"] = out
            state["summary"] = out[:500]
            if is_bucket:
                bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
            else:
                _set_state(key, state)
            return

        if state.get("step") == "pending_approve" and not state.get("work_id"):
            wid = _parse_work_id(text)
            if wid:
                state["work_id"] = state.get("work_id") or wid
                state["display_id"] = wid
                if is_bucket:
                    bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
                else:
                    _set_state(key, state)
                say(text=f"Got ticket ID: {wid}. Reply **Approve** to post the resolution and close it.", thread_ts=thread_ts)
                return

        if cmd == "approve" and state.get("step") == "pending_approve":
            work_id = state.get("work_id")
            display_id = state.get("display_id") or ""
            if not work_id and not display_id:
                say(
                    text="I don't have the ticket ID. Please paste the DevRev work ID (e.g. ISS-123) so I can post the update and close it.",
                    thread_ts=thread_ts,
                )
                return

            skill_name = (state.get("skill_name") or "").strip()

            # Use pse-ticket-closer flow: ask for cause code, breach reason, tags
            prompt = (
                f":ticket: *Closing {display_id}* — let's fill in the required fields.\n\n"
                f"*1. Cause Code* (pick a number):\n"
                f"```\n{_numbered_list(_CAUSE_CODES)}\n```\n\n"
                f"*2. Reason for Breach* (pick a number):\n"
                f"```\n{_numbered_list(_BREACH_REASONS)}\n```\n\n"
                f"*3. Tags* (comma-separated, e.g. `redemption_report`)\n\n"
                f"Reply with:\n"
                f"```\n"
                f"cause_code: <number>\n"
                f"breach_reason: <number>\n"
                f"tags: tag1, tag2\n"
                f"```\n"
                f"Or reply `quick` to close with defaults:\n"
                f"  cause_code: `PSE - Log/Tech Issue` | breach_reason: `SLA Not Breached` | tag: `{skill_name or 'bot_resolved'}`"
            )
            say(text=prompt, thread_ts=thread_ts)

            state["step"] = "awaiting_pse_close_info"
            state["skill_name"] = skill_name
            if is_bucket:
                bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
            else:
                _set_state(key, state)
            return

        # ── PSE ticket closer step: run close_pse_ticket.py ────────────────
        if state.get("step") == "awaiting_pse_close_info":
            display_id = state.get("display_id") or ""
            skill_name = (state.get("skill_name") or "").strip()
            summary = state.get("summary") or state.get("output") or "Resolved by Manideep Bot."

            raw_text = text.strip().lower()

            # Quick close with defaults
            if raw_text in ("quick", "q", "default", "defaults"):
                cause_code = "PSE - Log/Tech Issue"
                breach_reason = "SLA Not Breached"
                tags_list = [skill_name] if skill_name and skill_name != "none" else ["bot_resolved"]
            else:
                # Parse structured fields
                cause_raw = _extract_field(text,
                    r"^cause_?code[\s:：]+(.+)$",
                    r"cause_?code[\s:：]+(.+)")
                breach_raw = _extract_field(text,
                    r"^breach_?reason[\s:：]+(.+)$",
                    r"^reason_?for_?breach[\s:：]+(.+)$",
                    r"breach_?reason[\s:：]+(.+)")
                tags_raw = _extract_field(text,
                    r"^tags?[\s:：]+(.+)$",
                    r"tags?[\s:：]+(.+)")

                cause_code = _pick_from_list(cause_raw, _CAUSE_CODES) if cause_raw else ""
                breach_reason = _pick_from_list(breach_raw, _BREACH_REASONS) if breach_raw else ""
                tags_list = [t.strip() for t in re.split(r"[,;]", tags_raw) if t.strip()] if tags_raw else []

                # Add skill tag if not already present
                if skill_name and skill_name != "none":
                    skill_tag = skill_name
                    if skill_tag not in tags_list:
                        tags_list.append(skill_tag)
                if not tags_list:
                    tags_list = ["bot_resolved"]

                if not cause_code:
                    say(text=":warning: Cause code not recognized. Pick a number from the list above or type `quick` for defaults.", thread_ts=thread_ts)
                    return
                if not breach_reason:
                    say(text=":warning: Breach reason not recognized. Pick a number from the list above or type `quick` for defaults.", thread_ts=thread_ts)
                    return

            # Close using devrev_client directly (no subprocess, no API timeouts)
            say(text=f":hourglass_flowing_sand: Closing `{display_id}`...", thread_ts=thread_ts)

            try:
                from . import devrev_client
                comment_text = f"Resolved via Manideep Bot skill: {skill_name}.\n\n{summary[:500]}"
                success, log_output = devrev_client.pse_close_ticket(
                    display_id=display_id,
                    cause_code=cause_code,
                    reason_for_breach=breach_reason,
                    tag_names=tags_list,
                    comment=comment_text,
                )

                if success:
                    say(
                        text=(
                            f":white_check_mark: *{display_id} closed!*\n\n"
                            f":label: *Cause code:* `{cause_code}`\n"
                            f":clipboard: *Breach reason:* `{breach_reason}`\n"
                            f":bookmark: *Tags:* {', '.join(f'`{t}`' for t in tags_list)}\n\n"
                            f"```\n{log_output[-800:]}\n```"
                        ),
                        thread_ts=thread_ts,
                    )

                    # Append to solved tickets for learning
                    try:
                        from .monitor import append_solved_ticket_after_approve
                        work_id = state.get("work_id") or ""
                        if work_id:
                            append_solved_ticket_after_approve(config, work_id)
                    except Exception:
                        pass
                else:
                    say(text=f":x: Close failed:\n```\n{log_output[-1000:]}\n```", thread_ts=thread_ts)
                    return  # keep state so user can retry
            except Exception as e:
                logger.exception("pse_close_ticket error for %s", display_id)
                say(text=f":x: Error closing ticket: {e}", thread_ts=thread_ts)
                return

            # Clean up state
            if is_bucket:
                bucket_mod.pop_bucket_thread_state(ch, thread_ts)
            else:
                _thread_state.pop(key, None)
            return

        # ── Tag-confirmation step: user validates tags before close ──────────
        if state.get("step") == "pending_tag_confirm":
            work_id = state.get("work_id")
            display_id = state.get("display_id") or ""
            raw_text = text.strip().lower()

            # Allow override: "tags: tag1, tag2"
            tags_override_raw = _extract_field(text, r"^tags?[\s:：]+(.+)$", r"tags?[\s:：]+(.+)")
            if tags_override_raw:
                from . import devrev_client as dc
                override_list = [{"name": t.strip(), "value": ""} for t in re.split(r"[,;]", tags_override_raw) if t.strip()]
                state["tags_to_add"] = dc.build_tags_for_closure(extra_tags=override_list)
                tag_names = [t["name"] for t in state["tags_to_add"]]
                say(text=f":white_check_mark: Tags updated: {', '.join(f'`{n}`' for n in tag_names)}. Reply *confirm* to close.", thread_ts=thread_ts)
                if is_bucket:
                    bucket_mod.set_bucket_thread_state(ch, thread_ts, state)
                else:
                    _set_state(key, state)
                return

            if raw_text not in ("confirm", "yes", "ok", "done", "close it", "proceed"):
                say(
                    text="Reply *confirm* to close with those tags, or override with `tags: tag1, tag2`.",
                    thread_ts=thread_ts,
                )
                return

            # User confirmed — execute the close
            try:
                from . import devrev_client
                from .monitor import append_solved_ticket_after_approve

                summary = state.get("summary") or state.get("output") or "Resolved by Manideep Bot."
                skill_name = (state.get("skill_name") or "").strip()
                tags_to_add = state.get("tags_to_add") or []
                similar_fields = state.get("similar_fields") or {}
                best_similar_id = state.get("best_similar_id") or ""

                resolution_comment = devrev_client.build_resolution_comment(
                    summary=summary,
                    skill_name=skill_name,
                    similar_ticket_id=best_similar_id,
                )

                devrev_client.work_update_full(
                    work_id=work_id,
                    stage_name=config.devrev.closed_stage_name,
                    tags_to_add=tags_to_add,
                    comment=resolution_comment,
                    custom_fields=similar_fields if similar_fields else None,
                )

                append_solved_ticket_after_approve(config, work_id)

                tag_names = [t["name"] for t in tags_to_add]
                confirm_parts = [
                    f":white_check_mark: *{display_id}* closed — stage set to `{config.devrev.closed_stage_name}`.",
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

        # If we reach here, no handler matched
        logger.info("[MSG] No handler matched: cmd=%r step=%r awaiting_info=%s",
                     cmd, state.get("step"), state.get("awaiting_info"))

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

        # ── PSE pod filter: skip tickets not belonging to our pods ─────────
        allowed_pods = getattr(getattr(config, "monitor", None), "new_ticket_filter_pse_pods", None) or []
        ticket_pod = (
            (work.get("custom_fields") or {}).get("ctype__pse_pod") or
            work.get("ctype__pse_pod") or ""
        ).strip()
        logger.info("Ticket %s — PSE pod: '%s' | allowed: %s", display_id, ticket_pod, allowed_pods)
        if allowed_pods:
            pod_set = {p.strip().lower() for p in allowed_pods if p}
            if ticket_pod.lower() not in pod_set:
                logger.info(
                    "Skipping %s — PSE pod '%s' not in allowed pods",
                    display_id, ticket_pod,
                )
                return False

        # ── Auto-assign if unassigned ──────────────────────────────────────
        assigned_now = False
        skip_reason = None
        if my_user_id and _is_unassigned(work, svcacc_id):
            # Check if user already has too many tickets
            try:
                current_count = devrev_client.count_open_tickets_for_user(my_user_id)
                if current_count >= 10:
                    skip_reason = f"Already have {current_count} open tickets (limit: 10)"
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

            # Save ticket → Slack thread mapping for monitor continuity
            from . import bucket as _bucket_mod
            body_hash = _bucket_mod.get_body_hash(title, body)
            _bucket_mod.save_ticket_thread(display_id, bucket_ch, posted_ts, last_body_hash=body_hash)

            # 2. Get analysis
            result = _get_analysis(ticket_text, config, display_id)

            ticket_timestamp = None
            if isinstance(result, tuple):
                response, ticket_timestamp = result
            else:
                response = result

            # ── Skill detection: keyword match first, then parse LLM response ──
            # detect_skill() uses pure regex + tag matching — works with or
            # without an API key, always accurate for known ticket patterns.
            from .enhanced_agent import detect_skill as _detect_skill
            detected_skill, confidence = _detect_skill(ticket_text)
            skill_name = detected_skill or _parse_skill_name(response) or "none"

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
                out, ok = skill_runner.run_skill(skill_name, ticket_text, ticket_id=display_id)
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
                        "awaiting_info": True,
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

    # ── Catch-up scan on startup ─────────────────────────────────────────────
    def _catchup_scan():
        """
        Runs once on startup (in background thread, after 8s delay for connection).
        Two phases:
          1. Fetch unassigned PSE tickets missed while bot was down → auto-assign + thread
          2. Fetch assigned tickets with no Slack thread yet → create threads
        """
        import time as _time
        _time.sleep(8)  # wait for Slack connection to stabilise

        if not bucket_ch:
            logger.warning("Catch-up scan: bucket_channel_id not set, skipping")
            return

        logger.info("🔍 Catch-up scan: Phase 1 — checking for missed unassigned tickets...")
        try:
            from . import devrev_client
            from .monitor import _fetch_new_tickets
            from .response_watcher import _post_formatted
            from . import bucket as bucket_mod
            from .enhanced_agent import detect_skill as _detect_skill
            from .scripts_utils import build_inline_analysis

            # ── Phase 1: Unassigned tickets ──────────────────────────────────
            tickets = _fetch_new_tickets(config)
            unassigned_count = 0
            if tickets:
                logger.info("Catch-up scan: found %d unassigned ticket(s) to process", len(tickets))
                app.client.chat_postMessage(
                    channel=bucket_ch,
                    text=f"🔍 *Catch-up scan* — found *{len(tickets)}* unassigned ticket(s) missed while bot was down. Processing now...",
                )

                for w in tickets[:15]:
                    work_id = w.get("id", "")
                    display_id = w.get("display_id") or work_id
                    title = (w.get("title") or "")[:200]
                    body = (w.get("body") or "")[:3000]
                    ticket_text = f"{title}\n\n{body}".strip() or str(display_id)

                    try:
                        assigned_now = False
                        if my_user_id and _is_unassigned(w, svcacc_id):
                            try:
                                current_count = devrev_client.count_open_tickets_for_user(my_user_id)
                                if current_count < 15:
                                    devrev_client.work_assign(work_id, my_user_id)
                                    assigned_now = True
                                    logger.info("Catch-up: auto-assigned %s", display_id)
                            except Exception as e:
                                logger.warning("Catch-up auto-assign failed for %s: %s", display_id, e)

                        app_base = getattr(config.devrev, "app_base_url", None) or "https://app.devrev.ai"
                        ticket_url = f"{app_base}/razorpay/issue/{display_id}"
                        status_line = "✅ Auto-assigned to you (catch-up)" if assigned_now else "_(already assigned)_"

                        notify_result = app.client.chat_postMessage(
                            channel=bucket_ch,
                            text=f"[Catch-up] {display_id} — {title[:80]}",
                            attachments=[{
                                "color": "#FF8C00",
                                "title": f"[Catch-up] {display_id} — {title[:80]}",
                                "title_link": ticket_url,
                                "text": status_line,
                                "footer": "DevRev · PSE · Missed while bot was down",
                            }],
                        )
                        posted_ts = notify_result["ts"]
                        body_hash = bucket_mod.get_body_hash(title, body)
                        bucket_mod.save_ticket_thread(display_id, bucket_ch, posted_ts, last_body_hash=body_hash)

                        skill_name, confidence = _detect_skill(ticket_text)
                        skill_name = skill_name or "none"

                        response = build_inline_analysis(ticket_text, display_id, skill_name, confidence)
                        _post_formatted(app.client, bucket_ch, posted_ts, display_id, response)

                        if skill_name in _AUTO_RUN_SKILLS:
                            app.client.chat_postMessage(
                                channel=bucket_ch, thread_ts=posted_ts,
                                text=f":robot_face: *Auto-running* `{skill_name}`...",
                            )
                            from . import skill_runner
                            out, ok = skill_runner.run_skill(skill_name, ticket_text, ticket_id=display_id)
                            result_text = (
                                f":white_check_mark: `{skill_name}` done.\n```\n{out[:2500]}\n```\n\nReply *Approve* to post and close."
                                if ok else
                                f":warning: Auto-run failed: {out}\n\nReply *Yes* after adding missing info."
                            )
                            app.client.chat_postMessage(channel=bucket_ch, thread_ts=posted_ts, text=result_text)
                            step = "pending_approve" if ok else "suggested"
                        else:
                            step = "suggested"

                        bucket_mod.set_bucket_thread_state(bucket_ch, posted_ts, {
                            "step": step, "work_id": work_id, "display_id": display_id,
                            "ticket_text": ticket_text, "skill_name": skill_name,
                        })
                        unassigned_count += 1

                    except Exception as e:
                        logger.exception("Catch-up: error processing %s: %s", display_id, e)
            else:
                logger.info("Catch-up scan: no unassigned tickets found")

            # ── Phase 2: Assigned tickets — new threads + update existing ────
            logger.info("🔍 Catch-up scan: Phase 2 — checking assigned tickets...")
            assigned_count = 0
            existing_updated = 0
            try:
                user_id = my_user_id
                if not user_id:
                    logger.info("Catch-up Phase 2: my_user_id not set, skipping")
                else:
                    data = devrev_client.works_list(
                        owned_by=[user_id],
                        state=config.monitor.my_tickets_states,
                        limit=30,
                    )
                    assigned_works = data.get("works") or []

                    no_thread = [
                        w for w in assigned_works
                        if not bucket_mod.get_ticket_thread(w.get("display_id") or "")
                    ]
                    has_thread = [
                        w for w in assigned_works
                        if bucket_mod.get_ticket_thread(w.get("display_id") or "")
                    ]

                    # Phase 2a: Create threads for tickets without one
                    if no_thread:
                        logger.info("Catch-up Phase 2a: %d assigned ticket(s) with no thread", len(no_thread))
                        app.client.chat_postMessage(
                            channel=bucket_ch,
                            text=f":file_folder: *Catch-up* — found *{len(no_thread)}* assigned ticket(s) with no thread. Creating now...",
                        )

                        app_base = getattr(config.devrev, "app_base_url", None) or "https://app.devrev.ai"
                        for w in no_thread[:15]:
                            display_id = w.get("display_id") or w.get("id", "")
                            title = (w.get("title") or "")[:100]
                            body = (w.get("body") or "")[:2000]
                            stage_name = (w.get("stage") or {}).get("name") or "Unknown"
                            ticket_text = f"{title}\n\n{body}".strip()

                            try:
                                skill_name, confidence = _detect_skill(ticket_text)
                                skill_name = skill_name or "none"

                                ticket_url = f"{app_base}/razorpay/issue/{display_id}"
                                post_result = app.client.chat_postMessage(
                                    channel=bucket_ch,
                                    text=f"{display_id} — {title}",
                                    attachments=[{
                                        "color": "#6B47DC",
                                        "title": f"{display_id} — {title}",
                                        "title_link": ticket_url,
                                        "text": f"Stage: `{stage_name}` | Assigned to you",
                                        "footer": "DevRev · PSE · My Tickets",
                                    }],
                                )
                                posted_ts = post_result["ts"]

                                response = build_inline_analysis(ticket_text, display_id, skill_name, confidence)
                                _post_formatted(app.client, bucket_ch, posted_ts, display_id, response)

                                body_hash = bucket_mod.get_body_hash(title, body)
                                bucket_mod.save_ticket_thread(display_id, bucket_ch, posted_ts, last_body_hash=body_hash)
                                bucket_mod.set_bucket_thread_state(bucket_ch, posted_ts, {
                                    "step": "suggested",
                                    "work_id": w.get("id", ""),
                                    "display_id": display_id,
                                    "ticket_text": ticket_text,
                                    "skill_name": skill_name,
                                })
                                assigned_count += 1
                                logger.info("Catch-up Phase 2a: created thread for %s", display_id)
                            except Exception as e:
                                logger.exception("Catch-up Phase 2a: failed for %s: %s", display_id, e)
                    else:
                        logger.info("Catch-up Phase 2a: all assigned tickets already have threads")

                    # Phase 2b: Update existing threads (status or re-analyze)
                    if has_thread:
                        logger.info("Catch-up Phase 2b: updating %d existing thread(s)", len(has_thread))
                        existing_updated = _update_existing_threads(has_thread, app.client, bucket_ch, config)
                        if existing_updated:
                            logger.info("Catch-up Phase 2b: updated %d thread(s)", existing_updated)

            except Exception as e:
                logger.exception("Catch-up Phase 2 failed: %s", e)

            # ── Summary ──────────────────────────────────────────────────────
            total = unassigned_count + assigned_count + existing_updated
            if total == 0:
                app.client.chat_postMessage(
                    channel=bucket_ch,
                    text="✅ *Catch-up scan complete* — all tickets up to date.",
                )
            else:
                parts = []
                if unassigned_count:
                    parts.append(f"{unassigned_count} unassigned")
                if assigned_count:
                    parts.append(f"{assigned_count} new threads")
                if existing_updated:
                    parts.append(f"{existing_updated} existing updated")
                app.client.chat_postMessage(
                    channel=bucket_ch,
                    text=f"✅ *Catch-up scan complete* — processed {' + '.join(parts)}.",
                )
            logger.info("Catch-up scan complete — %d unassigned + %d new + %d updated", unassigned_count, assigned_count, existing_updated)

        except Exception as e:
            logger.exception("Catch-up scan failed: %s", e)

    import threading as _threading
    _threading.Thread(target=_catchup_scan, daemon=True, name="catchup-scan").start()

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
