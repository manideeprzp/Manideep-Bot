"""
Inline analysis builder — generates ticket analysis immediately without file queue.
Output format matches what response_watcher._post_formatted expects:
  **Analysis:** ...
  **Approach:** ...
  **Skill to run:** ...
  **Confidence:** ...
  **Suggested tags:** ...
  **Suggested fields:** ...
"""
import re
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def build_inline_analysis(ticket_text: str, ticket_id: str, skill_name: str, confidence: str) -> str:
    """
    Build a fully formatted analysis string that _post_formatted() will render
    as rich Slack attachments with color bars.
    """
    skill_name = skill_name or "none"
    confidence = confidence or "low"
    ticket_id = ticket_id or "ticket"

    summary    = _build_summary(skill_name, ticket_text, ticket_id)
    approach   = _build_approach(skill_name, ticket_text)
    tags       = _build_tags(skill_name, ticket_text, ticket_id)
    fields_str = "cause_code: (set on close), pse_pod: (set on close), severity: Sev-4"

    # This exact format is what _build_attachments() in response_watcher.py parses
    parts = [
        f"**Analysis:** {summary}",
        "",
        f"**Approach:**\n{approach}",
        "",
        f"**Skill to run:** {skill_name}",
        f"**Confidence:** {confidence}",
        "",
        f"**Suggested tags:** {tags}",
        f"**Suggested fields:** {fields_str}",
    ]
    return "\n".join(parts)


def _build_summary(skill_name: str, text: str, ticket_id: str) -> str:
    if skill_name == "gc-redemption-report":
        m = (re.search(r"card[_\s-]?number[\s:=]+([A-Za-z0-9]+)", text, re.I)
             or re.search(r"\b(GC[A-Z0-9]{6,})\b", text, re.I)
             or re.search(r"\b([A-Z]{2}[0-9]{9,})\b", text, re.I))
        card = m.group(1) if m else "the card"
        return (f"Gift card issue for `{card}`. Running redemption report to check "
                f"balance and transaction history.")

    if skill_name == "gc-cancellation":
        m = re.search(r"card[_\s-]?number[\s:=]+([A-Za-z0-9]+)", text, re.I)
        card = m.group(1) if m else "the card"
        return (f"Gift card cancellation requested for `{card}`. Will verify card "
                f"status and cancel after confirming reason.")

    if skill_name == "order-trace-debugger":
        m = re.search(r"order[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)", text, re.I)
        order = m.group(1) if m else "the order"
        return (f"Order issue detected for `{order}`. Tracing through RMP, "
                f"Offers Engine, and Procurement systems.")

    if skill_name == "vishnu-terraform-kong-pr":
        m = (re.search(r"https?://([a-zA-Z0-9._-]+\.razorpay\.com)", text, re.I)
             or re.search(r"\b([a-zA-Z0-9_-]+\.razorpay\.com)\b", text, re.I))
        url = m.group(1) if m else "the domain"
        return (f"DNS and CORS origin setup required for `{url}`. Will create PRs "
                f"in vishnu (DNS record) and terraform-kong (CORS origin).")

    if skill_name == "invalid-rewards-debugger":
        return ("Invalid rewards issue detected. Will debug reward eligibility "
                "and configuration.")

    if skill_name == "rmp-gandalf":
        return "RMP Gandalf access or permission issue. Checking authorization configuration."

    return f"Ticket `{ticket_id}` received. Analysing based on past solved tickets and issue patterns."


def _build_approach(skill_name: str, text: str) -> str:
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
            "4. Update ticket with confirmation"
        )
    if skill_name == "order-trace-debugger":
        return (
            "1. Run `order-trace-debugger` with the order_id\n"
            "2. Check order state and customer-to-order mapping\n"
            "3. Verify visibility flags and permissions\n"
            "4. Review state transitions for anomalies"
        )
    if skill_name == "vishnu-terraform-kong-pr":
        m = (re.search(r"https?://([a-zA-Z0-9._-]+\.razorpay\.com)", text, re.I)
             or re.search(r"\b([a-zA-Z0-9_-]+\.razorpay\.com)\b", text, re.I))
        url = m.group(1) if m else "the domain"
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


def _build_tags(skill_name: str, text: str, ticket_id: str) -> str:
    """Build suggested tags string for the analysis."""
    tags = []
    if skill_name and skill_name != "none":
        tags.append(f"`skill:{skill_name}`")

    # Add skill-specific tags
    tag_map = {
        "gc-redemption-report":    ["`redemption_report`", "`gc_redemption`"],
        "gc-cancellation":         ["`gc_cancellation`", "`gc_cancel`"],
        "order-trace-debugger":    ["`order_trace`", "`order_debug`"],
        "vishnu-terraform-kong-pr":["`dns_pr`", "`kong_pr`", "`cors_origin`"],
        "invalid-rewards-debugger":["`invalid_rewards`"],
        "rmp-gandalf":             ["`rmp_gandalf`"],
    }
    tags.extend(tag_map.get(skill_name, []))
    return ", ".join(tags) if tags else "_none_"
