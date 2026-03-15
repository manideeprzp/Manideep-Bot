# Getting Started - Quick Setup Guide

This guide walks you through setting up the bot from scratch. Choose your path based on whether you want to use Claude Code (recommended for development) or API mode (for production).

---

## 🎯 Quick Decision: Which Mode?

| Mode | Best For | API Key Required | Cost |
|------|----------|------------------|------|
| **Claude Code** | Development, learning, building skills | ❌ No | Free |
| **API Mode** | Production, autonomous operation | ✅ Yes | ~$0.01/ticket |

**Recommendation:** Start with Claude Code mode to learn the system, then add API key later.

---

## 📋 Prerequisites

1. **Python 3.11+** installed
2. **DevRev account** with access to your workspace
3. **Slack workspace** where you can create apps

---

## 🚀 Setup (30 minutes)

### Step 1: Clone and Install (5 min)

```bash
cd ~/Desktop
git clone <your-repo> manideep-bot
cd manideep-bot

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Step 2: Configure DevRev (5 min)

1. Go to DevRev → Settings → API Keys
2. Create a new API key with permissions:
   - Read works
   - Create/update timeline entries
   - Update work stage
3. Copy the key

```bash
cd scripts
cp .env.example .env
nano .env  # or your favorite editor
```

Add to `.env`:
```bash
DEVREV_API_KEY=your-devrev-api-key-here
```

### Step 3: Fetch Your Solved Tickets (5 min)

```bash
# From scripts/ directory
python3 fetch_my_solved.py
```

This creates:
- `data/my_solved_tickets.json` - Your past solved tickets
- Used for finding similar issues

### Step 4: Set Up Slack App (10 min)

1. Go to https://api.slack.com/apps
2. Click **Create New App** → **From scratch**
3. Name it "Manideep Bot" (or your name), select your workspace

**OAuth & Permissions:**
- Add Bot Token Scopes:
  - `app_mentions:read`
  - `chat:write`
  - `channels:history`
  - `channels:read`
  - `groups:history`
  - `im:history`
- Install to workspace
- Copy **Bot User OAuth Token** (starts with `xoxb-`)

**Socket Mode:**
- Enable Socket Mode
- Create App-Level Token with `connections:write` scope
- Copy **App-Level Token** (starts with `xapp-`)

**Event Subscriptions:**
- Subscribe to bot events:
  - `app_mention`
  - `message.channels`
  - `message.groups`
  - `message.im`

**Invite bot to channel:**
- Create or use existing channel (e.g., `#bot-testing`)
- Type `/invite @Manideep Bot`
- Copy the channel ID (right-click channel → View channel details)

### Step 5: Configure Environment (5 min)

Create `config/env.dev.yaml` or set environment variables:

```yaml
slack:
  bot_token: "xoxb-your-bot-token"
  app_token: "xapp-your-app-token"
  bucket_channel_id: "C01234567"  # Your channel ID

devrev:
  api_key: "your-devrev-key"
  base_url: "https://api.devrev.ai"

retriever:
  use_bm25: true
  top_k: 10

# Optional - only needed for API mode
anthropic:
  api_key: ""  # Leave empty for Claude Code mode
```

Or use environment variables:
```bash
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export SLACK_BUCKET_CHANNEL_ID=C01234567
export DEVREV_API_KEY=your-key
```

---

## ✅ Test the Setup

### Test 1: Run the Bot

**Terminal 1:**
```bash
cd ~/Desktop/manideep-bot
source .venv/bin/activate
python -m manideep_bot.app
```

You should see:
```
INFO — Manideep Bot starting...
INFO — No API key - using Claude Code local analysis
INFO — Connected to Slack
INFO — Listening for messages in channel C01234567
```

**Terminal 2 (Auto-Watcher):**
```bash
cd ~/Desktop/manideep-bot
source .venv/bin/activate
./scripts/run_auto_watcher.sh
```

You should see:
```
🤖 Auto-watcher started. Watching data/analysis_queue
Checking every 5 seconds...
```

### Test 2: Send a Test Message

In your Slack channel:
```
@Manideep Bot test order ID 12345
```

