#!/usr/bin/env python3
"""
github_pr.py — GitHub PR skill for Manideep Bot.

Commands:
  read  <pr_url>                     → show PR details (title, state, checks, review)
  list  <owner/repo> [open|closed]   → list PRs for a repo
  comment <pr_url> <message>         → post a comment on a PR
  create <owner/repo> <head> <title> → create a PR (prompts for body)

Usage examples:
  python3 scripts/github_pr.py read https://github.com/razorpay/vishnu/pull/42
  python3 scripts/github_pr.py list razorpay/vishnu
  python3 scripts/github_pr.py list razorpay/vishnu closed
  python3 scripts/github_pr.py comment https://github.com/razorpay/vishnu/pull/42 "LGTM, resolves ISS-1234567"
  python3 scripts/github_pr.py create razorpay/vishnu feature/add-foo "[ISS-1234567] Add foo" "Fixes X"
"""
import sys
from pathlib import Path

# Allow importing github_client from same directory
sys.path.insert(0, str(Path(__file__).parent))
import github_client as gh


def cmd_read(pr_url: str):
    repo, number = gh.pr_from_url(pr_url)
    pr = gh.get_pr(repo, number)

    state_emoji = {"OPEN": "🟢", "CLOSED": "🔴", "MERGED": "🟣"}.get(pr.state.upper(), "⚪")
    review_emoji = {
        "APPROVED": "✅",
        "CHANGES_REQUESTED": "🔄",
        "REVIEW_REQUIRED": "👀",
    }.get((pr.review_decision or "").upper(), "")

    print(f"{state_emoji} PR #{pr.number}: {pr.title}")
    print(f"   Repo:     {repo}")
    print(f"   Author:   {pr.author}")
    print(f"   State:    {pr.state}")
    print(f"   Review:   {review_emoji} {pr.review_decision or 'none'}")
    print(f"   Checks:   {pr.checks_status}")
    print(f"   Created:  {pr.created_at[:10] if pr.created_at else 'unknown'}")
    if pr.merged_at:
        print(f"   Merged:   {pr.merged_at[:10]}")
    print(f"   URL:      {pr.url}")
    if pr.body:
        body_preview = pr.body.strip()[:300].replace("\n", " ")
        print(f"   Body:     {body_preview}{'...' if len(pr.body) > 300 else ''}")


def cmd_list(repo: str, state: str = "open"):
    prs = gh.list_prs(repo, state=state, limit=15)
    if not prs:
        print(f"No {state} PRs found for {repo}.")
        return

    state_emoji = {"OPEN": "🟢", "CLOSED": "🔴", "MERGED": "🟣"}
    print(f"{'='*60}")
    print(f"  {state.upper()} PRs for {repo} ({len(prs)} found)")
    print(f"{'='*60}")
    for pr in prs:
        emoji = state_emoji.get(pr.state.upper(), "⚪")
        review = f" [{pr.review_decision}]" if pr.review_decision else ""
        print(f"  {emoji} #{pr.number}  {pr.title}{review}")
        print(f"       {pr.url}  by @{pr.author}  ({pr.created_at[:10] if pr.created_at else ''})")
    print(f"{'='*60}")


def cmd_comment(pr_url: str, message: str):
    repo, number = gh.pr_from_url(pr_url)
    result = gh.comment_pr(repo, number, message)
    print(f"✅ Comment posted on PR #{number} ({repo})")
    if result:
        print(f"   {result}")


def cmd_create(repo: str, head: str, title: str, body: str = ""):
    url = gh.create_pr(repo, title=title, body=body, head=head)
    print(f"✅ PR created: {url}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    try:
        if cmd == "read":
            if len(sys.argv) < 3:
                print("Usage: github_pr.py read <pr_url>")
                sys.exit(1)
            cmd_read(sys.argv[2])

        elif cmd == "list":
            if len(sys.argv) < 3:
                print("Usage: github_pr.py list <owner/repo> [open|closed|merged|all]")
                sys.exit(1)
            state = sys.argv[3] if len(sys.argv) > 3 else "open"
            cmd_list(sys.argv[2], state)

        elif cmd == "comment":
            if len(sys.argv) < 4:
                print("Usage: github_pr.py comment <pr_url> <message>")
                sys.exit(1)
            cmd_comment(sys.argv[2], " ".join(sys.argv[3:]))

        elif cmd == "create":
            if len(sys.argv) < 5:
                print("Usage: github_pr.py create <owner/repo> <head-branch> <title> [body]")
                sys.exit(1)
            body = sys.argv[5] if len(sys.argv) > 5 else ""
            cmd_create(sys.argv[2], sys.argv[3], sys.argv[4], body)

        else:
            print(f"Unknown command: {cmd}")
            print("Commands: read, list, comment, create")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
