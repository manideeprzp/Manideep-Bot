#!/usr/bin/env python3
"""
Auto-watcher: fully automatic ticket analysis — no Cursor/Claude Code typing needed.

Watches data/claude_requests/*.md for new ticket analysis requests written by the bot,
generates analysis using detect_skill() + past solved tickets, writes response to
data/claude_responses/<ticket_id>.md, which response_watcher.py picks up and posts to Slack.

Run in background:
    nohup .venv/bin/python scripts/auto_watcher.py > logs/auto_watcher.log 2>&1 &

The complete zero-intervention flow:
    Ticket arrives in Slack
        → bot writes data/claude_requests/ISS-XXXXXX.md
        → auto_watcher detects it (within 5 seconds)
        → generates analysis + skill suggestion
        → writes data/claude_responses/ISS-XXXXXX.md
        → response_watcher posts analysis to Slack
        → bot auto-runs safe skills immediately
        → you just reply Approve to close
"""
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s auto_watcher — %(message)s",
)
logger = logging.getLogger(__name__)

BOT_ROOT = Path(__file__).resolve().parent.parent
REQUESTS_DIR = BOT_ROOT / "data" / "claude_requests"
RESPONSES_DIR = BOT_ROOT / "data" / "claude_responses"


def _load_deps():
    """Import bot modules (lazy so env is loaded first)."""
    from manideep_bot.enhanced_agent import detect_skill
    from manideep_bot.retriever import find_relevant, format_relevant_for_prompt
    from manideep_bot.config import load_config
    return detect_skill, find_relevant, format_relevant_for_prompt, load_config


def _extract_ticket_text(md_content: str) -> tuple[str, str]:
    """Extract ticket_id and full text from a claude_requests .md file."""
    ticket_id = ""
    # Title line: # Ticket Analysis Request: ISS-XXXXXX
    m = re.search(r"ISS-\d+", md_content)
    if m:
        ticket_id = m.group(0)

    # Extract the ticket body between markers
    text_parts = []
    capture = False
    for line in md_content.splitlines():
        if line.startswith("## Ticket:") or line.startswith("## Issue:") or line.startswith("**Title"):
            capture = True
        if capture:
            text_parts.append(line)
        if capture and line.startswith("## Similar") :
            break

    return ticket_id, "\n".join(text_parts) if text_parts else md_content


def analyze(request_file: Path, deps: dict) -> str:
    """
    Read a request .md file and generate a full analysis response.
    Returns the response as a markdown string matching the bot's expected format.

    Args:
        request_file: Path to the ISS-XXXXXX.md request file
        deps: dict with keys detect_skill, find_relevant, format_relevant, config
    """
    detect_skill = deps["detect_skill"]
    find_relevant = deps["find_relevant"]
    format_relevant = deps["format_relevant"]
    config = deps["config"]

    content = request_file.read_text()
    ticket_id = request_file.stem  # filename is ISS-XXXXXX.md
    ticket_text = content  # pass full content for richer matching

    # Detect skill via keyword matching
    skill_name, confidence = detect_skill(ticket_text)
    skill_name = skill_name or "none"
    conf_label = confidence if confidence else "low"

    # Find similar past solved tickets
    similar_context = ""
    suggested_tags = []
    try:
        relevant = find_relevant(ticket_text, config, top_k=5)
        similar_context = format_relevant(relevant, max_items=5)
        # Extract tags from similar tickets
        for item in (relevant or []):
            for tag in (item.get("tag_names") or item.get("tags") or []):
                t = tag.strip() if isinstance(tag, str) else (tag.get("name") or "")
                if t and t not in suggested_tags:
                    suggested_tags.append(t)
    except Exception as e:
        logger.debug("Retriever error: %s", e)

    # Build approach steps based on skill
    approach_steps = _build_approach(skill_name, ticket_text)

    # Build suggested tags
    if skill_name and skill_name != "none":
        skill_tag = f"skill:{skill_name}"
        if skill_tag not in suggested_tags:
            suggested_tags.insert(0, skill_tag)

    tags_str = ", ".join(f"`{t}`" for t in suggested_tags[:6]) if suggested_tags else "_none_"

    # Build analysis summary
    summary = _build_summary(skill_name, ticket_text, ticket_id)

    response = (
        f"**Analysis:** {summary}\n\n"
        f"**Approach:**\n{approach_steps}\n\n"
        f"**Skill to run:** {skill_name}\n"
        f"**Confidence:** {conf_label}\n\n"
        f"**Suggested tags:** {tags_str}\n"
        f"**Suggested fields:** cause_code: (set on close), pse_pod: (set on close), severity: Sev-4\n"
    )

    if similar_context:
        response += f"\n**Similar past tickets:**\n{similar_context}\n"

    response += "\nReply *Yes* to run the skill, or *Approve* if already reviewed."

    return response