**Within 10 seconds, you'll see:**
```
🟢 Confidence: 65%

**Analysis:** Order trace issue detected.

**Skill to run:** order-trace

Reply **Yes** to run the skill.
```

**That's it!** No manual "analyze" commands needed

---

## 🔄 Daily Workflow

### Automatic Mode (Recommended for Development)

**One-time setup each day:**
```bash
# Terminal 1: Bot
python -m manideep_bot.app

# Terminal 2: Auto-watcher
./scripts/run_auto_watcher.sh
```

**Then just work in Slack:**

1. **New ticket arrives** → Auto-watcher analyzes it (5-10 seconds)
2. **Analysis posted to Slack** with confidence, similar tickets, skill name
3. **You reply "Yes"** → Skill runs
4. **You reply "Approve"** → Ticket closed ✅

**No manual analysis commands needed!**

See [CLAUDE_CODE_INTEGRATION.md](CLAUDE_CODE_INTEGRATION.md) for detailed workflow.

### API Mode (For Production)

1. **Add API key:**
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

2. **Run the bot:**
   ```bash
   python -m manideep_bot.app
   ```

3. **Automatic analysis:**
   - New ticket → bot analyzes automatically
   - Posts suggestion to Slack
   - You approve with "Yes" / "Approve"

---

## 📁 Repository Structure

```
manideep-bot/
├── README.md              # Main overview
├── docs/
│   ├── GETTING_STARTED.md           # This file
│   ├── CLAUDE_CODE_INTEGRATION.md   # Claude Code workflow
│   ├── ARCHITECTURE.md              # System design
│   ├── APIS_NEEDED.md               # API requirements
│   └── ...
├── src/manideep_bot/      # Source code
│   ├── app.py            # Main Slack bot
│   ├── agent.py          # Analysis logic
│   ├── retriever.py      # Past ticket search
│   ├── devrev_client.py  # DevRev API
│   └── ...
├── scripts/              # Helper scripts
│   ├── fetch_my_solved.py
│   ├── claude_code_analyzer.py
│   └── .env             # Your secrets (gitignored)
├── config/
│   └── env.dev.yaml     # Configuration
├── template/
│   ├── PERSONA.md       # How the bot thinks
│   └── SAFETY.md        # Safety guidelines
├── data/                # Generated data (gitignored)
│   ├── my_solved_tickets.json
│   └── analysis_queue/
└── requirements.txt
```

---

## 🎓 Next Steps

1. **Read the key docs:**
   - [ARCHITECTURE.md](ARCHITECTURE.md) - How everything fits together
   - [CLAUDE_CODE_INTEGRATION.md](CLAUDE_CODE_INTEGRATION.md) - Detailed Claude Code workflow
   - [SKILL_BUILDING_GUIDE.md](SKILL_BUILDING_GUIDE.md) - Build custom skills

2. **Test with real tickets:**
   - Paste a DevRev ticket in Slack
   - Practice the Yes/Approve workflow
   - Build 3-5 common skills

3. **Optional: Add webhook for real-time:**
   - See [WEBHOOK.md](WEBHOOK.md) for DevRev webhook setup
   - Or [DEVREV_WORKFLOW_SLACK.md](DEVREV_WORKFLOW_SLACK.md) for workflow approach

4. **Production ready:**
   - Add `ANTHROPIC_API_KEY` for autonomous mode
   - Set up monitoring
   - Deploy to server

---

## 🔧 Troubleshooting

### Bot doesn't respond
- Check bot is running: `ps aux | grep manideep_bot`
- Check Slack token is valid
- Check bot is invited to channel
- Check logs for errors

### No past tickets found
- Run `python scripts/fetch_my_solved.py` again
- Check `data/my_solved_tickets.json` exists
- Verify DevRev API key has permissions

### Analysis queue stuck
- Check `data/analysis_queue/` directory
- Run `python scripts/claude_code_analyzer.py list`
- Ensure response files are valid JSON

---

## 📞 Help

- **Documentation:** See `docs/` folder
- **Issues:** Check existing docs or ask in Slack
- **Architecture questions:** Read [ARCHITECTURE.md](ARCHITECTURE.md)

---

**Ready to start?** Run the bot and try your first ticket! 🚀
