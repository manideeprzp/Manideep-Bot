"""
Run a skill script by name. Maps skill name -> script path + how to get args from ticket text.
Output is captured and returned for Slack.

After a skill returns raw output (usually JSON), we pass it through the local
Claude Code CLI (`claude -p`) for human-readable analysis — same quality as
running the skill in Claude Code terminal.
"""
import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_BOT_ROOT = Path(__file__).resolve().parent.parent.parent

# agent-skills repo cloned inside the bot workspace (works in Cowork + terminal)
_AGENT_SKILLS_ROOT = _BOT_ROOT / "agent-skills"

# Fallback: Cursor skills on Mac (terminal only)
_CURSOR_SKILLS_ROOT = Path.home() / ".cursor" / "skills"


def _find_skill_script(*relative_paths: str) -> Path:
    """
    Look for a skill script first in agent-skills repo, then in ~/.cursor/skills.
    Falls back to cursor path so the caller's .exists() check still works as before.
    """
    # agent-skills uses a nested structure: teams/<team>/<pod>/<skill>/scripts/<file>
    # Try the full path as-is under agent-skills root
    agent_path = _AGENT_SKILLS_ROOT.joinpath(*relative_paths)
    if agent_path.exists():
        return agent_path
    # Fallback: ~/.cursor/skills/<skill>/scripts/<file> (Mac terminal)
    cursor_path = _CURSOR_SKILLS_ROOT.joinpath(*relative_paths)
    return cursor_path  # caller checks .exists()


# Local bot scripts (always in the repo)
_ORDER_TRACE_SCRIPT = _BOT_ROOT / "scripts" / "trace_order.py"
_VISHNU_KONG_SCRIPT = _BOT_ROOT / "scripts" / "vishnu_kong_pr.py"
_GITHUB_PR_SCRIPT = _BOT_ROOT / "scripts" / "github_pr.py"

# order-trace-debugger: in agent-skills repo ✅ (PR #313 merged)
_ORDER_TRACE_CURSOR = _find_skill_script(
    "teams", "engage", "rewards-market-place",
    "order-trace-debugger", "scripts", "trace_order.py"
)

# gc-redemption-report: not yet in agent-skills → falls back to ~/.cursor/skills on Mac
# TODO: once merged to agent-skills, update path to:
#   "teams", "engage", "rewards-market-place", "gc-redemption-report", "scripts", "redemption_report.py"
_GC_REDEMPTION_SCRIPT = _find_skill_script(
    "gc-redemption-report", "scripts", "redemption_report.py"
)

# gc-cancellation: not yet in agent-skills → falls back to ~/.cursor/skills on Mac
# TODO: once merged to agent-skills, update path to:
#   "teams", "engage", "rewards-market-place", "gc-cancellation", "scripts", "cancel_gc.py"
_GC_CANCELLATION_SCRIPT = _find_skill_script(
    "gc-cancellation", "scripts", "cancel_gc.py"
)


def _format_redemption_report(raw_output: str, card_numbers: list) -> str:
    """Format gc-redemption-report output into a clean Slack message with emojis."""
    # Extract all Google Sheets URLs from the raw output
    sheet_urls = re.findall(r"https://docs\.google\.com/spreadsheets/[^\s\)]+", raw_output)

    lines = [":gift: *GC Redemption Report*\n"]

    if card_numbers and sheet_urls:
        lines.append(f":page_facing_up: Here are the reports for *{len(card_numbers)}* card(s):\n")
        for i, card in enumerate(card_numbers):
            url = sheet_urls[i] if i < len(sheet_urls) else (sheet_urls[-1] if sheet_urls else "")
            lines.append(f":credit_card: *Card {i+1}:* `{card}`")
            if url:
                lines.append(f"   :bar_chart: <{url}|View Report>\n")
            else:
                lines.append("")
    elif card_numbers:
        # No URLs found — just show card numbers with raw output
        lines.append(f":page_facing_up: Report generated for *{len(card_numbers)}* card(s):\n")
        for i, card in enumerate(card_numbers):
            lines.append(f":credit_card: *Card {i+1}:* `{card}`")
        lines.append(f"\n{raw_output[:1500]}")
    else:
        lines.append(raw_output[:2000])

    lines.append("\n:white_check_mark: Please review the spreadsheet and reply *Approve* to post on the ticket and close it.")

    return "\n".join(lines)