def _build_summary(skill_name: str, text: str, ticket_id: str) -> str:
    """Generate a 1-2 sentence analysis summary."""
    text_lower = text.lower()
    if skill_name == "gc-redemption-report":
        # Match: "card number: 7717386747", "GC123456789", "RZ97262589925171", or bare 10+ digit number
        card_m = (
            re.search(r"card[_\s-]?number[\s:=]+([A-Za-z0-9]+)", text, re.I)
            or re.search(r"\b(GC[A-Z0-9]{6,})\b", text, re.I)
            or re.search(r"\b([A-Z]{2}[0-9]{9,})\b", text, re.I)
            or re.search(r"\b([0-9]{10,})\b", text)
        )
        card = card_m.group(1) if card_m else "provided card"
        return f"Customer has a gift card issue for {card}. Running redemption report to check balance and transaction history."
    if skill_name == "gc-cancellation":
        return "Gift card cancellation requested. Will verify card status and proceed with cancellation after confirming reason."
    if skill_name == "order-trace-debugger":
        order_m = re.search(r"order[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)", text, re.I)
        order_id = order_m.group(1) if order_m else "the order"
        return f"Order issue detected for {order_id}. Tracing through RMP, Offers Engine, and Procurement systems."
    if skill_name == "vishnu-terraform-kong-pr":
        url_m = re.search(r"([a-zA-Z0-9_-]+\.razorpay\.com)", text)
        url = url_m.group(1) if url_m else "the requested domain"
        return f"DNS and CORS origin setup required for {url}. Will create PRs in vishnu (DNS record) and terraform-kong (CORS origin)."
    if skill_name == "invalid-rewards-debugger":
        return "Invalid rewards issue detected. Debugging reward eligibility and configuration."
    if skill_name == "rmp-gandalf":
        return "RMP Gandalf access or permission issue. Checking authorization configuration."
    return f"Ticket {ticket_id} received. Analysing based on past solved tickets and issue patterns."


def _build_approach(skill_name: str, text: str) -> str:
    """Generate numbered approach steps for the skill."""
    if skill_name == "gc-redemption-report":
        return (
            "1. Run `gc-redemption-report` with the card number\n"
            "2. Check transactions — if only recharge entries → full balance → cancellation case\n"
            "3. If redemptions found → card was used → share the report\n"
            "4. Update ticket with findings"
        )
    if skill_name == "gc-cancellation":
        return (
            "1. Verify cancellation reason is present\n"
            "2. Run `gc-cancellation` with card number + reason\n"
            "3. Confirm cancellation in GCOMS\n"
            "4. Update ticket with cancellation confirmation"
        )
    if skill_name == "order-trace-debugger":
        return (
            "1. Run `order-trace-debugger` with the order_id\n"
            "2. Check order state and customer-to-order mapping\n"
            "3. Verify visibility flags and permissions\n"
            "4. Review state transitions for anomalies"
        )
    if skill_name == "vishnu-terraform-kong-pr":
        url_m = re.search(r"([a-zA-Z0-9_-]+\.razorpay\.com)", text)
        url = url_m.group(1) if url_m else "the domain"
        return (
            f"1. Run `vishnu-terraform-kong-pr` with URL: `{url}`\n"
            "2. vishnu: Add CNAME record in `prod/dns/records.tf` (engage-loyalty region)\n"
            "3. terraform-kong: Append URL to `rmp_service_cors_origins` in `prod/rewards-marketplace/config.tf`\n"
            "4. Both PRs created and linked — reply Approve to close ticket"
        )
    if skill_name == "invalid-rewards-debugger":
        return (
            "1. Run `invalid-rewards-debugger`\n"
            "2. Check reward eligibility rules and configuration\n"
            "3. Identify root cause of invalid reward\n"
            "4. Update ticket with findings"
        )
    return (
        "1. Review ticket details carefully\n"
        "2. Check similar past solved tickets for pattern\n"
        "3. Determine correct action and run appropriate skill\n"
        "4. Update ticket with resolution"
    )


def watch(interval: int = 5):
    """Main watch loop — runs forever, checking every `interval` seconds."""
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Auto-watcher started — watching %s", REQUESTS_DIR)

    try:
        detect_skill, find_relevant, format_relevant, load_config = _load_deps()
        config = load_config()
    except Exception as e:
        logger.error("Failed to load bot modules: %s", e)
        sys.exit(1)

    deps = {
        "detect_skill": detect_skill,
        "find_relevant": find_relevant,
        "format_relevant": format_relevant,
        "config": config,
    }

    processed = set()

    while True:
        try:
            for req_file in sorted(REQUESTS_DIR.glob("ISS-*.md")):
                if req_file in processed:
                    continue

                resp_file = RESPONSES_DIR / req_file.name
                if resp_file.exists():
                    processed.add(req_file)
                    continue

                logger.info("New request: %s — analysing...", req_file.name)
                try:
                    response_text = analyze(req_file, deps)
                    resp_file.write_text(response_text)
                    logger.info("Response written: %s", resp_file.name)
                except Exception as e:
                    logger.error("Failed to analyse %s: %s", req_file.name, e)

                processed.add(req_file)

            time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Auto-watcher stopped.")
            break
        except Exception as e:
            logger.error("Watch loop error: %s", e)
            time.sleep(interval)


if __name__ == "__main__":
    watch()
