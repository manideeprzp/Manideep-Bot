"""Load PERSONA + SAFETY and inject past solved tickets + skills (works like me)."""
import json
from pathlib import Path

from .config import Config


def _load(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    return ""


def _solved_summary(data_dir: Path) -> str:
    p = data_dir / "my_solved_tickets.json"
    if not p.exists():
        return "No past solved tickets loaded yet. Run scripts/fetch_my_solved.py first."
    try:
        with open(p) as f:
            data = json.load(f)
        tickets = data.get("tickets") or []
        if not tickets:
            return "You have no solved tickets in the cache."
        titles = [t.get("title") or t.get("display_id") or "" for t in tickets[:20]]
        return f"You have {len(tickets)} solved tickets. Recent themes/titles: " + "; ".join(titles[:10]) + (" ..." if len(tickets) > 10 else "")
    except Exception:
        return "Past solved tickets could not be loaded."


def _skills_list(solved_dir: Path) -> str:
    if not solved_dir.exists():
        return "No generated skills yet. Run scripts/generate_skills_from_solved.py."
    md_files = list(solved_dir.glob("*.md"))
    known = ["order-trace-debugger", "gc-cancellation", "gc-redemption-report", "devrev-ticket-assistant"]
    names = list(known) + [f.name.replace(".md", "") for f in md_files[:15]]
    return "When relevant use these skills: " + ", ".join(names) + "."


def get_system_prompt(config: Config) -> str:
    paths = config.paths
    persona = _load(paths.template_dir / "PERSONA.md")
    safety = _load(paths.template_dir / "SAFETY.md")

    solved_summary = _solved_summary(paths.data_dir)
    skills_list = _skills_list(paths.solved_dir)

    persona = persona.replace(
        "*(The bot will append a short summary of `data/my_solved_tickets.json` here.)*",
        solved_summary,
    ).replace(
        "*(The bot will append the list of `solved/*.md` and known skills like order-trace-debugger, gc-cancellation.)*",
        skills_list,
    )

    parts = [persona]
    if safety:
        parts.append(safety)
    return "\n\n---\n\n".join(parts)
