# APIs and tokens needed for Manideep Bot

## Which API key for what (and why)

| Purpose | API / key | Why |
|--------|-----------|-----|
| **Understand issue + suggest approach + skill** | **Anthropic (Claude)** — `ANTHROPIC_API_KEY` | Claude is used for all "understanding" and structured suggestion (analysis, approach, skill_name, confidence). One-shot Messages API; no tool loop required. |
| **Semantic retrieval (optional)** | **OpenAI** — `OPENAI_API_KEY` | Anthropic does **not** offer an embedding API. For vector/semantic search (better than BM25-only and `min_similarity` to avoid misleading top-k), we use OpenAI `text-embedding-3-small`. |
| **DevRev** | **DevRev** — `DEVREV_API_KEY` | List/fetch works, timeline, post resolution, close. |
| **Slack** | **Slack** Bot + App token + `SLACK_BUCKET_CHANNEL_ID` | Post suggestions and read thread replies (Yes / Approve). |

**Claude Agent SDK:** The [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) is for **agent loops** (tools, MCP, sessions). We do **not** need it for "description understanding" or "skill suggestion"—our flow is a single prompt + structured response, which the standard Anthropic Messages API handles. The Agent SDK does **not** provide embeddings; for vector retrieval you still need an embedding provider (OpenAI or similar).

---

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
| **Solved tickets data** | Local file `data/my_solved_tickets.json` | Yes — from `scripts/fetch_my_solved.py` (uses **DevRev API**); refreshed on schedule (e.g. 24h) and appended on Approve. |
| **BM25 scoring** | Library `rank_bm25` | Optional; falls back to word-overlap if not installed. Corpus = title + body + **thread_text** (timeline). |
| **Semantic search** | **OpenAI** embeddings | Optional. Set `retriever.use_embeddings: true` and `OPENAI_API_KEY` for vector similarity + `min_similarity` threshold. |

**Why two keys for "AI":** Claude is used for **chat/understanding** (one API). **Embeddings** are a different product; Anthropic does not offer them, so we use OpenAI for vector retrieval when you want better-than-BM25 matching and a similarity threshold.

**When solved tickets have no "how I solved" in the thread:** We still match on title, body, and tags. Fetching timeline (default in `fetch_my_solved.py`) adds any comments that exist. Adding a resolution comment when closing (e.g. "Resolved via: order-trace-debugger") improves future retrieval.

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

## Cron / scheduled fetch and permissions

- **Scheduled solved fetch (e.g. every 24h):** Runs with the same **DEVREV_API_KEY**; no extra DevRev permission. No interactive "your permission" per run—the script runs as the process user with env vars.
- **Slack:** Retrieval runs server-side (no Slack call). Only posting suggestions and reading thread replies need **channel access** for the bot; that is sufficient.

---

## Optional

| What | API | Purpose |
|------|-----|---------|
| **Embeddings** | **OpenAI** — `OPENAI_API_KEY` | Semantic search; set `retriever.use_embeddings: true` and `min_similarity` (e.g. 0.5) to reduce misleading top-k. |

---

## Summary

- **Bucket flow:** **DevRev** + **Anthropic** + **Slack** (Bot + App token + `SLACK_BUCKET_CHANNEL_ID`).
- **Full AI experience:** You need **both** keys: **ANTHROPIC_API_KEY** (understanding + skill suggestion) and **OPENAI_API_KEY** (optional but recommended for semantic retrieval / embeddings). Anthropic does not provide an embedding API.
- **Cron/scheduled fetch:** Use Slack command “fetch updated tickets” in the channel, or system cron; same **DEVREV_API_KEY**. **Slack:** channel access for the bot is enough.
- **Single channel:** All ticket threads and bot commands (fetch tickets, help, future interactions) happen in the same Slack channel. See [ARCHITECTURE.md](ARCHITECTURE.md).
