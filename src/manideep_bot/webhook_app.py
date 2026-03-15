"""
DevRev webhook receiver: POST /webhooks/devrev with work_created events.
Verifies X-DevRev-Signature (HMAC-SHA256), responds to verify challenge,
enqueues work_created for async processing. Worker fetches work, filters
by monitor criteria, runs agent + posts to Slack (same flow as monitor).
"""
import hashlib
import hmac
import json
import logging
import os
import queue
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent.parent.parent

# In-memory queue for work_created events (work_id strings)
_work_queue: queue.Queue = queue.Queue()


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify X-DevRev-Signature: HMAC-SHA256(secret, raw_body)."""
    if not secret or not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _work_matches_filters(work: dict, config) -> bool:
    """Return True if work matches monitor new_ticket_filters (parts, stage, unassigned)."""
    stage_names = getattr(config.monitor, "new_ticket_stage_names", None) or []
    parts = list(config.monitor.new_ticket_filter_parts or [])
    part_names = getattr(config.monitor, "new_ticket_filter_part_names", None) or []
    if part_names:
        from . import monitor as mon
        resolved = mon._resolve_part_names_to_ids(part_names)
        for pid in resolved:
            if pid not in parts:
                parts.append(pid)
    unassigned_only = getattr(config.monitor, "new_ticket_unassigned_only", False)

    if stage_names:
        stage_set = {s.strip().lower() for s in stage_names if s}
        work_stage = ((work.get("stage") or {}).get("name") or "").strip().lower()
        if work_stage not in stage_set:
            return False
    if parts:
        work_parts = work.get("applies_to_part") or []
        if not work_parts or not any(p in parts for p in work_parts):
            return False
    if unassigned_only and (work.get("owned_by") or []):
        return False
    return True


def _process_work_created(work_id: str) -> None:
    """Fetch work, filter, analyze, post to Slack (same as monitor new-ticket path)."""
    from .config import load_config
    from . import devrev_client
    from .agent import reply
    from .retriever import find_relevant, format_related_ticket_links
    from . import bucket as bucket_mod

    config = load_config()
    if not config.devrev.api_key:
        logger.warning("DEVREV_API_KEY not set; skipping webhook work %s", work_id)
        return

    try:
        data = devrev_client.works_list(work_ids=[work_id], limit=1)
        works = data.get("works") or []
        if not works:
            logger.warning("Work %s not found", work_id)
            return
        w = works[0]
        if not _work_matches_filters(w, config):
            logger.info("Work %s does not match monitor filters; skipping", work_id)
            return

        title = (w.get("title") or "")[:200]
        body = (w.get("body") or "")[:3000]
        display_id = w.get("display_id") or work_id
        ticket_text = f"{title}\n\n{body}".strip() or str(display_id)

        response = reply(ticket_text, config)
        skill_name = _parse_skill_name(response)
        if len(response) > 2800:
            response = response[:2800] + "\n… (truncated)"

        relevant = find_relevant(ticket_text, config, top_k=5)
        related_line = format_related_ticket_links(
            relevant,
            app_base_url=config.devrev.app_base_url,
            max_items=5,
        )

        message_parts = [
            "🆕 *New PSE Ticket* (webhook)",
            f"*{display_id}* — {title[:80]}",
            "",
            response,
        ]
        if related_line:
            message_parts.append("")
            message_parts.append(related_line)
        message_parts.append("")
        message_parts.append("—_Reply **Yes** to run the skill, then **Approve** to post resolution and close ticket._")
        message_text = "\n".join(message_parts)

        _slack_post_interactive(
            text=message_text,
            config=config,
            work_id=work_id,
            display_id=display_id,
            ticket_text=ticket_text,
            skill_name=skill_name,
        )
    except Exception as e:
        logger.exception("Process work_created %s: %s", work_id, e)


def _parse_skill_name(text: str) -> str:
    import re
    if not text:
        return "order-trace-debugger"
    m = re.search(r"\*\*skill\s+to\s+run:\*\*\s*([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"skill[:\s]+([a-z0-9-]+)", text, re.I)
    if m:
        return m.group(1).strip()
    return "order-trace-debugger"


def _slack_post_interactive(text: str, config, work_id: str, display_id: str, ticket_text: str, skill_name: str):
    """Post to Slack bucket channel with thread state (reuse monitor pattern)."""
    channel_id = config.slack.bucket_channel_id or os.environ.get("SLACK_BUCKET_CHANNEL_ID") or ""
    if not channel_id:
        logger.warning("SLACK_BUCKET_CHANNEL_ID not set; cannot post from webhook")
        return
    if not config.slack.bot_token:
        logger.warning("SLACK_BOT_TOKEN not set; cannot post from webhook")
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
            bucket_mod.set_bucket_thread_state(channel_id, ts, {
                "step": "suggested",
                "work_id": work_id,
                "display_id": display_id,
                "ticket_text": ticket_text,
                "skill_name": skill_name,
            })
            logger.info("Webhook: posted to Slack for %s", display_id)
    except Exception as e:
        logger.warning("Webhook Slack post failed: %s", e)


def _worker_loop() -> None:
    """Consume work IDs from queue and process (analyze + Slack)."""
    while True:
        try:
            work_id = _work_queue.get()
            if work_id is None:
                break
            _process_work_created(work_id)
        except Exception as e:
            logger.exception("Webhook worker: %s", e)


def create_app():
    """Create FastAPI app for DevRev webhook endpoint."""
    try:
        from fastapi import FastAPI, Request, Response
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError("Install fastapi and uvicorn: pip install fastapi uvicorn")

    app = FastAPI(title="Manideep Bot Webhook")

    @app.post("/webhooks/devrev")
    async def devrev_webhook(request: Request):
        body = await request.body()
        signature = request.headers.get("X-DevRev-Signature", "")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            logger.warning("Webhook invalid JSON: %s", e)
            return Response(status_code=400, content="Invalid JSON")

        event_type = payload.get("type", "")

        # DevRev sends "verify" before we have the secret (secret comes in webhooks.create response).
        # So allow verify without signature; require signature for all other events.
        if event_type != "verify":
            config = None
            try:
                from .config import load_config
                config = load_config()
                secret = config.devrev.webhook_secret or os.environ.get("DEVREV_WEBHOOK_SECRET", "")
            except Exception:
                secret = os.environ.get("DEVREV_WEBHOOK_SECRET", "")
            if not _verify_signature(body, signature, secret):
                logger.warning("Webhook signature verification failed")
                return Response(status_code=401, content="Invalid signature")

        if event_type == "verify":
            challenge = (payload.get("verify") or {}).get("challenge")
            if not challenge:
                return Response(status_code=400, content="Missing challenge")
            return JSONResponse(content={"challenge": challenge})

        if event_type == "work_created":
            work_created = payload.get("work_created") or {}
            work_id = work_created.get("id") if isinstance(work_created, dict) else None
            if work_id:
                _work_queue.put(work_id)
                logger.info("Webhook: enqueued work_created %s", work_id)
            return Response(status_code=200, content="OK")

        logger.info("Webhook: ignored event type %s", event_type)
        return Response(status_code=200, content="OK")

    return app


def run_worker_background():
    """Start the webhook worker thread (call once at startup)."""
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
    logger.info("Webhook worker thread started")
