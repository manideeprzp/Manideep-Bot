# Manideep Bot

Slack bot that **works like you**: uses your **past solved DevRev tickets** and **generated skills** to suggest what to do for tickets. You @mention it, paste a ticket, and it replies with a suggestion and asks for **Yes / No / Proceed**.

All code and data live in this folder (Desktop/manideep-bot).

---

## Setup

### 1. One-time: DevRev data and skills

```bash
cd ~/Desktop/manideep-bot/scripts
cp .env.example .env
# Edit .env: set DEVREV_API_KEY=your-token

pip install -r requirements.txt
python3 fetch_my_solved.py
python3 generate_skills_from_solved.py
```

This writes `data/my_solved_tickets.json` and `solved/*.md`. The bot uses these when you @mention it.

### 2. Slack app

- Create a Slack app with **Socket Mode**.
- **Bot Token Scopes:** `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`, `groups:history`, `im:history` (so the bot can read thread replies).
- **Subscribe to Bot Events:** `app_mention`, `message.channels`, `message.groups`, `message.im` (so you can reply "Yes" / "Approve" in the same thread).
- Install to workspace; copy **Bot User OAuth Token** (`xoxb-...`) and **App-Level Token** (`xapp-...`).

### 3. Run the bot

```bash
cd ~/Desktop/manideep-bot
pip install -r requirements.txt
pip install -e .

export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export ANTHROPIC_API_KEY=sk-ant-...

python -m manideep_bot.app
# or: manideep-bot
```

---

## Usage

1. **@Manideep Bot** and paste a ticket (title, description, or link). It suggests an approach and a **skill to run**.
2. Reply **Yes** (or **Proceed**) → the bot runs the skill and posts the output.
3. Review the output; reply **Approve** → the bot posts the resolution on the DevRev ticket and closes it (two-step verification).

Include the ticket ID (e.g. `ISSUE-123`) in your first message or when you Approve so the bot can post and close the right ticket.

---

## Bucket flow (no pasting)

The bot can **watch your DevRev bucket** (tickets assigned to you), analyze each in parallel, and post suggestions to Slack. You only reply **Done** → **Approve**; no pasting.

1. **Grant tokens** (see **docs/APIS_NEEDED.md**): `DEVREV_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and **`SLACK_BUCKET_CHANNEL_ID`** (channel where the bot posts; invite the bot and copy the channel ID).
2. **Run the Slack bot** so it can read your replies: `manideep-bot` (or `python -m manideep_bot.app`).
3. **Run the bucket watcher** (once or on a schedule):  
   `manideep-bot-bucket` (or `python -m manideep_bot.bucket_cli`).  
   It fetches your open tickets, finds relevant past solved tickets, gets an AI suggestion per ticket, and posts one message per ticket in the bucket channel.
4. In Slack, for each ticket: reply **Done** in that thread → bot runs the skill and shows execution. Review, then reply **Approve** → bot posts on DevRev and closes the ticket.

Config: `config/env.dev.yaml` → `slack.bucket_channel_id`, `bucket.max_tickets_per_run`, `bucket.states`.

---

## Proactive monitor (new tickets + my tickets with new replies)

The bot can **proactively** look at (1) **new tickets** matching your filters and (2) **tickets assigned to you** for **new replies** (e.g. reporter replied on "Awaiting info"). When it finds something, it posts to Slack (via `SLACK_WEBHOOK_URL`).

- **Config:** `config/env.dev.yaml` → `monitor.enabled`, `monitor.interval_minutes`, `monitor.new_ticket_filters` (e.g. `applies_to_part`), `monitor.my_tickets`.
- **Run once:** `manideep-bot-monitor` (or `python -m manideep_bot.monitor_cli`).
- **Run loop:** `manideep-bot-monitor run` (runs every `interval_minutes`). Set `SLACK_WEBHOOK_URL` and `DEVREV_API_KEY` (in `scripts/.env` or env).

See **docs/WORKFLOW.md** for the full flow (channels, monitor, two-step approval, skill runner, post to DevRev and close).

---

## Folder structure

```
manideep-bot/
├── config/             # env.dev.yaml (Slack, Anthropic, DevRev, monitor)
├── template/           # PERSONA.md, SAFETY.md
├── docs/               # WORKFLOW.md (full spec)
├── src/manideep_bot/   # app, agent, config, devrev_client, monitor, skill_runner, prompts
├── scripts/            # DevRev fetch/generate, slack_notify
├── data/               # my_solved_tickets.json, monitor_state.json
├── solved/             # Generated skills
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Understand issue + find relevant past (phase 2)

When you @mention the bot or run the agent, it now:
1. **Understands** the current issue from the title/description you paste.
2. **Finds relevant past solved tickets** using tag overlap + text similarity (no extra ML deps).
3. Injects those into the prompt so the AI suggests an approach and skill (e.g. "Based on ISS-1609523, run gc-redemption-report").

**Test from CLI (no Slack):**
```bash
# Dry-run: retrieval only (BM25 + tags), no API key
.venv/bin/python scripts/suggest_from_past.py --dry-run "Blinkit GC redemption code not received"
.venv/bin/python scripts/suggest_from_past.py -n 15 "order trace 757987924"   # top 15, optional --no-bm25 for word-overlap only

# Full AI suggestion (needs ANTHROPIC_API_KEY)
.venv/bin/python scripts/suggest_from_past.py --suggest "Order 757987924 fulfillment failed"
```

**APIs needed:** Retrieval uses no external API (local data + BM25). Full suggest needs **Anthropic**. See **docs/APIS_NEEDED.md** for a full list.

---

## Optional scripts

- **Fetch my solved / generate skills:** `scripts/fetch_my_solved.py`, `scripts/generate_skills_from_solved.py`.
- **Suggest from past (retriever + optional AI):** `scripts/suggest_from_past.py "issue text"` or `--suggest`.
- **Monitor tickets (one-off):** `scripts/fetch_tickets_to_monitor.py --mode assigned-to-me`.
- **Slack notify:** `scripts/slack_notify.py --ticket-id X --title "..." --suggestion "..."` (uses `SLACK_WEBHOOK_URL` in `scripts/.env`).
