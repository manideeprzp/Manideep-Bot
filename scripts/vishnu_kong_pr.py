#!/usr/bin/env python3
"""
vishnu_kong_pr.py — Create coordinated DNS + Kong CORS PRs from one command.

Usage:
    python3 scripts/vishnu_kong_pr.py <url> <ticket_id>

Example:
    python3 scripts/vishnu_kong_pr.py simplysave.razorpay.com ISS-1659503

What it does:
  1. Pulls latest master in both repos
  2. Creates a feature branch in each repo
  3. vishnu:          adds DNS CNAME block to prod/dns/records.tf (engage-loyalty region)
  4. terraform-kong:  appends URL to rmp_service_cors_origins in prod/rewards-marketplace/config.tf
  5. Commits, pushes, opens GitHub PRs via `gh pr create`
  6. Prints both PR URLs
"""
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Repo paths (hardcoded; both cloned on your machine) ──────────────────────
VISHNU_PATH = Path.home() / "Desktop" / "vishnu"
KONG_PATH = Path.home() / "Desktop" / "terraform-kong"

# ── File paths inside repos ───────────────────────────────────────────────────
RECORDS_TF = "prod/dns/records.tf"
KONG_CONFIG = "prod/rewards-marketplace/config.tf"

# ── Cloudfront target (fixed for engage-loyalty) ─────────────────────────────
CLOUDFRONT = "d21zo78t01anj.cloudfront.net"


