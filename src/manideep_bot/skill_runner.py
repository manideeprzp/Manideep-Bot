"""
Run a skill script by name. Maps skill name -> script path + how to get args from ticket text.
Output is captured and returned for Slack.
"""
import re
import subprocess
from pathlib import Path

_BOT_ROOT = Path(__file__).resolve().parent.parent.parent
_CURSOR_SKILLS_ROOT = Path.home() / ".cursor" / "skills"

# Scripts from Cursor skill or local scripts
_ORDER_TRACE_SCRIPT = _BOT_ROOT / "scripts" / "trace_order.py"
_GC_REDEMPTION_SCRIPT = _CURSOR_SKILLS_ROOT / "gc-redemption-report" / "scripts" / "redemption_report.py"
_GC_CANCELLATION_SCRIPT = _CURSOR_SKILLS_ROOT / "gc-cancellation" / "scripts" / "cancel_gc.py"
_VISHNU_KONG_SCRIPT = _BOT_ROOT / "scripts" / "vishnu_kong_pr.py"

# Fallback: order-trace-debugger in Cursor skills
_ORDER_TRACE_CURSOR = _CURSOR_SKILLS_ROOT / "order-trace-debugger" / "scripts" / "trace_order.py"


def _find_order_id(text: str) -> str:
    """Extract order_id from ticket body/title (e.g. order_123 or order-id: xyz)."""
    if not text:
        return ""
    # Common patterns
    for pat in [
        r"order[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)",
        r"order_id[\s:=]+([A-Za-z0-9_-]+)",
        r"\b(order_[A-Za-z0-9_-]+)\b",
        r"\b([0-9a-f-]{36})\b",  # UUID
    ]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _find_card_number(text: str) -> str:
    """Extract GC card number from ticket body/title."""
    if not text:
        return ""
    # Common patterns for gift card numbers
    for pat in [
        r"card[_\s-]?number[\s:=]+([A-Za-z0-9_-]+)",
        r"card[\s:]+([A-Z0-9]{9,20})",  # e.g., "card: GC123456789"
        r"GC[_-]?([A-Z0-9]{6,15})",  # e.g., "GC123456789" or "GC_123456"
        r"\b([A-Z]{2}[0-9]{9,15})\b",  # e.g., "GC123456789"
    ]:
        m = re.search(pat, text, re.I)
        if m:
            card = m.group(1).strip()
            # If pattern captured just the number part, prepend GC if needed
            if pat.startswith(r"GC"):
                return f"GC{card}" if not card.startswith("GC") else card
            return card
    return ""


def _find_url(text: str) -> str:
    """Extract a domain/URL from ticket text (e.g. simplysave.razorpay.com)."""
    if not text:
        return ""
    # Full https URL
    m = re.search(r"https?://([a-zA-Z0-9._-]+\.razorpay\.com)\b", text, re.I)
    if m:
        return m.group(1)
    # Bare razorpay.com subdomain
    m = re.search(r"\b([a-zA-Z0-9_-]+\.razorpay\.com)\b", text, re.I)
    if m:
        return m.group(1)
    return ""