def _find_order_id(text: str) -> str:
    """Extract order_id from ticket body/title (e.g. order_123 or order-id: xyz)."""
    if not text:
        return ""
    # Common patterns (checked in priority order)
    for pat in [
        r"order[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)",
        r"order_id[\s:=]+([A-Za-z0-9_-]+)",
        r"\b(order_[A-Za-z0-9_-]+)\b",
        r"\b([0-9a-f-]{36})\b",  # UUID
        r"\b([A-Za-z0-9]{14})\b",  # RMP-style IDs e.g. SWFPzY3olAMzPl
    ]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _find_all_order_ids(text: str) -> list:
    """Extract all RMP-style order IDs from ticket body (e.g. SWFPzY3olAMzPl)."""
    if not text:
        return []
    # Named patterns first
    ids = re.findall(r"order[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)", text, re.I)
    if ids:
        return ids
    ids = re.findall(r"\b(order_[A-Za-z0-9_-]+)\b", text, re.I)
    if ids:
        return ids
    # RMP-style 14-char alphanumeric IDs (one per line)
    ids = re.findall(r"(?m)^\s*([A-Za-z0-9]{14})\s*$", text)
    return ids


def _find_card_number(text: str) -> str:
    """
    Extract GC card number from ticket body.
    Ticket body from DevRev will have a clear line like 'Card number: 7717386747'.
    That's the source of truth — read it directly, no guessing.
    """
    if not text:
        return ""
    # Primary: explicit "Card number: XXXX" line (how tickets are written)
    m = re.search(r"card[_\s-]?number[\s:=]+([A-Za-z0-9]+)", text, re.I)
    if m:
        return m.group(1).strip()
    # Fallback: GC-prefixed number or 2-letter + 9+ digit code
    m = re.search(r"\b(GC[A-Z0-9]{6,})\b", text, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b([A-Z]{2}[0-9]{9,})\b", text, re.I)
    if m:
        return m.group(1).strip()
    # Last resort: bare numeric card number on its own line (10–19 digits)
    # Handles tickets where card numbers are listed without a "Card number:" label
    m = re.search(r"(?:^|\s)([0-9]{10,19})(?:\s|$)", text)
    if m:
        return m.group(1).strip()
    return ""


def _find_all_card_numbers(text: str) -> list:
    """
    Extract ALL GC card numbers from ticket body (handles multi-card tickets).
    Returns a deduplicated list preserving order.
    """
    if not text:
        return []
    seen = set()
    results = []

    def _add(val):
        v = val.strip()
        if v and v not in seen:
            seen.add(v)
            results.append(v)

    # Explicit "card number: XXXX" lines
    for m in re.finditer(r"card[_\s-]?number[\s:=]+([A-Za-z0-9]+)", text, re.I):
        _add(m.group(1))
    # GC-prefixed codes
    for m in re.finditer(r"\b(GC[A-Z0-9]{6,})\b", text, re.I):
        _add(m.group(1))
    # 2-letter + 9+ digit codes
    for m in re.finditer(r"\b([A-Z]{2}[0-9]{9,})\b", text, re.I):
        _add(m.group(1))
    # Bare 10–19 digit numeric codes (one per line)
    for m in re.finditer(r"(?:^|\s)([0-9]{10,19})(?:\s|$)", text):
        _add(m.group(1))

    return results


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


def _find_merchant_id(text: str) -> str:
    """Extract merchant_id from ticket body."""
    if not text:
        return ""
    for pat in [
        r"merchant[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)",
        r"\b([A-Za-z0-9]{14,20})\b",  # Razorpay merchant IDs are typically 14-20 chars
    ]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _find_bearer_token(text: str) -> str:
    """Extract bearer token from ticket body."""
    if not text:
        return ""
    for pat in [
        r"bearer[_\s-]?token[\s:=]+([A-Za-z0-9._\-]+)",
        r"token[\s:=]+([A-Za-z0-9._\-]{20,})",
        r"auth[\s:=]+([A-Za-z0-9._\-]{20,})",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _find_github_pr_url(text: str) -> str:
    """Extract a GitHub PR URL from ticket text."""
    if not text:
        return ""
    m = re.search(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/\d+", text)
    if m:
        return m.group(0)
    return ""


def _find_github_repo(text: str) -> str:
    """Extract an owner/repo slug from ticket text (e.g. razorpay/vishnu)."""
    if not text:
        return ""
    # Explicit repo: patterns
    m = re.search(r"repo[\s:]+([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)", text, re.I)
    if m:
        return m.group(1)
    # From a GitHub URL
    m = re.search(r"github\.com/([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)", text)
    if m:
        return m.group(1).rstrip("/")
    return ""


# ── LLM analysis via local Claude Code CLI ─────────────────────────────────

_ANALYSIS_PROMPTS = {
    "order-trace-debugger": (
        "You are an RMP (Rewards Marketplace) support engineer at Razorpay. "
        "Analyze this order trace JSON and provide a concise Slack-friendly summary. Include:\n"
        "1. **Order Status** — SUCCESS/FAILED/PROCESSING with emoji (✅/❌/⏳)\n"
        "2. **Timeline** — key state transitions with human-readable timestamps (IST)\n"
        "3. **Order Details** — amount, product type, reward ID, merchant/RZP commission\n"
        "4. **Diagnosis** — if failed, identify WHERE it broke (RMP/Procurement/Provider) and WHY\n"
        "5. **Coralogix Logs** — summarize any error logs if present\n"
        "6. **Action Required** — what the support engineer should do next\n\n"
        "Keep it under 1500 chars. Use Slack markdown (*bold*, `code`). No JSON in output.\n\n"
        "Ticket context: {ticket_text}\n\n"
        "Raw trace output:\n{raw_output}"
    ),
    "gc-redemption-report": (
        "You are a GC (Gift Card) support engineer at Razorpay. "
        "Analyze this redemption report and provide a Slack-friendly summary:\n"
        "1. **Card Status** — active/cancelled/expired\n"
        "2. **Balance** — current balance vs loaded amount\n"
        "3. **Transactions** — list redemptions (if any) with amounts and dates\n"
        "4. **Diagnosis** — if only recharges and no redemptions, flag as CANCELLATION candidate\n"
        "5. **Action Required** — next steps\n\n"
        "Keep it under 1500 chars. Use Slack markdown.\n\n"
        "Ticket context: {ticket_text}\n\n"
        "Raw output:\n{raw_output}"
    ),
    "gc-cancellation": (
        "You are a GC support engineer at Razorpay. "
        "Analyze this GC cancellation result:\n"
        "1. **Result** — success/failure with emoji\n"
        "2. **Card Details** — card ID, merchant, balance at cancellation\n"
        "3. **Action Required** — confirm with requester or escalate\n\n"
        "Keep it under 800 chars. Use Slack markdown.\n\n"
        "Raw output:\n{raw_output}"
    ),
}

_DEFAULT_ANALYSIS_PROMPT = (
    "Analyze this skill output and provide a concise Slack-friendly summary. "
    "Use Slack markdown (*bold*, `code`). Keep it under 1500 chars.\n\n"
    "Ticket context: {ticket_text}\n\n"
    "Raw output:\n{raw_output}"
)


def _analyze_with_claude_code(raw_output: str, skill_name: str, ticket_text: str = "") -> str:
    """
    Pass raw skill output through local Claude Code CLI for human-readable analysis.
    Falls back to raw output if claude CLI is not available or fails.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        logger.info("claude CLI not found — returning raw output")
        return raw_output

    prompt_template = _ANALYSIS_PROMPTS.get(skill_name, _DEFAULT_ANALYSIS_PROMPT)
    prompt = prompt_template.format(
        raw_output=raw_output[:6000],  # limit to avoid token overflow
        ticket_text=(ticket_text or "")[:1000],
    )

    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            analysis = result.stdout.strip()
            # Append raw JSON as collapsed reference
            return analysis
        else:
            logger.warning("claude CLI returned %d: %s", result.returncode, (result.stderr or "")[:200])
            return raw_output
    except subprocess.TimeoutExpired:
        logger.warning("claude CLI timed out (60s) — returning raw output")
        return raw_output
    except Exception as e:
        logger.warning("claude CLI error: %s — returning raw output", e)
        return raw_output


def run_skill(skill_name: str, ticket_text: str, ticket_id: str = "") -> tuple[str, bool]:
    """
    Run the skill script. Returns (output_or_error_message, success).
    ticket_id should be passed explicitly (e.g. ISS-1720641) — don't rely on parsing ticket body.
    """
    skill_name = (skill_name or "").strip().lower()

    # Order trace debugger
    if skill_name == "order-trace-debugger":
        order_id = _find_order_id(ticket_text)
        if not order_id:
            return (
                "Order ID not found in the ticket body.\n"
                "Please reply with:\n`order_id: <your_order_id>`"
            ), False
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
            raw = (out.stdout or "Done.").strip()
            analyzed = _analyze_with_claude_code(raw, "order-trace-debugger", ticket_text)
            return analyzed[:3000], True
        except subprocess.TimeoutExpired:
            return "Script timed out (120s).", False
        except Exception as e:
            return str(e)[:500], False

    # GC Redemption Report
    elif skill_name in ("gc-redemption-report", "redemption-report", "redemption_report"):
        # Collect ALL card numbers from the ticket (handles multi-card tickets)
        card_numbers = _find_all_card_numbers(ticket_text)
        if not card_numbers:
            return (
                "Card number not found in the ticket body.\n"
                "Please reply with:\n`card number: <your_card_number>`"
            ), False
        script = _GC_REDEMPTION_SCRIPT
        if not script.exists():
            return f"Redemption report skill not found at {script}. Make sure gc-redemption-report Cursor skill is installed.", False
        try:
            import sys
            py = sys.executable or "python3"
            out = subprocess.run(
                [py, str(script), "--card-numbers"] + card_numbers,
                capture_output=True,
                text=True,
                timeout=180,  # Redash queries can be slow
                cwd=str(script.parent),
            )
            if out.returncode != 0:
                return (out.stderr or out.stdout or "Script failed").strip()[:3000], False
            raw = (out.stdout or "Done. Check the sheet link above.").strip()
            # Format a clean Slack message with card numbers and sheet links
            # instead of passing through Claude CLI (which can't read sheet URLs)
            formatted = _format_redemption_report(raw, card_numbers)
            return formatted[:3000], True
        except subprocess.TimeoutExpired:
            return "Script timed out (180s). Redash query may be slow.", False
        except Exception as e:
            return str(e)[:500], False

    # GC Cancellation
    elif skill_name in ("gc-cancellation", "cancel-gc", "gc_cancellation"):
        card_number = _find_card_number(ticket_text)
        if not card_number:
            return (
                "Card number not found in the ticket body.\n"
                "Please reply with:\n`card number: <gc_id>`"
            ), False

        reason = _find_cancellation_reason(ticket_text)
        if not reason:
            return (
                "Cancellation reason not found in the ticket.\n"
                "Please reply with:\n`reason: <cancellation reason>`"
            ), False

        bearer_token = _find_bearer_token(ticket_text)
        if not bearer_token:
            return (
                "Bearer token not found in the ticket.\n"
                "Please reply with:\n`bearer token: <your_token>`"
            ), False

        script = _GC_CANCELLATION_SCRIPT
        if not script.exists():
            return f"GC cancellation skill not found at {script}. Make sure gc-cancellation Cursor skill is installed.", False

        import sys
        py = sys.executable or "python3"

        # Step 1: fetch — queries Redash to get merchant_id from card number
        try:
            fetch_out = subprocess.run(
                [py, str(script), "fetch", "--card-numbers", card_number],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(script.parent),
            )
            if fetch_out.returncode != 0:
                return (
                    f"fetch step failed:\n{(fetch_out.stderr or fetch_out.stdout or 'Unknown error').strip()[:1000]}"
                ), False
            fetch_result = fetch_out.stdout.strip()
        except subprocess.TimeoutExpired:
            return "fetch step timed out (120s). Redash may be slow.", False
        except Exception as e:
            return f"fetch step error: {str(e)[:500]}", False

        # Parse merchant_id from fetch output
        # fetch prints lines like: "merchant_id: XXXXXXXXXXXXXXXX" or JSON
        merchant_id = ""
        for pat in [
            r"merchant[_\s-]?id[\s:=]+([A-Za-z0-9_-]+)",
            r'"merchant_id"\s*:\s*"([^"]+)"',
            r"'merchant_id'\s*:\s*'([^']+)'",
        ]:
            m = re.search(pat, fetch_result, re.I)
            if m:
                merchant_id = m.group(1).strip()
                break

        if not merchant_id:
            return (
                f"Could not parse merchant_id from fetch output:\n{fetch_result[:500]}\n\n"
                "Please provide it manually:\n`merchant id: <merchant_id>`"
            ), False

        # Step 2: cancel — runs the actual cancellation
        try:
            cancel_out = subprocess.run(
                [
                    py, str(script), "cancel",
                    "--gc-id", card_number,
                    "--merchant-id", merchant_id,
                    "--bearer-token", bearer_token,
                    "--reason", reason,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(script.parent),
            )
            if cancel_out.returncode != 0:
                return (cancel_out.stderr or cancel_out.stdout or "cancel step failed").strip()[:3000], False
            raw = (cancel_out.stdout or "GC cancelled successfully.").strip()
            analyzed = _analyze_with_claude_code(raw, "gc-cancellation", ticket_text)
            return analyzed[:3000], True
        except subprocess.TimeoutExpired:
            return "cancel step timed out (120s).", False
        except Exception as e:
            return str(e)[:500], False

    # Vishnu + Terraform-Kong dual PR
    elif skill_name in ("vishnu-terraform-kong-pr", "vishnu-kong-pr", "kong-pr", "dns-pr"):
        url = _find_url(ticket_text)
        if not url:
            return (
                "Domain URL not found in the ticket body.\n"
                "Please reply with:\n`url: <subdomain>.razorpay.com`"
            ), False

        # Use explicitly passed ticket_id — never fall back to parsing the body
        # (ticket body often has placeholder text, not the real ID)
        tid = (ticket_id or "").strip().upper() or "ISS-UNKNOWN"

        if not _VISHNU_KONG_SCRIPT.exists():
            return f"Script not found: {_VISHNU_KONG_SCRIPT}", False

        try:
            import sys
            py = sys.executable or "python3"
            out = subprocess.run(
                [py, str(_VISHNU_KONG_SCRIPT), url, tid],
                capture_output=True,
                text=True,
                timeout=300,
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

    # GitHub PR — read or list PRs
    elif skill_name in ("github-pr", "github-pr-reader", "gh-pr", "github"):
        if not _GITHUB_PR_SCRIPT.exists():
            return f"GitHub PR script not found at {_GITHUB_PR_SCRIPT}.", False

        import sys
        py = sys.executable or "python3"

        # Determine sub-command from ticket text
        pr_url = _find_github_pr_url(ticket_text)
        repo = _find_github_repo(ticket_text)

        if pr_url:
            # PR URL found → read its details
            args = [py, str(_GITHUB_PR_SCRIPT), "read", pr_url]
        elif repo:
            # Only a repo slug → list open PRs
            args = [py, str(_GITHUB_PR_SCRIPT), "list", repo]
        else:
            return (
                "No GitHub PR URL or repo found in the ticket.\n"
                "Please reply with a PR URL like:\n"
                "`https://github.com/razorpay/vishnu/pull/42`\n"
                "or a repo like:\n`repo: razorpay/vishnu`"
            ), False

        try:
            out = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if out.returncode != 0:
                return (out.stderr or out.stdout or "Script failed").strip()[:3000], False
            return (out.stdout or "Done.").strip()[:3000], True
        except subprocess.TimeoutExpired:
            return "GitHub PR script timed out (60s).", False
        except Exception as e:
            return str(e)[:500], False

    # Unknown skill
    return f"No runnable skill for '{skill_name}'. Available skills: order-trace-debugger, gc-redemption-report, gc-cancellation, vishnu-terraform-kong-pr, github-pr.", False
