"""
github_client.py — Thin wrapper around `gh` CLI for bot use.

Supports:
  list_prs(repo)               → list open PRs for a repo
  get_pr(repo, pr_number)      → full details of a PR
  comment_pr(repo, pr_number, body) → post a comment on a PR
  create_pr(repo, title, body, head, base) → open a new PR
"""
import json
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class PR:
    number: int
    title: str
    url: str
    state: str
    author: str
    body: str
    review_decision: str
    checks_status: str
    created_at: str
    merged_at: Optional[str]


def _gh(args: list[str], cwd: str = None) -> dict | list:
    """Run `gh` CLI and parse JSON output. Raises on failure."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def _gh_text(args: list[str], cwd: str = None) -> str:
    """Run `gh` CLI and return raw text output."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def list_prs(repo: str, state: str = "open", limit: int = 10) -> list[PR]:
    """
    List PRs for a repo.
    repo: 'owner/repo' e.g. 'razorpay/vishnu'
    state: 'open' | 'closed' | 'merged' | 'all'
    """
    data = _gh([
        "pr", "list",
        "--repo", repo,
        "--state", state,
        "--limit", str(limit),
        "--json", "number,title,url,state,author,createdAt,reviewDecision",
    ])
    return [
        PR(
            number=p["number"],
            title=p["title"],
            url=p["url"],
            state=p["state"],
            author=p["author"]["login"],
            body="",
            review_decision=p.get("reviewDecision") or "",
            checks_status="",
            created_at=p.get("createdAt", ""),
            merged_at=None,
        )
        for p in data
    ]


def get_pr(repo: str, pr_number: int | str) -> PR:
    """Fetch full details of a single PR."""
    data = _gh([
        "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "number,title,url,state,author,body,reviewDecision,statusCheckRollup,createdAt,mergedAt",
    ])

    # Summarise checks into a single status
    checks = data.get("statusCheckRollup") or []
    if not checks:
        checks_status = "no checks"
    elif all(c.get("status") == "COMPLETED" and c.get("conclusion") == "SUCCESS" for c in checks):
        checks_status = "all passing"
    elif any(c.get("conclusion") in ("FAILURE", "ERROR") for c in checks):
        checks_status = "failing"
    else:
        checks_status = "pending"

    return PR(
        number=data["number"],
        title=data["title"],
        url=data["url"],
        state=data["state"],
        author=data["author"]["login"],
        body=data.get("body", ""),
        review_decision=data.get("reviewDecision") or "",
        checks_status=checks_status,
        created_at=data.get("createdAt", ""),
        merged_at=data.get("mergedAt"),
    )


def comment_pr(repo: str, pr_number: int | str, body: str) -> str:
    """Post a comment on a PR. Returns the comment URL."""
    return _gh_text([
        "pr", "comment", str(pr_number),
        "--repo", repo,
        "--body", body,
    ])


def create_pr(repo: str, title: str, body: str, head: str, base: str = "master") -> str:
    """Create a PR and return its URL."""
    return _gh_text([
        "pr", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
        "--head", head,
        "--base", base,
    ])


def pr_from_url(url: str) -> tuple[str, int]:
    """
    Parse a GitHub PR URL into (repo, pr_number).
    e.g. https://github.com/razorpay/vishnu/pull/42 → ('razorpay/vishnu', 42)
    """
    import re
    m = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"Not a valid GitHub PR URL: {url}")
    return m.group(1), int(m.group(2))
