# Manideep Bot

Slack bot that **works like you**: uses your **past solved DevRev tickets** and **skills** to analyze and resolve tickets.

**Two modes:**
- **🎓 Claude Code Mode** (recommended): You analyze tickets using Claude Code - no API key needed, free, great for learning
- **🤖 API Mode**: Bot auto-analyzes tickets using Claude API - faster, costs ~$0.01/ticket

**Simple workflow:** New ticket → Bot analyzes → Reply "Yes" → Skill runs → Reply "Approve" → Ticket closed ✅

---

## 🚀 Quick Start

**5-minute setup:**

```bash
# 1. Install
cd ~/Desktop/manideep-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# 2. Set up environment
cd scripts
cp .env.example .env
# Edit .env: add DEVREV_API_KEY, SLACK_BOT_TOKEN, SLACK_APP_TOKEN

# 3. Fetch past tickets
python3 fetch_my_solved.py

# 4. Run bot + auto-watcher (no API key needed!)
cd ..
python -m manideep_bot.app           # Terminal 1
./scripts/run_auto_watcher.sh        # Terminal 2
```

**📖 Detailed setup:** See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)

---

## 🎯 How It Works

### Automatic Mode (Recommended for Development)

1. **New ticket arrives** → Auto-watcher analyzes automatically (5-10 seconds)
2. **Analysis posted to Slack** with confidence, similar tickets, and skill name
3. **Reply "Yes"** → Skill runs → Reply **"Approve"** → Ticket closed

**You don't run any manual commands!** Just approve in Slack.

**Benefits:** Free, no API key, fully automatic, great for learning

📖 See [docs/CLAUDE_CODE_INTEGRATION.md](docs/CLAUDE_CODE_INTEGRATION.md)

### API Mode (For Production)

1. Set `ANTHROPIC_API_KEY` in environment
2. Bot automatically analyzes new tickets
3. Posts suggestion to Slack
4. You approve with "Yes" / "Approve"

**Benefits:** Fast, autonomous, scales to many tickets

---

## 📖 Documentation

| Doc | What's Inside |
|-----|---------------|
| **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** | **⭐ Start here!** Complete setup guide |
| [CLAUDE_CODE_INTEGRATION.md](docs/CLAUDE_CODE_INTEGRATION.md) | Claude Code workflow (no API key needed) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, what runs where |
| [SKILL_BUILDING_GUIDE.md](docs/SKILL_BUILDING_GUIDE.md) | Build skills for common issue types |
| [APIS_NEEDED.md](docs/APIS_NEEDED.md) | Which API keys and why |
| [DEVREV_WORKFLOW_SLACK.md](docs/DEVREV_WORKFLOW_SLACK.md) | DevRev workflow integration |
| [MONITOR.md](docs/MONITOR.md) | Optional polling monitor |
| [WEBHOOK.md](docs/WEBHOOK.md) | DevRev webhook setup |

📁 Full docs: [docs/README.md](docs/README.md)

---

## Setup (Detailed)

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

A **separate process** continuously checks (1) **new issues** under your filters and (2) **updates** on tickets **assigned to you**. It posts to the **same Slack channel** (and threads) as the bot so you can reply **Yes** / **Approve** there.

- **Run continuously:** `./run-monitor.sh` or `manideep-bot-monitor run` (polls every `interval_minutes`, default 20).
- **Run once (test):** `manideep-bot-monitor` or `python -m manideep_bot.monitor_cli once`.
- **Config:** `config/env.dev.yaml` → `monitor.enabled`, `monitor.interval_minutes`, `monitor.new_ticket_filters`, `monitor.my_tickets`. Set `slack.bucket_channel_id` (or `SLACK_BUCKET_CHANNEL_ID`) so monitor posts to the same channel as the bot.

**Full details:** **docs/MONITOR.md** (filters, env overrides, two processes).

Monitor and bucket posts now include **Related past tickets** (links to similar solved issues) so you can compare at a glance.

---

## DevRev webhook (new-issue trigger)

Instead of (or in addition to) polling, you can receive **work_created** events from DevRev via webhook. When a new issue is created, DevRev POSTs to your server; the bot analyzes it and posts to Slack immediately.

- **Run webhook server:** `manideep-bot-webhook` (or `python -m manideep_bot.webhook_cli`). Requires a **public HTTPS URL** (deploy or use ngrok for local dev).
- **Config:** Set `DEVREV_WEBHOOK_SECRET` (from DevRev when you create the webhook). Optional: `devrev.webhook_secret` and `devrev.app_base_url` in `config/env.dev.yaml`.
- **Register URL with DevRev:** Run `python3 scripts/register_devrev_webhook.py --url https://YOUR-PUBLIC-URL/webhooks/devrev` (or call `webhooks.create` via curl). See **docs/WEBHOOK.md** for full setup, verification, and testing.

**Recommended (no webhook URL):** Use a **DevRev workflow** that posts new issues to your Slack channel; the bot enters the thread and runs analysis. See **docs/DEVREV_WORKFLOW_SLACK.md** and **docs/ARCHITECTURE.md**.

---

## Folder structure

```
manideep-bot/
├── .cursor/rules/      # Cursor AI rules (analyze-tickets.md)
├── config/             # env.dev.yaml (Slack, DevRev, retriever, monitor)
├── docs/               # ARCHITECTURE, APIS_NEEDED, WEBHOOK, MONITOR, ENHANCED_AGENT, etc.
├── src/manideep_bot/   # Core bot code
│   ├── app.py              # Slack bot entry point
│   ├── agent.py            # Basic AI agent
│   ├── enhanced_agent.py   # Pattern matching + confidence scoring
│   ├── claude_code_agent.py # File-based Claude Code analysis
│   ├── devrev_client.py    # DevRev API client
│   ├── response_watcher.py # Polls for Claude Code responses
│   ├── skill_runner.py     # Execute skills
│   ├── config.py           # Configuration loader
│   ├── retriever.py        # Past ticket search (BM25 + tags)
│   ├── commands.py         # Slack slash commands
│   ├── bucket.py           # Bucket watcher
│   ├── monitor.py          # Polling monitor
│   ├── webhook_app.py      # DevRev webhook handler
│   └── prompts.py          # Prompt templates
├── scripts/            # Utilities (fetch_my_solved, auto_watcher, etc.)
├── template/           # PERSONA.md, SAFETY.md (agent prompts)
├── workflows/          # Skill workflow templates
├── data/               # Runtime data (gitignored)
├── solved/             # Generated skill docs from solved tickets
├── CLAUDE.md           # Instructions for Claude Code CLI
├── pyproject.toml
├── requirements.txt
├── run_bot.sh          # Start bot + auto-watcher
├── run-monitor.sh      # Start ticket monitor
└── setup_once.sh       # One-time setup
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

- **Fetch my solved tickets:** `scripts/fetch_my_solved.py` (with optional `--no-timeline` for faster run). Or say **@bot fetch updated tickets** in Slack.
- **Generate skills from solved:** `scripts/generate_skills_from_solved.py`.
- **Suggest from past (CLI):** `scripts/suggest_from_past.py "issue text"` or `--suggest`.
- **Register DevRev webhook:** `scripts/register_devrev_webhook.py --url https://YOUR-URL/webhooks/devrev`.
- **Test tool connections:** `python3 scripts/test_tools_connection.py` — checks Redash, Querybook, Coralogix (keys in `scripts/.env`). See **docs/TOOLS_SETUP.md**.
