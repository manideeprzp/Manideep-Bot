#!/usr/bin/env python3
"""
PSE Ticket Closer — Close DevRev PSE tickets with proper stage transitions,
custom fields (cause code, reason for breach), and tags.
"""

import argparse
import json
import os
import sys
import requests
from pathlib import Path

# DevRev API
DEVREV_BASE = "https://api.devrev.ai"
ORG_PREFIX = "don:core:dvrv-in-1:devo/2sRI6Hepzz"
CUSTOM_SCHEMA_FRAGMENT = f"{ORG_PREFIX}:custom_type_fragment/17324"

# PSE stage transition path: Triage -> Acknowledged -> Under Investigation -> PSE Fixing -> Closed
STAGE_PATH = ["acknowledged", "Under Investigation", "PSE Fixing", "Closed"]

VALID_CAUSE_CODES = [
    "Caused by Incident",
    "Config Change",
    "Dev Intervention - Code Debugging",
    "Dev Intervention - Code Fix",
    "Dev Intervention - Data Fix",
    "Dev Intervention - Log/Tech Issue",
    "Dev Intervention - Product Bug",
    "Issue due to Internal stakeholder teams",
    "Issue due to externals partners",
    "L1 Solvable",
    "No Response from Merchant/Business Teams",
    "Not via Standard Channel",
    "PSE - Code Debugging",
    "PSE - Code Fix",
    "PSE - Data Fix",
    "PSE - Log/Tech Issue",
    "PSE - Product Bug",
    "Product Intervention - New Enhancement",
]

VALID_BREACH_REASONS = [
    "Breached by Engineering",
    "Breached by PSE",
    "Delay Response from Merchant",
    "Delay from Gateway / Bank / NPCI",
    "Delay from Internal Teams",
    "Delay in Deployment / PR / Approvals",
    "Incorrect Priority / Severity by TS",
    "Priority / Severity Upgraded",
    "SLA Not Breached",
    "Ticket Reopened",
]


