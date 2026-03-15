# Architecture: event-driven, one channel, minimal polling

## System architecture (what runs where)

You do **not** need a separate “core” server or a big stack. The bot runs as one or two small processes:

| What you run | What it is | Needs public URL? |
|--------------|------------|--------------------|
| **Slack bot** (`python -m manideep_bot.app`) | One long‑running process. Connects to Slack via **Socket Mode** (outbound WebSocket), so Slack pushes events (messages, mentions) to your process. No inbound HTTP from Slack = no public URL or ngrok for Slack. | **No** |
| **Webhook server** (optional; `python -m manideep_bot.webhook_cli`) | HTTP server that receives **DevRev** `work_created` POSTs. Only needed if you use DevRev webhook (not workflow). DevRev must reach your server, so you need a public URL (ngrok, cloud, etc.). | **Yes**, only if you use DevRev webhook |

So in the **workflow-based** setup (recommended for you): run **only the Slack bot**. No server, no ngrok. The DevRev workflow posts into Slack; the bot reacts to messages in the channel. Data lives on the machine where the bot runs (`data/my_solved_tickets.json`, config, env).

**How the bot works:**

1. You start the bot → it opens an outbound connection to Slack (Socket Mode).
2. Slack sends events (e.g. “new message in #pse-tickets”) to your process.
3. The bot handles the event (e.g. “message contains ISSUE-123” → fetch from DevRev, run agent, post reply in thread).
4. All logic (retrieval, agent, DevRev API, skills) runs inside this same process. No separate “core” service.

---

## Target flow (current): DevRev workflow → new thread → bot enters thread

Your approach: **DevRev workflow** creates a **new Slack thread** whenever a new issue is created (the workflow posts a parent message; that message starts the thread). The **bot’s job** is to **enter that thread** and do its work:

1. **Workflow** posts a message in your channel (e.g. “New issue: ISSUE-456” or a link). That message is the **thread parent** (no `thread_ts`).
2. **Bot** sees the message (in the configured channel), parses the issue ref, fetches the work from DevRev, runs analysis, and **replies in that same thread** (`thread_ts` = the workflow message’s `ts`). So the bot is the first (or one of the first) to “enter” the thread.
3. In that thread you reply **Yes** → bot runs the skill; **Approve** → bot posts resolution on DevRev and closes the ticket.

Other flows (e.g. webhook‑driven new issue, or different triggers) can be added later; for now the **target** is: **new thread created on new issue → bot enters the thread and does his things.**

---

## Design principles

- **Use system resources meaningfully:** No continuous DevRev polling. New issues come from **DevRev webhook** (or workflow posting to Slack). Solved-tickets refresh is **on demand** (Slack command or system cron), not a 24/7 loop.
- **One Slack channel:** All ticket-related threads and bot commands live in the same channel. New issue → bot posts in thread; you reply Yes/Approve in that thread. You can also chat with the bot: e.g. “fetch updated tickets”, “help”.
- **Both API keys for full experience:** **ANTHROPIC_API_KEY** (Claude) for understanding and skill suggestion; **OPENAI_API_KEY** for optional semantic retrieval (embeddings). See [APIS_NEEDED.md](APIS_NEEDED.md).

## What runs in production

| Component | Role | When |
|-----------|------|------|
| **Webhook server** | Receives DevRev `work_created` → fetches work, analyzes, posts to Slack channel in a thread | Run when you want new-issue events from DevRev (needs public URL / ngrok or deploy). |
| **Slack bot** | Handles all conversation in the channel: ticket threads (Yes/Approve), commands (“fetch updated tickets”, “help”) | Run always so you can interact. |
| **Monitor (optional)** | Polls DevRev for new tickets + “my tickets” updates | **Not required** if you use webhook (or workflow) for new issues. Use only if you need proactive “my tickets” polling. |
| **Solved tickets refresh** | Updates `data/my_solved_tickets.json` | **Slack:** say “fetch updated tickets” in the channel. **Or** system cron: `0 */12 * * * cd /path/to/manideep-bot && python scripts/fetch_my_solved.py`. |

So: run **webhook server** (if you use DevRev webhook) + **Slack bot**. Do **not** run a continuous monitor just to refresh solved tickets; use the Slack command or cron instead.

## Single channel flow

1. **New issue:** DevRev sends `work_created` to your webhook → webhook posts to your Slack channel (one message per issue, each can start a thread). Or a DevRev workflow posts a message with issue ref → bot sees it and replies in thread.
2. **Ticket thread:** Bot’s reply contains analysis and “Reply **Yes** to run the skill, then **Approve** to close.” You reply **Yes** / **Approve** in that same thread.
3. **Commands:** In the same channel (or in a thread), you can say **@bot fetch updated tickets** or **@bot help**. Future commands (e.g. cron approval) can be added in `src/manideep_bot/commands.py`.

## Resolution: conversation + tag

When you **Approve**, the bot:

- Posts a **timeline comment** on the ticket: “Resolution: …” and **“Resolved via: &lt;skill_name&gt;”** so retrieval and humans see how it was closed.
- Sets the work **stage** to closed.
- Tries to add a **tag** `resolved_via: &lt;skill_name&gt;` on the work (if your DevRev org has that tag). If the tag doesn’t exist, only the timeline comment is used.
- Appends the ticket to `my_solved_tickets.json` so it’s available for retrieval immediately.

**Recommendation:** Prefer the **timeline comment** (“Resolved via: …”) as the main signal; the tag is optional for filtering in DevRev.
