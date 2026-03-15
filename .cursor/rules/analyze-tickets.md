---
description: When the user says "check", "analyze", "pending", or "requests" — process all pending bot analysis requests
globs: data/claude_requests/*.md
alwaysApply: false
---

# Analyze Pending Ticket Requests

When the user says **"check"**, **"analyze"**, **"pending"**, or **"new tickets"**, do this:

## FIRST: Read the Persona

Before analyzing ANY ticket, read `template/PERSONA.md`. This contains Manideep's decision-making rules. Follow them exactly. Key rules:

### GC Redemption & Cancellation Logic
- If ticket asks for "redemption report" + card number → run `gc-redemption-report` FIRST
- After getting redemption data, check `transactions.entity_type`:
  - If ONLY 'recharge' transactions (no redemptions) → card has FULL BALANCE → this is a CANCELLATION case
  - If has redemption entries → card was used → just share the report, no cancellation
- For cancellation: MUST have cancellation reason. If missing, ask for it — don't proceed

### Order Issues
- If ticket has order_id + failure/visibility issue → `order-trace-debugger`
- Check order state, customer-to-order mapping, visibility flags

### Missing Information
- If critical info is missing (card number, order_id, cancellation reason), say what's missing
- Don't guess — ask for it

## Steps

1. **Read** `template/PERSONA.md` to load decision-making rules
2. **Scan** `data/claude_requests/` for any `.md` files
3. **For each request file**:
   a. Read the file to get the ticket ID and context
   b. Use DevRev MCP tool `fetch_object_context` with `object_id: ISS-XXXXXX` to get full ticket details
   c. Analyze the ticket USING THE PERSONA RULES — think like Manideep would
   d. Check the "Similar Tickets" section — use their tags and fields
4. **Write the response** to `data/claude_responses/<ticket_id>.md` using this exact format:

```
**Analysis:** <1-2 sentence summary of the issue, who reported it, key details>

**Approach:**
1. <step 1>
2. <step 2>
...

**Skill to run:** <skill-name or "none">
**Confidence:** <high / medium / low>

**Suggested tags:** `tag1`, `tag2`, `skill:<skill-name>`
**Suggested fields:** cause_code: ..., pse_pod: ..., severity: ...
```

5. **Report back** to the user: "Analyzed X tickets. Responses written."

## Available Skills

- `gc-redemption-report` — GC card redemption reports, balance checks
- `gc-cancellation` — Cancel/deactivate gift cards (need cancellation reason)
- `order-trace-debugger` — Trace reward order failures across RMP/Offers/Procurement
- `rmp-gandalf` — RMP Gandalf access/permission issues
- `vishnu-terraform-kong-pr` — DNS/Kong route PRs
- `voucher-benefit-upload` — Voucher benefit uploads
- `invalid-rewards-debugger` — Debug invalid reward issues
- `none` — Manual task, no automated skill available

## Confidence Guidelines

- **high**: Similar solved tickets found with matching tags, clear skill match
- **medium**: Pattern matches but no exact tag match from past tickets
- **low**: Unclear issue, no similar tickets found

## Important

- ALWAYS read `template/PERSONA.md` first — it has the decision logic
- Use DevRev MCP `fetch_object_context` for rich ticket data
- Copy tags from similar solved tickets when suggesting tags
- Add `skill:<skill-name>` tag when a skill is identified
- If critical info is missing, say so — don't guess
- If the ticket is not assigned to Manideep, note that in the analysis
