# Manideep Bot — Full Workflow

## 1. Channels

- Bot responds **anywhere it’s invited** (channels or DMs). You can restrict to certain channels later via config (`allowed_channel_ids`).

---

## 2. Proactive monitor (two streams)

### Stream A – New tickets (with your filters)

- **What:** New tickets created that match **filters you configure** (e.g. part/pod, state, tags).
- **How:** On an **interval** (e.g. every 15–30 min), bot fetches works with those filters and `created_date` (or cursor) since last run.
- **Output:** Post to Slack: “New ticket: [link] … Suggestion (from past/skills): … Reply **Yes** / **No** / **Proceed**.”

### Stream B – My tickets (updates and new replies)

- **What:** Tickets **assigned to you**.
- **Why:** So you know when:
  - A ticket you left in “Awaiting info from reporter” gets a **new reply** (reporter provided info) → you can pick it up again.
  - **Status/stage** changes (e.g. reopened, unblocked).
- **How:** On the same interval, fetch works `owned_by=me` in open states; for each, call **timeline-entries.list** and compare with last known timeline (e.g. last entry id or count). If there’s a **new timeline entry** (comment/reply) since last check → notify: “Ticket X – new reply from reporter” (or “new activity”) with link.
- **Config:** Optional list of **stages** you care about for “awaiting info” (e.g. “Awaiting info from reporter”); bot can prioritise or only notify when ticket is in that stage and a **non-you** user added a comment (reporter replied).

---

## 3. Two-step verification and execution

### Step 1 – Suggest and first approval

1. Bot posts (from monitor or from your @mention): “This is the ask. Based on past/skills I think we can solve it like this: [approach]. Use skill: **X**. Reply **Yes** / **No** / or give other instructions.”
2. You reply **Yes** (or **Proceed**) or correct the bot.
3. If **Yes**: bot **runs the skill** (see Skill runner below) and **posts the output** in the same thread.

### Step 2 – Review and final approval (post to DevRev + close)

4. Bot posts: “Work done. Output: [summary/output]. Review. If correct, reply **Approve** to post this on the ticket and close it.”
5. You reply **Approve** (or ask changes).
6. On **Approve**: bot:
   - **Posts a comment** on the DevRev ticket (timeline-entries.create) with the resolution summary / what was done.
   - **Updates the work** (works.update) to set **stage** to your “closed”/“resolved” stage (configurable).
7. Bot confirms in Slack: “Posted update on ticket and closed.”

So: **Suggest → Yes → Bot runs skill → Shows output → Approve → Bot posts on ticket and closes.**

---

## 4. Skill runner (bot “does the work”)

- **Runnable skills** are mapped in config to **scripts** (and how to get arguments from the ticket).
- Example: `order-trace-debugger` → run `trace_order.py <order_id>`; `order_id` is parsed from ticket title/body (or you pass it in Slack).
- Bot runs the script, captures stdout/stderr, and posts a short summary (or key lines) in Slack for your review. If the script can’t run (e.g. missing order_id), bot says “I need order_id – please share it” and you can reply with it.
- Over time you can add more skills and tune parsing so the bot improves.

---

## 5. Config (summary)

| Item | Purpose |
|------|--------|
| **Monitor interval** | Minutes between runs (e.g. 15 or 30). |
| **New-ticket filters** | e.g. `applies_to_part`, `state`, `created_after` (or “since last run”). You specify these. |
| **My-tickets** | Enable/disable; which stages to watch (e.g. “Awaiting info from reporter”); “notify on new reply” (timeline check). |
| **Closed stage name** | Stage to set when you Approve (e.g. “Closed”, “Resolved”) – your DevRev org’s stage name. |
| **Skill → script mapping** | Which skills are runnable and which script + how to get args from ticket. |
| **Channels** | Optional: restrict to certain channel IDs. |

---

## 6. DevRev APIs used

- **works.list** – New tickets (filters); my tickets (owned_by=me).
- **timeline-entries.list** – Comments/replies on a work item (object = work id); detect “new reply”.
- **timeline-entries.create** – Post comment on ticket (resolution summary).
- **works.update** – Update work stage to closed (and optionally title/body).

---

## 7. Flow diagram

```
Monitor (every N min)
  ├─ New tickets (filters) ──► Slack: "New ticket + suggestion" → You: Yes/No/Proceed
  └─ My tickets ──► For each: timeline_entries.list
                    └─ New entry since last run? ──► Slack: "Ticket X – new reply, ready for you"

You: Yes/Proceed
  └─ Bot runs skill (script) ──► Post output in thread

You: Approve
  └─ timeline_entries.create (comment) + works.update (stage=closed) ──► Slack: "Posted and closed"
```
