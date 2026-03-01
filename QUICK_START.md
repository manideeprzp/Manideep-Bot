# Manideep Bot - Quick Start Guide

## 🚀 Start Your Automated Bot in 3 Steps

### Step 1: Set Your Slack Channel

Edit `scripts/.env` and add:

```bash
# Get this from Slack: Right-click channel → View details → Channel ID at bottom
SLACK_BUCKET_CHANNEL_ID=C01234567
```

### Step 2: Start the System

Open **two terminals**:

**Terminal 1 - Slack Bot (handles thread interactions):**
```bash
cd /Users/karalapati.manideep/Desktop/manideep-bot
manideep-bot
```

**Terminal 2 - Monitor (detects tickets & updates):**
```bash
cd /Users/karalapati.manideep/Desktop/manideep-bot
manideep-bot-monitor loop
```

### Step 3: Test It!

**Manual test:**
```bash
python -m manideep_bot.monitor_cli once
```

Then check your Slack bucket channel for bot messages!

---

## ✅ What the Bot Does Automatically

### Every 20 Minutes:

1. **Checks for new unassigned PSE tickets** (Triage stage)
2. **Checks your assigned tickets** for new comments/updates
3. **Analyzes each** with AI + past solved tickets
4. **Posts to Slack** with skill suggestion

### When You Reply:

- **"Yes"** → Bot runs the skill, shows output
- **"Approve"** → Bot posts resolution to DevRev & closes ticket

---

## 📍 Configuration Reference

Your bot is configured in [config/env.dev.yaml](config/env.dev.yaml):

```yaml
monitor:
  enabled: true  # ✅ Monitor is ON
  interval_minutes: 20  # Checks every 20 min

  # New tickets (PSE pod, unassigned, Triage)
  new_ticket_filters:
    applies_to_part_names:
      - "distribution channel and reseller"
      - "issuance"
      - "wallet as service"
    stage_names: ["triage"]
    unassigned_only: true

  # Your assigned tickets (updates)
  my_tickets:
    enabled: true
    states_to_watch: ["open", "in_progress", "triaged"]
```

---

## 🔧 Troubleshooting

### Bot not posting to Slack?

```bash
# Check if variables are set:
grep SLACK scripts/.env

# Test monitor manually:
python -m manideep_bot.monitor_cli once
```

### Bot not responding to "Yes"/"Approve"?

- Make sure **Terminal 1** (manideep-bot) is running
- Reply in the **thread**, not main channel
- Use exact words: "Yes", "Approve"

### Want to change which tickets to monitor?

Edit `config/env.dev.yaml` → `monitor.new_ticket_filters`

---

## 📊 Expected Behavior

### First Run (Cold Start):
```
Monitor run: Found 0 new PSE tickets
Monitor run: Found 0 assigned ticket updates
```

### When New Ticket Detected:
```
Monitor run: Found 1 new PSE ticket
Posted to Slack: ISS-123456
```

### In Slack:
```
🆕 New PSE Ticket (Triage, unassigned)
ISS-123456 — Customer issue title

Analysis: ...
Approach: ...
Skill to run: order-trace-debugger
Confidence: high

—Reply **Yes** to run the skill, then **Approve** to post resolution and close ticket.
```

---

## 📚 Full Documentation

- **[AUTOMATED_WORKFLOW_GUIDE.md](AUTOMATED_WORKFLOW_GUIDE.md)** - Complete workflow guide
- **[OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md)** - Technical optimizations
- **[README.md](README.md)** - Project overview

---

## 🎯 Your Role

| Bot Does (90%) | You Do (10%) |
|----------------|--------------|
| Monitors tickets | Validate suggestions |
| Analyzes issues | Reply "Yes" |
| Runs diagnostics | Review output |
| Posts resolutions | Reply "Approve" |
| Closes tickets | ✅ Done! |

**That's it!** Let the bot work while you validate. 🎉
