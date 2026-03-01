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

    # Unknown skill
    return f"No runnable skill for '{skill_name}'. Available skills: order-trace-debugger, gc-redemption-report, gc-cancellation.", False