def run(cmd: str, cwd: Path, check=True) -> subprocess.CompletedProcess:
    """Run a shell command, stream output, raise on failure."""
    result = subprocess.run(
        cmd, shell=True, cwd=str(cwd),
        capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed in {cwd}:\n  $ {cmd}\n"
            f"  stdout: {result.stdout.strip()}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return result


def normalize_url(url: str) -> str:
    """Ensure URL has https:// prefix."""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def bare_domain(url: str) -> str:
    """Strip https:// and trailing slash."""
    return re.sub(r"^https?://", "", url).rstrip("/")


def slug_from_domain(domain: str) -> str:
    """
    Derive a snake_case slug from a domain for use in Terraform resource names.
    e.g. simplysave.razorpay.com -> simplysave
         udeals.razorpay.com     -> udeals
    """
    subdomain = domain.split(".")[0]
    # Convert camelCase / hyphens to snake_case
    slug = re.sub(r"[-]", "_", subdomain)
    slug = re.sub(r"([a-z])([A-Z])", r"\1_\2", slug).lower()
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    return slug


def resource_name(slug: str) -> str:
    return f"engage_loyalty_{slug}_record"


def branch_name(slug: str) -> str:
    return f"feature/add-{slug.replace('_', '-')}-domain"


# ── vishnu: add DNS record ────────────────────────────────────────────────────

def add_dns_record(domain: str, slug: str) -> bool:
    """
    Insert a new CNAME block into prod/dns/records.tf just before # endregion.
    Returns True if added, False if already present.
    """
    tf_path = VISHNU_PATH / RECORDS_TF
    content = tf_path.read_text()

    # Check if already present
    if domain in content:
        print(f"  [vishnu] {domain} already exists in records.tf — skipping add.")
        return False

    new_block = (
        f'\nresource "aws_route53_record" "{resource_name(slug)}" {{\n'
        f'  zone_id = data.aws_route53_zone.com.zone_id\n'
        f'  name    = "{domain}"\n'
        f'  type    = "CNAME"\n'
        f'  ttl     = 300\n'
        f'  records = ["{CLOUDFRONT}"]\n'
        f'}}\n'
    )

    # Insert just before # endregion
    if "# endregion" not in content:
        raise RuntimeError("Could not find '# endregion' marker in records.tf")

    updated = content.replace("# endregion", new_block + "# endregion", 1)
    tf_path.write_text(updated)
    print(f"  [vishnu] Added DNS block for {domain}")
    return True


# ── terraform-kong: add CORS origin ──────────────────────────────────────────

def add_cors_origin(https_url: str) -> bool:
    """
    Append https_url to rmp_service_cors_origins list in prod/rewards-marketplace/config.tf.
    Returns True if added, False if already present.
    """
    cfg_path = KONG_PATH / KONG_CONFIG
    content = cfg_path.read_text()

    # Check if already present
    if https_url in content:
        print(f"  [terraform-kong] {https_url} already in cors_origins — skipping add.")
        return False

    # The origins list ends with: ..."lastentry"]
    # We append ,"https://newurl"] before the closing ]
    if 'rmp_service_cors_origins' not in content:
        raise RuntimeError("Could not find rmp_service_cors_origins in config.tf")

    # Replace the closing bracket of the cors_origins list
    updated = re.sub(
        r'(rmp_service_cors_origins\s*=\s*\[.*?)"(\s*\])',
        lambda m: m.group(0).rstrip("]") + f',"{https_url}"]',
        content,
        count=1,
        flags=re.DOTALL,
    )

    if updated == content:
        # Fallback: simple string replacement for the closing bracket pattern
        # Find the cors_origins line and append before its closing ]
        lines = content.splitlines(keepends=True)
        new_lines = []
        for line in lines:
            if "rmp_service_cors_origins" in line and line.rstrip().endswith("]"):
                line = line.rstrip()
                line = line[:-1] + f',"{https_url}"]\n'
            new_lines.append(line)
        updated = "".join(new_lines)

    if updated == content:
        raise RuntimeError("Could not insert URL into rmp_service_cors_origins — pattern not matched.")

    cfg_path.write_text(updated)
    print(f"  [terraform-kong] Added {https_url} to cors_origins")
    return True


# ── Git operations ────────────────────────────────────────────────────────────

def prepare_repo(repo: Path, branch: str):
    """Fetch + reset to latest master, then create fresh branch."""
    print(f"\n[{repo.name}] Pulling latest master...")
    run("git checkout master", repo)
    run("git fetch origin master", repo)
    run("git reset --hard origin/master", repo)

    # Delete branch if it already exists (from a previous attempt)
    run(f"git branch -D {branch}", repo, check=False)
    run(f"git checkout -b {branch}", repo)
    print(f"  Created branch: {branch}")


def commit_and_push(repo: Path, branch: str, message: str):
    run("git add -A", repo)
    status = run("git status --short", repo).stdout.strip()
    if not status:
        print(f"  [{repo.name}] Nothing to commit — already up to date.")
        return False
    run(f'git commit -m "{message}"', repo)
    run(f"git push origin {branch} --force", repo)
    print(f"  [{repo.name}] Pushed branch {branch}")
    return True


def create_pr(repo: Path, title: str, body: str) -> str:
    """Create GitHub PR and return the PR URL. Handles 'already exists' gracefully."""
    import tempfile, os
    # Write body to a temp file — avoids all shell quoting/backtick issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(body)
        body_file = f.name
    try:
        branch = subprocess.run(
            "git branch --show-current", shell=True, cwd=str(repo),
            capture_output=True, text=True
        ).stdout.strip()
        result = subprocess.run(
            ["gh", "pr", "create",
             "--title", title,
             "--body-file", body_file,
             "--head", branch],
            cwd=str(repo), capture_output=True, text=True
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            print(f"  PR created: {url}")
            return url
        # PR already exists — extract URL from stderr
        existing = re.search(r"https://github\.com/\S+/pull/\d+", result.stderr or result.stdout)
        if existing:
            url = existing.group(0)
            print(f"  PR already exists: {url}")
            return url
        raise RuntimeError(
            f"gh pr create failed:\n  stdout: {result.stdout.strip()}\n  stderr: {result.stderr.strip()}"
        )
    finally:
        os.unlink(body_file)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 vishnu_kong_pr.py <url> <ticket_id>")
        print("  e.g: python3 vishnu_kong_pr.py simplysave.razorpay.com ISS-1659503")
        sys.exit(1)

    raw_url = sys.argv[1].strip()
    ticket_id = sys.argv[2].strip().upper()

    https_url = normalize_url(raw_url)
    domain = bare_domain(https_url)
    slug = slug_from_domain(domain)
    branch = branch_name(slug)

    print(f"\n{'='*60}")
    print(f"  URL:       {https_url}")
    print(f"  Domain:    {domain}")
    print(f"  Ticket:    {ticket_id}")
    print(f"  Branch:    {branch}")
    print(f"  Resource:  {resource_name(slug)}")
    print(f"{'='*60}\n")

    # Validate repos exist
    if not VISHNU_PATH.exists():
        print(f"ERROR: vishnu repo not found at {VISHNU_PATH}")
        sys.exit(1)
    if not KONG_PATH.exists():
        print(f"ERROR: terraform-kong repo not found at {KONG_PATH}")
        sys.exit(1)

    vishnu_pr_url = ""
    kong_pr_url = ""

    # ── vishnu ────────────────────────────────────────────────────────────────
    print("── vishnu (DNS) ─────────────────────────────────────────")
    prepare_repo(VISHNU_PATH, branch)
    added = add_dns_record(domain, slug)
    if added:
        commit_msg = f"[{ticket_id}] Add DNS record for {domain} (engage-loyalty)"
        committed = commit_and_push(VISHNU_PATH, branch, commit_msg)
        if committed:
            pr_title = f"[{ticket_id}] Add DNS record for {domain} (engage-loyalty)"
            pr_body = (
                f"Adds CNAME record for `{domain}` pointing to `{CLOUDFRONT}`.\n\n"
                f"Ticket: {ticket_id}\n"
                f"Paired with terraform-kong PR for CORS origin.\n\n"
                f"Made-with: Manideep-Bot"
            )
            vishnu_pr_url = create_pr(VISHNU_PATH, pr_title, pr_body)
    else:
        print(f"  Skipped — {domain} already in vishnu.")

    # ── terraform-kong ────────────────────────────────────────────────────────
    print("\n── terraform-kong (CORS) ────────────────────────────────")
    prepare_repo(KONG_PATH, branch)
    added = add_cors_origin(https_url)
    if added:
        commit_msg = f"[{ticket_id}] Add CORS origin for {domain} (rewards-marketplace)"
        committed = commit_and_push(KONG_PATH, branch, commit_msg)
        if committed:
            pr_title = f"[{ticket_id}] Add CORS origin for {domain} (rewards-marketplace)"
            pr_body = (
                f"Adds `{https_url}` to `rmp_service_cors_origins` in `prod/rewards-marketplace/config.tf`.\n\n"
                f"Ticket: {ticket_id}\n"
                f"Paired with vishnu DNS PR{': ' + vishnu_pr_url if vishnu_pr_url else ''}.\n\n"
                f"Made-with: Manideep-Bot"
            )
            kong_pr_url = create_pr(KONG_PATH, pr_title, pr_body)
    else:
        print(f"  Skipped — {https_url} already in terraform-kong.")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  DONE")
    if vishnu_pr_url:
        print(f"  vishnu PR:         {vishnu_pr_url}")
    if kong_pr_url:
        print(f"  terraform-kong PR: {kong_pr_url}")
    print(f"{'='*60}\n")

    # Output for bot (last two lines parsed by skill_runner)
    if vishnu_pr_url or kong_pr_url:
        print("PRs created successfully:")
        if vishnu_pr_url:
            print(f"  vishnu:          {vishnu_pr_url}")
        if kong_pr_url:
            print(f"  terraform-kong:  {kong_pr_url}")


if __name__ == "__main__":
    main()
