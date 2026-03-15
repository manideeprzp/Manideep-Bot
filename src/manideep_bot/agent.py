"""Ticket analysis using Anthropic Claude API (same model as Cursor AI)."""
import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel

from .config import Config
from .prompts import get_system_prompt
from .retriever import find_relevant, format_relevant_for_prompt

logger = logging.getLogger(__name__)


class TicketAnalysis(BaseModel):
    analysis: str
    approach: str
    skill_name: str
    confidence: Literal["high", "medium", "low"]
    missing_info: Optional[list[str]] = None
    recommendation: Literal["proceed", "need_more_info", "not_applicable"]


def _call_claude(user_content: str, system: str, config: Config) -> str:
    """Call Anthropic Claude API and return formatted analysis text."""
    api_key = config.anthropic.api_key
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not set. Add it to scripts/.env:\n"
            "  ANTHROPIC_API_KEY=sk-ant-...\n"
            "Get one at https://console.anthropic.com/"
        )

    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic")

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=config.anthropic.model,
        max_tokens=config.anthropic.max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )

    raw = "".join(block.text for block in resp.content if hasattr(block, "text"))

    # Try to parse as JSON (structured output)
    try:
        cleaned = raw.strip()
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        if cleaned.startswith("{"):
            parsed = json.loads(cleaned)
            result = TicketAnalysis(**parsed)
            text = (
                f"**Analysis:** {result.analysis}\n\n"
                f"**Approach:**\n{result.approach}\n\n"
                f"**Skill to run:** {result.skill_name}\n"
                f"**Confidence:** {result.confidence}\n"
            )
            if result.missing_info:
                text += "\n**Missing info:**\n- " + "\n- ".join(result.missing_info) + "\n"
            if result.recommendation == "proceed":
                text += "\n\nReply *Yes* to run the skill, or *No* to cancel."
            elif result.recommendation == "need_more_info":
                text += "\n\nPlease provide the missing info listed above."
            else:
                text += "\n\nThis issue may not be applicable for automated resolution."
            return text
    except Exception:
        pass  # not JSON — return raw text as-is

    return raw


def reply(user_message: str, config: Config) -> str:
    """
    Analyse a ticket and return a suggestion.
    Uses Anthropic Claude — the same model that powers Cursor AI.
    """
    system = get_system_prompt(config)
    top_k = getattr(config.retriever, "top_k", 12) if getattr(config, "retriever", None) else 12
    relevant = find_relevant(user_message.strip(), config, top_k=top_k)
    relevant_block = format_relevant_for_prompt(relevant, max_items=min(10, top_k))

    user_content = (
        f"Current issue (title/description):\n\n{user_message.strip()}\n\n"
        "---\n"
        f"Relevant past tickets (use these to suggest a similar approach):\n\n{relevant_block}\n\n"
        "---\n"
        "Think step-by-step:\n"
        "1. What type of issue is this? (order trace, gc redemption, booking, cancellation, etc.)\n"
        "2. Which past ticket is most similar?\n"
        "3. What skill was used for similar issues?\n"
        "4. What information is needed to run the skill?\n"
        "5. Respond in JSON:\n"
        "   { \"analysis\": \"...\", \"approach\": \"...\", \"skill_name\": \"...\","
        " \"confidence\": \"high|medium|low\", \"missing_info\": [], \"recommendation\": \"proceed|need_more_info|not_applicable\" }"
    )

    return _call_claude(user_content, system, config)