def _find_cancellation_reason(text: str) -> str:
    """Extract cancellation reason from ticket body."""
    if not text:
        return ""
    # Look for reason patterns
    for pat in [
        r"reason[\s:]+(.+?)(?:\n|$)",
        r"cancel(?:lation)?[\s]+reason[\s:]+(.+?)(?:\n|$)",
        r"(?:customer wants?|requested)[\s:]+(.+?)(?:\n|$)",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()[:200]  # Limit length
    return ""


def run_skill(skill_name: str, ticket_text: str) -> tuple[str, bool]:
    """
    Run the skill script. Returns (output_or_error_message, success).
    """
    skill_name = (skill_name or "").strip().lower()

    # Order trace debugger
    if skill_name == "order-trace-debugger":
        order_id = _find_order_id(ticket_text)
        if not order_id:
            return "Could not find order_id in the ticket. Please reply with the order_id (e.g. paste it).", False
        script = _ORDER_TRACE_SCRIPT if _ORDER_TRACE_SCRIPT.exists() else _ORDER_TRACE_CURSOR
        if not script.exists():
            return f"Skill script not found: {script}. Install order-trace-debugger scripts or add trace_order.py to manideep-bot/scripts.", False
        try:
            import sys
            py = sys.executable or "python3"
            out = subprocess.run(
                [py, str(script), order_id],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(script.parent),
            )
            if out.returncode != 0:
                return (out.stderr or out.stdout or "Script failed").strip()[:3000], False
            return (out.stdout or "Done.").strip()[:3000], True
        except subprocess.TimeoutExpired:
            return "Script timed out (120s).", False
        except Exception as e:
            return str(e)[:500], False

    # GC Redemption Report
    elif skill_name in ("gc-redemption-report", "redemption-report", "redemption_report"):
        card_number = _find_card_number(ticket_text)
        if not card_number:
            return "Could not find card number in the ticket. Please reply with the card number (e.g., GC123456789).", False
        script = _GC_REDEMPTION_SCRIPT
        if not script.exists():
            return f"Redemption report skill not found at {script}. Make sure gc-redemption-report Cursor skill is installed.", False
        try:
            import sys
            py = sys.executable or "python3"
            out = subprocess.run(
                [py, str(script), card_number],
                capture_output=True,
                text=True,
                timeout=180,  # Redash queries can be slow
                cwd=str(script.parent),
            )
            if out.returncode != 0:
                return (out.stderr or out.stdout or "Script failed").strip()[:3000], False
            return (out.stdout or "Done. Check the sheet link above.").strip()[:3000], True
        except subprocess.TimeoutExpired:
            return "Script timed out (180s). Redash query may be slow.", False
        except Exception as e:
            return str(e)[:500], False

    # GC Cancellation
    elif skill_name in ("gc-cancellation", "cancel-gc", "gc_cancellation"):
        card_number = _find_card_number(ticket_text)
        if not card_number:
            return "Could not find card number in the ticket. Please reply with the card number (e.g., GC123456789).", False

        reason = _find_cancellation_reason(ticket_text)
        if not reason:
            return "Could not find cancellation reason in the ticket. Please provide the reason (e.g., 'customer wants refund').", False

        script = _GC_CANCELLATION_SCRIPT
        if not script.exists():
            return f"GC cancellation skill not found at {script}. Make sure gc-cancellation Cursor skill is installed.", False
        try:
            import sys
            py = sys.executable or "python3"
            # Pass both card number and reason as arguments
            out = subprocess.run(
                [py, str(script), card_number, reason],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(script.parent),
            )
            if out.returncode != 0:
                return (out.stderr or out.stdout or "Script failed").strip()[:3000], False
            return (out.stdout or "GC cancelled successfully.").strip()[:3000], True
        except subprocess.TimeoutExpired:
            return "Script timed out (120s).", False
        except Exception as e:
            return str(e)[:500], False

    # Vishnu + Terraform-Kong dual PR
    elif skill_name in ("vishnu-terraform-kong-pr", "vishnu-kong-pr", "kong-pr", "dns-pr"):
        url = _find_url(ticket_text)
        if not url:
            return (
                "Could not find a `*.razorpay.com` URL in the ticket.\n"
                "Please reply with the domain, e.g.:\n`url: simplysave.razorpay.com`"
            ), False

        # Extract ticket ID from ticket text (ISS-XXXXXX)
        ticket_id_match = re.search(r"\b(ISS-\d+)\b", ticket_text, re.I)
        ticket_id = ticket_id_match.group(1).upper() if ticket_id_match else "ISS-000000"

        if not _VISHNU_KONG_SCRIPT.exists():
            return f"Script not found: {_VISHNU_KONG_SCRIPT}", False

        try:
            import sys
            py = sys.executable or "python3"
            out = subprocess.run(
                [py, str(_VISHNU_KONG_SCRIPT), url, ticket_id],
                capture_output=True,
                text=True,
                timeout=300,  # git ops can be slow
                cwd=str(_BOT_ROOT),
            )
            output = (out.stdout or "").strip()
            if out.returncode != 0:
                err = (out.stderr or out.stdout or "Script failed").strip()
                return err[:3000], False
            return output[:3000], True
        except subprocess.TimeoutExpired:
            return "PR script timed out (300s). Check if repos are accessible.", False
        except Exception as e:
            return str(e)[:500], False

    # Unknown skill
    return f"No runnable skill for '{skill_name}'. Available skills: order-trace-debugger, gc-redemption-report, gc-cancellation, vishnu-terraform-kong-pr.", False