def load_api_key():
    """Load DevRev API key from scripts/.env"""
    env_paths = [
        Path(__file__).resolve().parent.parent.parent.parent.parent.parent / "scripts" / ".env",
        Path.home() / "Desktop" / "razorpay" / "manideep-bot" / "scripts" / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DEVREV_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Fallback to environment variable
    key = os.environ.get("DEVREV_API_KEY")
    if key:
        return key
    print("ERROR: DEVREV_API_KEY not found in scripts/.env or environment", file=sys.stderr)
    sys.exit(1)


def devrev_post(endpoint, payload, api_key):
    """Make a POST request to DevRev API."""
    resp = requests.post(
        f"{DEVREV_BASE}/{endpoint}",
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json=payload,
    )
    return resp.json()


def devrev_get(endpoint, params, api_key):
    """Make a GET request to DevRev API."""
    resp = requests.get(
        f"{DEVREV_BASE}/{endpoint}",
        headers={"Authorization": api_key},
        params=params,
    )
    return resp.json()


def ticket_to_urn(ticket_id):
    """Convert ISS-XXXXXX to full DevRev URN."""
    num = ticket_id.replace("ISS-", "").replace("iss-", "")
    return f"{ORG_PREFIX}:issue/{num}"


def get_current_stage(ticket_urn, api_key):
    """Get current stage name of a ticket."""
    data = devrev_get("works.get", {"id": ticket_urn}, api_key)
    stage = data.get("work", {}).get("stage", {}).get("name", "unknown")
    return stage.lower()


def transition_stages(ticket_urn, current_stage, api_key, dry_run=False):
    """Walk through PSE stage path to reach Closed."""
    current = current_stage.lower()

    # Find where we are in the path
    path_lower = [s.lower() for s in STAGE_PATH]
    start_idx = 0
    for i, stage in enumerate(path_lower):
        if current == stage:
            start_idx = i + 1
            break

    remaining = STAGE_PATH[start_idx:]
    if not remaining:
        if current == "closed":
            print(f"  Already Closed")
            return True
        else:
            print(f"  WARNING: Current stage '{current_stage}' not in standard path, attempting direct transitions")
            remaining = STAGE_PATH

    for stage_name in remaining:
        if dry_run:
            print(f"  [DRY RUN] Would transition -> {stage_name}")
            continue

        result = devrev_post("works.update", {
            "id": ticket_urn,
            "type": "issue",
            "stage": {"name": stage_name},
        }, api_key)

        actual = result.get("work", {}).get("stage", {}).get("name", "")
        error = result.get("message", "")

        if error and not actual:
            print(f"  FAILED -> {stage_name}: {error}")
            return False
        else:
            print(f"  -> {stage_name}: OK")

    return True


def set_custom_fields(ticket_urn, cause_code, reason_for_breach, api_key, dry_run=False):
    """Set cause_code and reason_for_breach custom fields."""
    if dry_run:
        print(f"  [DRY RUN] Would set cause_code='{cause_code}', reason_for_breach='{reason_for_breach}'")
        return True

    result = devrev_post("works.update", {
        "id": ticket_urn,
        "type": "issue",
        "custom_schema_fragments": [CUSTOM_SCHEMA_FRAGMENT],
        "custom_fields": {
            "ctype__cause_code": cause_code,
            "ctype__reason_for_breach": reason_for_breach,
        },
    }, api_key)

    if result.get("message"):
        print(f"  Custom fields FAILED: {result['message']}")
        return False
    print(f"  Custom fields: OK")
    return True


def resolve_tag(tag_name, api_key):
    """Find tag by name, create if not found. Returns tag URN."""
    result = devrev_post("tags.list", {"name": tag_name}, api_key)
    tags = result.get("tags", [])

    # Exact match
    for tag in tags:
        if tag.get("name", "").lower() == tag_name.lower():
            return tag["id"]

    # Not found — create it
    print(f"  Tag '{tag_name}' not found, creating...")
    result = devrev_post("tags.create", {"name": tag_name}, api_key)
    tag = result.get("tag", {})
    if tag.get("id"):
        print(f"  Created tag: {tag['id']}")
        return tag["id"]

    print(f"  WARNING: Could not create tag '{tag_name}': {result.get('message', 'unknown error')}")
    return None


def add_tags(ticket_urn, tag_ids, api_key, dry_run=False):
    """Add tags to a ticket."""
    if not tag_ids:
        return True

    if dry_run:
        print(f"  [DRY RUN] Would add {len(tag_ids)} tag(s)")
        return True

    result = devrev_post("works.update", {
        "id": ticket_urn,
        "type": "issue",
        "tags": {"set": [{"id": tid} for tid in tag_ids]},
    }, api_key)

    if result.get("message"):
        print(f"  Tags FAILED: {result['message']}")
        return False
    print(f"  Tags: OK ({len(tag_ids)} added)")
    return True


def add_comment(ticket_urn, comment_text, api_key, dry_run=False):
    """Add an internal comment to the ticket."""
    if dry_run:
        print(f"  [DRY RUN] Would add comment: {comment_text[:50]}...")
        return True

    result = devrev_post("timeline-entries.create", {
        "type": "timeline_comment",
        "object": ticket_urn,
        "body": comment_text,
        "visibility": "internal",
    }, api_key)

    if result.get("timeline_entry", {}).get("id"):
        print(f"  Comment: OK")
        return True
    print(f"  Comment FAILED: {result.get('message', 'unknown')}")
    return False


def close_ticket(ticket_id, cause_code, reason_for_breach, tag_ids, api_key, dry_run=False, comment=None):
    """Close a single PSE ticket with all required metadata."""
    ticket_urn = ticket_to_urn(ticket_id)
    print(f"\n--- {ticket_id} ---")

    # 1. Get current stage
    current_stage = get_current_stage(ticket_urn, api_key)
    print(f"  Current stage: {current_stage}")

    # 2. Add comment if provided
    if comment:
        add_comment(ticket_urn, comment, api_key, dry_run)

    # 3. Set custom fields
    fields_ok = set_custom_fields(ticket_urn, cause_code, reason_for_breach, api_key, dry_run)

    # 4. Add tags
    tags_ok = add_tags(ticket_urn, tag_ids, api_key, dry_run)

    # 5. Transition stages to Closed
    closed_ok = transition_stages(ticket_urn, current_stage, api_key, dry_run)

    # 6. Verify final stage
    if not dry_run:
        final_stage = get_current_stage(ticket_urn, api_key)
        success = final_stage == "closed"
        status = "CLOSED" if success else f"FAILED (stage: {final_stage})"
    else:
        status = "DRY RUN"
        success = True

    print(f"  Result: {status}")
    return success


def validate_inputs(cause_code, reason_for_breach):
    """Validate cause code and reason for breach against allowed values."""
    # Case-insensitive match
    matched_cause = None
    for valid in VALID_CAUSE_CODES:
        if valid.lower() == cause_code.lower():
            matched_cause = valid
            break
    if not matched_cause:
        print(f"ERROR: Invalid cause code: '{cause_code}'", file=sys.stderr)
        print(f"Valid values:", file=sys.stderr)
        for v in VALID_CAUSE_CODES:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    matched_reason = None
    for valid in VALID_BREACH_REASONS:
        if valid.lower() == reason_for_breach.lower():
            matched_reason = valid
            break
    if not matched_reason:
        print(f"ERROR: Invalid reason for breach: '{reason_for_breach}'", file=sys.stderr)
        print(f"Valid values:", file=sys.stderr)
        for v in VALID_BREACH_REASONS:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    return matched_cause, matched_reason


def main():
    parser = argparse.ArgumentParser(description="Close PSE DevRev tickets")
    parser.add_argument("--ticket", nargs="+", required=True, help="ISS-XXXXXX ticket ID(s)")
    parser.add_argument("--cause-code", required=True, help="Cause code for closing")
    parser.add_argument("--reason-for-breach", required=True, help="Reason for breach")
    parser.add_argument("--tags", nargs="+", required=True, help="Tag name(s) to add")
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    parser.add_argument("--comment", help="Internal comment to add before closing")
    args = parser.parse_args()

    # Validate
    cause_code, reason_for_breach = validate_inputs(args.cause_code, args.reason_for_breach)

    # Load API key
    api_key = load_api_key()

    print("=" * 60)
    print("PSE Ticket Closer")
    print("=" * 60)
    print(f"  Tickets: {', '.join(args.ticket)}")
    print(f"  Cause Code: {cause_code}")
    print(f"  Reason for Breach: {reason_for_breach}")
    print(f"  Tags: {', '.join(args.tags)}")
    if args.dry_run:
        print(f"  Mode: DRY RUN")
    print()

    # Resolve tags (once for all tickets)
    print("Resolving tags...")
    tag_ids = []
    for tag_name in args.tags:
        tag_id = resolve_tag(tag_name, api_key)
        if tag_id:
            tag_ids.append(tag_id)
            print(f"  '{tag_name}' -> {tag_id}")

    # Close each ticket
    results = {}
    for ticket_id in args.ticket:
        # Normalize ticket ID format
        if not ticket_id.upper().startswith("ISS-"):
            ticket_id = f"ISS-{ticket_id}"
        else:
            ticket_id = ticket_id.upper()

        success = close_ticket(
            ticket_id, cause_code, reason_for_breach, tag_ids,
            api_key, dry_run=args.dry_run, comment=args.comment,
        )
        results[ticket_id] = success

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for ticket_id, success in results.items():
        icon = "OK" if success else "FAILED"
        print(f"  {ticket_id}: {icon}")
    print("=" * 60)

    # Exit with error if any failed
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
