"""Enhanced agent: Claude (Anthropic API) based ticket analysis with pattern matching.

Skill detection uses two signals:
  1. Regex patterns on the ticket text (fast, keyword-based)
  2. Tags from similar solved issues found via DevRev hybrid search
     (high confidence — if a past solved issue had tag "redemption_report",
      a new similar issue is very likely solvable with the same skill)
"""
import logging
import re
from typing import Optional

from .config import Config
from .prompts import get_system_prompt
from .retriever import find_relevant, format_relevant_for_prompt

logger = logging.getLogger(__name__)

# Pattern → skill mapping (keyword-based, used when no tag signal is available)
# Order matters: more specific patterns first to avoid false positives
ISSUE_PATTERNS = [
    # DNS / Kong PR — must come before gc patterns (no overlap risk)
    (re.compile(r"add\s+(dns|domain|route|cname)|vishnu|terraform.?kong|kong.?pr|cors.?origin|subdomain.*razorpay|razorpay\.com.*\bdomain\b", re.I), "vishnu-terraform-kong-pr"),
    # GC cancellation — before redemption-report (cancel is more specific)
    (re.compile(r"cancel\s+(gc|gift.?card|card)|gc\s+cancel|deactivate\s+(gc|gift.?card)", re.I), "gc-cancellation"),
    # GC redemption report
    (re.compile(r"gc|gift.?card|card.?number|redemption.?report", re.I), "gc-redemption-report"),
    # Order trace
    (re.compile(r"order.?id|order.?fail|reward.?order|order.?not\s+(visible|showing|found)", re.I), "order-trace-debugger"),
    # Invalid rewards
    (re.compile(r"invalid.?reward|reward.?invalid", re.I), "invalid-rewards-debugger"),
    # RMP Gandalf
    (re.compile(r"\brmp\b|gandalf", re.I), "rmp-gandalf"),
]

# Tag → skill mapping (from solved issues — highest confidence signal)
TAG_SKILL_MAP = {
    # GC
    "redemption_report": "gc-redemption-report",
    "gc_redemption": "gc-redemption-report",
    "gc_cancellation": "gc-cancellation",
    "gc_cancel": "gc-cancellation",
    # Orders
    "order_trace": "order-trace-debugger",
    "order_debug": "order-trace-debugger",
    # Others
    "invalid_rewards": "invalid-rewards-debugger",
    "rmp_gandalf": "rmp-gandalf",
    "rmp_order": "rmp-gandalf",
    "voucher_upload": "voucher-benefit-upload",
    # DNS / Kong PR
    "dns_pr": "vishnu-terraform-kong-pr",
    "kong_pr": "vishnu-terraform-kong-pr",
    "dns_record": "vishnu-terraform-kong-pr",
    "cors_origin": "vishnu-terraform-kong-pr",
    "engage_loyalty_dns": "vishnu-terraform-kong-pr",
}


def _detect_skill_from_text(text: str) -> Optional[str]:
    """Detect skill from ticket text using regex patterns."""
    for pattern, skill in ISSUE_PATTERNS:
        if pattern.search(text):
            return skill
    return None


def _detect_skill_from_tags(tags: list[dict]) -> Optional[str]:
    """
    Detect skill from tags of similar solved issues.
    This is the strongest signal — if a past solved issue had a known tag,
    the same skill almost certainly applies.
    Also handles skill:xxx tags that the bot adds on closure.
    """
    for tag in tags:
        name = (tag.get("name") or "").lower().strip()
        # Direct skill tag (added by bot on closure: "skill:gc-redemption-report")
        if name.startswith("skill:"):
            return name.split(":", 1)[1]
        # Known tag → skill mapping
        if name in TAG_SKILL_MAP:
            return TAG_SKILL_MAP[name]
    return None


def detect_skill(ticket_text: str, similar_tags: list[dict] = None) -> tuple[Optional[str], str]:
    """
    Detect the best skill for a ticket using both signals:
      1. Tags from similar solved issues (high confidence)
      2. Regex patterns on ticket text (medium confidence)

    Returns: (skill_name, confidence) where confidence is "high"/"medium"/"low"
    """
    # Signal 1: Tags from similar solved issues (strongest)
    if similar_tags:
        tag_skill = _detect_skill_from_tags(similar_tags)
        if tag_skill:
            return tag_skill, "high"

    # Signal 2: Regex on ticket text
    text_skill = _detect_skill_from_text(ticket_text)
    if text_skill:
        return text_skill, "medium"

    return None, "low"


def enhanced_reply(ticket_text: str, config: Config) -> str:
    """
    Analyse ticket using Anthropic Claude API.
    Pre-detects issue type via tag matching + pattern matching for faster, more accurate routing.
    Returns formatted analysis string.
    """
    api_key = config.anthropic.api_key
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Add it to scripts/.env:\n"
            "  ANTHROPIC_API_KEY=sk-ant-...\n"
            "Get your key at https://console.anthropic.com/"
        )

    # Fetch similar solved issues via hybrid search for tag-based skill detection
    similar_tags = []
    similar_context = ""
    try:
        from . import devrev_client
        similar = devrev_client.find_similar_issues(ticket_text, limit=5, only_solved=True)
        for s in similar:
            tags = devrev_client.get_tags_from_work(s)
            similar_tags.extend(tags)
            did = s.get("display_id", "?")
            tag_str = ", ".join(t["name"] for t in tags) if tags else "none"
            similar_context += f"- {did}: {(s.get('title') or '')[:80]} (tags: {tag_str})\n"
    except Exception as e:
        logger.debug("Hybrid search in enhanced_reply: %s", e)

    hint_skill, confidence = detect_skill(ticket_text, similar_tags)

    hint_lines = ""
    if hint_skill:
        source = "similar solved issues' tags" if confidence == "high" else "keyword patterns"
        hint_lines = (
            f"\nDetected skill: '{hint_skill}' (confidence: {confidence}, source: {source})\n"
        )
    if similar_context:
        hint_lines += f"\nSimilar solved issues from DevRev:\n{similar_context}\n"

    system = get_system_prompt(config)
    top_k = getattr(config.retriever, "top_k", 12)
    relevant = find_relevant(ticket_text.strip(), config, top_k=top_k)
    relevant_block = format_relevant_for_prompt(relevant, max_items=min(10, top_k))

    user_content = (
        f"Current issue:\n\n{ticket_text.strip()}\n"
        f"{hint_lines}"
        "---\n"
        f"Relevant past tickets:\n\n{relevant_block}\n\n"
        "---\n"
        "Think step-by-step and respond with:\n"
        "**Analysis:** <what the issue is>\n\n"
        "**Approach:**\n<numbered steps>\n\n"
        "**Skill to run:** <skill-name>\n"
        "**Confidence:** high/medium/low\n\n"
        "Reply *Yes* to run the skill, or *No* to cancel."
    )

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=config.anthropic.model,
            max_tokens=config.anthropic.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
        )
        return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
    except Exception as e:
        logger.error("enhanced_reply failed: %s", e)
        raise
