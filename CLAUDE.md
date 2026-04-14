# Manideep Bot — Claude Code Instructions

When the user says **"check"**, process all pending ticket analysis requests.

## FIRST: Read the Persona

Before analyzing ANY ticket, read `template/PERSONA.md`. It contains Manideep's decision-making rules. Follow them exactly:

### Key Decision Rules (from Persona)

**GC Redemption & Cancellation:**
- Redemption report + card number provided → run `gc-redemption-report` FIRST
- Check redemption data: if ONLY 'recharge' transactions (no redemptions) → full balance → CANCELLATION case
- If has redemption entries → card was used → just share the report
- Cancellation REQUIRES a reason. If missing, ask for it — don't proceed without it

**Order Issues:**
- Order ID + failure/visibility → `order-trace-debugger`
- Check order state, customer mapping, visibility flags

**Missing Info:**
- If card number, order_id, or cancellation reason is missing → ask for it, don't guess

## What to do

1. Read `template/PERSONA.md` for full decision logic
2. List files in `data/claude_requests/` (NOT inside `done/`) — each `.md` file is a pending request
3. If no files (only `done/` subfolder), say "No pending requests" and stop
4. For each request file (all in parallel — write all response files at once):
   a. Read it to get the ticket ID (filename = `ISS-XXXXXX.md`)
   b. Fetch ticket details: `curl -s -X POST https://api.devrev.ai/works.get -H "Authorization: $DEVREV_API_KEY" -H "Content-Type: application/json" -d '{"id":"<work_id>"}'`
      - Convert display ID to work ID: `ISS-1234567` → `don:core:dvrv-in-1:devo/2sRI6Hepzz:issue/1234567`
   c. Read the similar tickets section in the request file for context
   d. Apply Persona decision rules to analyze the ticket
   e. Write analysis to `data/claude_responses/<ticket_id>.md`
5. After ALL responses are written → **Archive REQUEST files only**:
   - Move each processed `data/claude_requests/ISS-XXXXXX.md` → `data/claude_requests/done/ISS-XXXXXX.md`
   - Use: `mv data/claude_requests/*.md data/claude_requests/done/`
   - ⚠️ DO NOT move response files — leave `data/claude_responses/ISS-XXXXXX.md` in place
   - The bot's response_watcher will pick them up, post to Slack, save thread state (skill_name), then archive them
   - If you archive responses too early, the bot loses the skill_name and "yes" replies break

## Response format (MUST follow exactly)

```
**Analysis:** <1-2 sentence summary>

**Approach:**
1. <step>
2. <step>
...

**Skill to run:** <skill-name or "none">
**Confidence:** <high / medium / low>

**Suggested tags:** `tag1`, `tag2`, `skill:<skill-name>`
**Suggested fields:** cause_code: ..., pse_pod: ..., severity: ...
```

## Available skills

- `gc-redemption-report` — GC card redemption/balance reports
- `gc-cancellation` — Cancel/deactivate gift cards (REQUIRES cancellation reason)
- `order-trace-debugger` — Trace reward order failures
- `rmp-gandalf` — RMP Gandalf access issues
- `vishnu-terraform-kong-pr` — DNS/Kong route PRs
- `github-pr` — Read PR details or list open PRs (ticket has GitHub PR URL or repo name)
- `voucher-benefit-upload` — Voucher benefit uploads
- `invalid-rewards-debugger` — Debug invalid rewards
- `wallet-closure` — Process wallet closure/refund requests. Parses DevRev ticket, queries Redash for user_id and reversal amounts, fetches admin token, executes closure curl, comments result on ticket. Tag: `wallet_closure`
- `pse-ticket-closer` — Close PSE tickets with cause code, reason for breach, and tags. Run AFTER other skills complete.
- `none` — Manual task, no skill available

## Closing Tickets After Skill Execution

After any skill finishes (e.g., `gc-redemption-report` posts results to the ticket), use `pse-ticket-closer` to close it:

```bash
python3 agent-skills/support/skills/pse-ticket-closer/scripts/close_pse_ticket.py \
  --ticket ISS-XXXXXX \
  --cause-code "<CAUSE_CODE>" \
  --reason-for-breach "<REASON>" \
  --tags <TAG_NAMES>
```

**IMPORTANT:** Always ask the user for cause code, reason for breach, and tags before closing. Do NOT pick defaults.

## Posting Comments on DevRev Tickets

**ALWAYS use DevRev MCP tools** to post comments on tickets. Do NOT use curl/API directly.

```
Use MCP tool: add_comment / create_timeline_entry
- object: don:core:dvrv-in-1:devo/2sRI6Hepzz:issue/XXXXXX
- body: your comment text
- visibility: external (visible to reporter) or internal
```

Links in comments must use markdown format: `[text](url)` — plain URLs work but markdown is preferred.

## GC Redemption Report — Google Sheets

The `gc-redemption-report` skill writes to this shared Google Sheet:
- **Spreadsheet ID:** `1FKyIukL9VoMZYsyabk204EELYqeWSKQHs5AXwPBHJP0`
- **URL:** https://docs.google.com/spreadsheets/d/1FKyIukL9VoMZYsyabk204EELYqeWSKQHs5AXwPBHJP0/edit
- Each card gets its own tab (e.g. `Card_7100155263348049`)
- Always use `--spreadsheet-id` flag (or config.json has it) — never output CSV only
- After running the skill, post the per-card Google Sheet links on the DevRev ticket using MCP

## Environment

- DevRev API key is in `scripts/.env` as `DEVREV_API_KEY`
- Redash Wallet: `REDASH_WALLET_API_KEY` / `REDASH_WALLET_URL` in `scripts/.env`
- Bot watcher auto-posts responses to Slack when files appear in `data/claude_responses/`
- Load env: `source scripts/.env` or `export $(grep -v '^#' scripts/.env | grep '=' | xargs)`

## Confidence rules

- **high**: Similar solved tickets found with matching tags, clear skill match
- **medium**: Pattern matches but no exact tag match
- **low**: Unclear issue, no similar tickets
