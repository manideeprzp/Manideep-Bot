# APIs and tokens needed for Manideep Bot

## Tokens you need to give (bucket flow: no pasting)

For the bot to **watch your bucket**, **analyze tickets**, and let you **Done → Approve** in Slack, set these:

| Token / config | Where to set | Purpose |
|----------------|--------------|---------|
| **DEVREV_API_KEY** | `scripts/.env` | List your tickets (bucket), post comment and close on DevRev |
| **ANTHROPIC_API_KEY** | `scripts/.env` or env | Analyze each ticket and suggest approach + skill (Claude) |
| **SLACK_BOT_TOKEN** | env or config | Post bucket suggestions to Slack and read your replies (Done / Approve) |
| **SLACK_APP_TOKEN** | env or config | Socket Mode so the bot can receive your replies |
| **SLACK_BUCKET_CHANNEL_ID** | env or config | Channel where the bot posts “my tickets” (invite the bot, then copy channel ID) |

You do **not** paste anything: the bot fetches tickets assigned to you, finds relevant past solved tickets, suggests approach + skill, and posts one message per ticket. You reply **Done** in that thread → bot runs the skill and shows execution. You reply **Approve** → bot posts on DevRev and closes the ticket.

---

## Retrieval (understand issue + find relevant past tickets)

| What | API / dependency | Required? |
|------|-------------------|-----------|
| **Solved tickets data** | None (local file) | Yes — run `scripts/fetch_my_solved.py` first; uses **DevRev API** |
| **BM25 scoring** | None (library `rank_bm25`) | No — optional; falls back to word-overlap if not installed |
| **Tag + text matching** | None | No — runs offline once `data/my_solved_tickets.json` exists |

**No external API is needed for retrieval itself.** Dry-run uses only local data and BM25.

---

## Full flow (retrieval + AI suggestion)

| What | API | Required? |
|------|-----|-----------|
| **Suggest approach + skill** | **Anthropic (Claude)** | Yes for suggest and for Slack bot |
| **Slack bot** | **Slack** (Bot + App token) | Yes to run the bot in Slack |

---

## One-time / setup

| What | API | When |
|------|-----|------|
| **Fetch my solved tickets** | **DevRev** | Once and periodically; token in `scripts/.env` as `DEVREV_API_KEY` |
| **Slack notifications (monitor)** | **Slack** (webhook or tokens) | If you use proactive monitor |

---

## Optional (future)

| What | API | Purpose |
|------|-----|---------|
| **Embeddings** | **OpenAI** or **Cohere** | Semantic search (better relevance) |
| **Re-rank with Claude** | **Anthropic** (already used) | Pick top 10 from BM25 top-20 |

---

## Summary

- **Bucket flow (no pasting):** **DevRev** + **Anthropic** + **Slack** (Bot + App token + `SLACK_BUCKET_CHANNEL_ID`).
- **Retrieval (dry-run):** No API; needs `data/my_solved_tickets.json` (from DevRev fetch).
- **Full suggest (CLI or Slack):** **Anthropic**.
- **Slack bot:** **Slack** (Bot + App token).
