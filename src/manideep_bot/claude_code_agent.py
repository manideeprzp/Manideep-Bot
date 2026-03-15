"""Claude Code Agent — file-based interface for Cursor AI (Claude Code) to analyse tickets.

How it works:
  1. Bot receives a ticket → fetches similar tickets via DevRev hybrid search
  2. Writes a rich request file to data/claude_requests/ with similar tickets, tags, fields
  3. Claude Code (you, in Cursor) sees the file, uses DevRev MCP tools, writes response
  4. Bot polls for the response file and posts it to Slack
  5. On "Approve", bot uses the tag/field suggestions to close with full metadata

This lets Cursor AI + DevRev MCP be the analyst — no external API key needed.
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

from .config import Config

logger = logging.getLogger(__name__)

_REQUEST_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "claude_requests"
_RESPONSE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "claude_responses"
_SIMILAR_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "similar_tickets"
_POLL_INTERVAL = 5    # seconds between checks
_TIMEOUT = 300        # 5 minutes max wait


def _ensure_dirs():
    _REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    _RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    _SIMILAR_DIR.mkdir(parents=True, exist_ok=True)


def _fetch_similar_context(ticket_text: str, ticket_id: str) -> str:
    """
    Use DevRev hybrid search to find similar solved tickets.
    Saves full data to data/similar_tickets/<ticket_id>.json for the approve step.
    Returns a formatted markdown block for the request file.
    """
    from . import devrev_client
    from .retriever import find_relevant, format_relevant_for_prompt

    lines = []
    similar_data = {"similar_tickets": [], "suggested_tags": [], "suggested_fields": {}}

    # 1. DevRev hybrid search (semantic search across all tickets)
    try:
        similar = devrev_client.find_similar_issues(ticket_text, limit=5, only_solved=True)
        if similar:
            lines.append("### Similar Solved Tickets (DevRev Hybrid Search)\n")
            for i, w in enumerate(similar, 1):
                display_id = w.get("display_id") or "?"
                title = (w.get("title") or "")[:120]
                state = w.get("state") or "?"
                stage = (w.get("stage") or {}).get("name") or "?"
                tags = devrev_client.get_tags_from_work(w)
                custom_fields = devrev_client.get_custom_fields_from_work(w)
                tag_str = ", ".join(f"`{t['name']}`" for t in tags) if tags else "none"

                lines.append(f"**{i}. {display_id}** — {title}")
                lines.append(f"   State: {state} | Stage: {stage}")
                lines.append(f"   Tags: {tag_str}")
                if custom_fields:
                    # Show key fields readably (cause_code, reason_for_breach, pod, severity, etc.)
                    readable = {}
                    for k, v in custom_fields.items():
                        label = k.replace("ctype__", "").replace("tnt__", "").replace("_", " ").title()
                        if isinstance(v, str) and len(v) < 200:
                            readable[label] = v
                    if readable:
                        field_str = " | ".join(f"{k}: {v}" for k, v in readable.items())
                        lines.append(f"   Fields: {field_str}")
                lines.append("")

                similar_data["similar_tickets"].append({
                    "display_id": display_id,
                    "title": title,
                    "state": state,
                    "stage": stage,
                    "tags": tags,
                    "custom_fields": custom_fields,
                    "id": w.get("id", ""),
                })

            # Collect all unique tags from similar tickets as suggestions
            all_tags = {}
            for s in similar_data["similar_tickets"]:
                for t in s.get("tags", []):
                    name = t.get("name", "")
                    if name and name not in all_tags:
                        all_tags[name] = t.get("value", "")
            similar_data["suggested_tags"] = [{"name": k, "value": v} for k, v in all_tags.items()]

            # Collect common custom fields as suggestions
            all_fields = {}
            for s in similar_data["similar_tickets"]:
                for k, v in s.get("custom_fields", {}).items():
                    if k not in all_fields:
                        all_fields[k] = v
            similar_data["suggested_fields"] = all_fields

            # Tag-based skill detection (strongest confidence signal)
            from .enhanced_agent import detect_skill, TAG_SKILL_MAP
            all_similar_tags = similar_data["suggested_tags"]
            detected_skill, confidence = detect_skill(ticket_text, all_similar_tags)
            if detected_skill:
                similar_data["detected_skill"] = detected_skill
                similar_data["detected_confidence"] = confidence
                source = "tags from similar solved issues" if confidence == "high" else "keyword patterns"
                lines.append(f"### Auto-Detected Skill\n")
                lines.append(f"**Skill:** `{detected_skill}` | **Confidence:** {confidence} | **Source:** {source}\n")
                if confidence == "high":
                    known_tags = set(TAG_SKILL_MAP.keys())
                    matching = [t["name"] for t in all_similar_tags
                                if t["name"].lower() in known_tags or t["name"].lower().startswith("skill:")]
                    if matching:
                        lines.append(f"_Matched tags: {', '.join(f'`{t}`' for t in matching)}_\n")
    except Exception as e:
        logger.warning("Hybrid search for similar tickets failed: %s", e)
        lines.append("_(DevRev hybrid search unavailable)_\n")

    # 2. Local BM25 retrieval (solved tickets from my_solved_tickets.json)
    try:
        from .config import load_config
        config = load_config()
        relevant = find_relevant(ticket_text, config, top_k=5)
        if relevant:
            relevant_block = format_relevant_for_prompt(relevant, max_items=5)
            lines.append("### Similar Solved Tickets (Local Knowledge Base)\n")
            lines.append(relevant_block)
            lines.append("")
    except Exception as e:
        logger.debug("Local retrieval: %s", e)

    # Save similar data for the approve step
    _ensure_dirs()
    similar_file = _SIMILAR_DIR / f"{ticket_id}.json"
    try:
        similar_file.write_text(json.dumps(similar_data, indent=2))
    except Exception as e:
        logger.debug("Save similar data: %s", e)

    return "\n".join(lines)


def load_similar_data(ticket_id: str) -> dict:
    """Load saved similar ticket data (tags, fields) for the approve step."""
    similar_file = _SIMILAR_DIR / f"{ticket_id}.json"
    if similar_file.exists():
        try:
            return json.loads(similar_file.read_text())
        except Exception:
            pass
    return {"similar_tickets": [], "suggested_tags": [], "suggested_fields": {}}


def _write_request(ticket_id: str, ticket_text: str, context: str = "") -> Path:
    _ensure_dirs()

    similar_context = _fetch_similar_context(ticket_text, ticket_id)

    req_file = _REQUEST_DIR / f"{ticket_id}.md"
    req_file.write_text(
        f"# Ticket Analysis Request: {ticket_id}\n\n"
        f"## Issue\n\n{ticket_text}\n\n"
        f"{('## Additional Context\n\n' + context + '\n\n') if context else ''}"
        "---\n\n"
        f"## Similar Tickets & Reference Data\n\n{similar_context}\n\n"
        "---\n\n"
        "## Instructions for Claude Code\n\n"
        f"Analyse this ticket and write your response to:\n"
        f"`data/claude_responses/{ticket_id}.md`\n\n"
        "**You have DevRev MCP tools available.** Use them to:\n"
        "- `get_issue` / `get_ticket` — fetch full ticket details\n"
        "- `hybrid_search` — find more similar tickets if needed\n"
        "- `add_comment` — add analysis notes directly on the ticket\n"
        "- `fetch_object_context` — get rich context about the ticket\n\n"
        "**Include in your response:**\n"
        "- **Analysis:** what the issue is\n"
        "- **Approach:** step-by-step resolution\n"
        "- **Skill to run:** e.g. `gc-redemption-report`, `order-trace-debugger`, `gc-cancellation`, `rmp-gandalf`\n"
        "- **Confidence:** high / medium / low\n"
        "- **Suggested tags:** (copy relevant tags from similar solved tickets above + add `skill:<skill-name>`)\n"
        "- **Suggested fields:** (cause code, category, etc. from similar solved tickets)\n"
    )
    return req_file


def _poll_response(ticket_id: str, timeout: int = _TIMEOUT) -> Optional[str]:
    resp_file = _RESPONSE_DIR / f"{ticket_id}.md"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if resp_file.exists():
            content = resp_file.read_text().strip()
            if content:
                resp_file.unlink(missing_ok=True)
                return content
        time.sleep(_POLL_INTERVAL)
    return None


def claude_code_reply(
    ticket_text: str,
    config: Config,
    ticket_id: str = None,
    channel: str = None,
    thread_ts: str = None,
) -> Tuple[str, Optional[str]]:
    """
    Submit ticket for Claude Code (Cursor AI) to analyse.

    Fetches similar tickets via DevRev hybrid search before writing the request,
    so Claude Code has full context including tags and fields from past tickets.

    Returns:
        (waiting_message, ticket_id) — bot posts "waiting for analysis..."
        Claude Code fills data/claude_responses/<ticket_id>.md
        Bot then posts the actual analysis when the file appears.
    """
    ticket_id = ticket_id or f"ticket_{int(time.time())}"
    req_file = _write_request(ticket_id, ticket_text)

    waiting_msg = (
        f"Submitted to Claude Code for analysis (`{ticket_id}`)\n\n"
        f"Request saved to: `{req_file.relative_to(Path.cwd()) if req_file.is_relative_to(Path.cwd()) else req_file}`\n\n"
        f"Waiting for Claude Code analysis...\n\n"
        f"_Claude Code: please analyse and write response to `data/claude_responses/{ticket_id}.md`_"
    )

    logger.info("Claude Code request written: %s", req_file)
    return waiting_msg, ticket_id
