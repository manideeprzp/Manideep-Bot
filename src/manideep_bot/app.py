"""Manideep Bot: Slack Socket Mode, @mention + thread replies (Yes/Proceed → run skill; Approve → post on DevRev and close)."""
import logging
import os
import re

from .config import load_config
from .agent import reply

logger = logging.getLogger(__name__)

# Per-thread state: (channel_id, thread_ts) -> dict
_thread_state = {}


def _thread_key(event):
    ch = event.get("channel", "")
    ts = event.get("thread_ts") or event.get("ts", "")
    return (ch, ts)


def _normalize_approve(text):
    t = (text or "").strip().lower()
    if t in ("yes", "proceed", "y", "go"):
        return "yes"
    if t in ("approve", "approved", "close it", "post and close"):
        return "approve"
    return None


def _parse_work_id(text):
    """Extract DevRev work ID from text (e.g. ISSUE-123, or https://app.devrev.ai/...)."""
    if not text:
        return None
    m = re.search(r"(ISSUE|TICKET|INC)-[\w-]+", text, re.I)
    if m:
        return m.group(0)
    m = re.search(r"devrev\.ai/[^/\s]+/([A-Za-z0-9_-]+)", text)
    if m:
        return m.group(1)
    return None


def _parse_skill_name(text):
    """Extract skill name from agent reply (supports both old and new structured formats)."""
    if not text:
        return None

    # Try structured format: **Skill to run:** skill-name
    m = re.search(r"\*\*skill\s+to\s+run:\*\*\s*([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()

    # Try legacy format: skill: skill-name
    m = re.search(r"skill[:\s]+([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()

    return None


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

    def handle_mention(event, say, client):
        thread_ts = event.get("thread_ts") or event.get("ts")
        user_id = event.get("user", "")
        text = re.sub(r"<@\w+>", "", (event.get("text") or "")).strip()

        if config.slack.allowed_user_ids and user_id not in config.slack.allowed_user_ids:
            say(text="You are not allowed to use this bot.", thread_ts=thread_ts)
            return

        if not text:
            say(
                text="Share a ticket title/description or link and I'll suggest an approach. Then reply **Yes** to run the skill, or **Approve** (after I post output) to post on the ticket and close it.",
                thread_ts=thread_ts,
            )
            return

        say(text="Thinking…", thread_ts=thread_ts)
        try:
            response = reply(text, config)
            if len(response) > 3900:
                response = response[:3900] + "\n… (truncated)"
            say(text=response, thread_ts=thread_ts)
            key = _thread_key(event)
            _thread_state[key] = {
                "step": "suggested",
                "ticket_text": text,
                "work_id": _parse_work_id(text),
                "skill_name": _parse_skill_name(response) or "order-trace-debugger",
            }
        except Exception as e:
            logger.exception("Agent error")
            say(text=f"Error: {e}", thread_ts=thread_ts)

    def handle_message(event, say, client):
        # Only handle replies in threads (from @mention or from bucket post)
        thread_ts = event.get("thread_ts")
        if not thread_ts:
            return
        ch = event.get("channel", "")
        key = (ch, thread_ts)
        state = _thread_state.get(key)
        # If not from @mention, check bucket thread state (bot posted "my bucket" suggestion)
        from . import bucket as bucket_mod
        if not state:
            state = bucket_mod.get_thread_state_from_bucket(ch, thread_ts)
            is_bucket = bool(state)
        else:
            is_bucket = False
        if not state:
            return

        user_id = event.get("user", "")
        text = (event.get("text") or "").strip()
        cmd = _normalize_approve(text)
        # "Done" same as "Yes" for bucket flow
        if not cmd and (text or "").strip().lower() in ("done", "run it"):
            cmd = "yes"

        if cmd == "yes" and state.get("step") == "suggested":
            from . import skill_runner
            ticket_text = state.get("ticket_text") or ""
            skill_name = state.get("skill_name") or "order-trace-debugger"
            out, ok = skill_runner.run_skill(skill_name, ticket_text)
            if not ok:
                say(text=f"Could not run skill: {out}\nReply with **Done** again after adding the missing info (e.g. order_id).", thread_ts=thread_ts)
                return
            say(text=f"Work done. Output:\n```\n{out[:2500]}\n```\n\nReview. If correct, reply **Approve** to post this on the ticket and close it.", thread_ts=thread_ts)
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
                # Resolve display_id to full work_id if we only have display_id (bucket has work_id)
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
                say(text="I don't have the ticket ID. Please paste the DevRev work ID (e.g. ISSUE-123) so I can post the update and close it.", thread_ts=thread_ts)
                return
            try:
                from . import devrev_client
                summary = state.get("summary") or state.get("output") or "Resolved by Manideep Bot."
                devrev_client.timeline_entry_create(work_id, f"Resolution:\n{summary}")
                devrev_client.work_update_stage(work_id, config.devrev.closed_stage_name)
                say(text=f"Posted update on ticket and set stage to **{config.devrev.closed_stage_name}**. Done.", thread_ts=thread_ts)
            except Exception as e:
                logger.exception("DevRev post/close: %s", e)
                say(text=f"Failed to post/close: {e}", thread_ts=thread_ts)
            if is_bucket:
                bucket_mod.pop_bucket_thread_state(ch, thread_ts)
            else:
                _thread_state.pop(key, None)
            return

    @app.event("app_mention")
    def on_mention(event, say, client):
        handle_mention(event, say, client)

    @app.event("message")
    def on_message(event, say, client):
        if event.get("bot_id"):
            return
        handle_message(event, say, client)

    handler = SocketModeHandler(app, config.slack.app_token)
    logger.info("Manideep Bot starting (Socket Mode); @mention + thread Yes/Approve")
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
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("Loading config and starting Manideep Bot...")
    try:
        run_slack_bot()
    except SystemExit as e:
        raise
    except Exception as e:
        logger.exception("Bot failed to start: %s", e)
        raise


if __name__ == "__main__":
    run()
