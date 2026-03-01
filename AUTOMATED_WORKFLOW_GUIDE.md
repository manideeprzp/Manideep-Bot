# Manideep Bot - Fully Automated Workflow Guide

## 🎯 Your Goal: Validate, Not Work

Your bot now handles **everything automatically**:
1. ✅ Monitors new unassigned tickets in PSE pod
2. ✅ Monitors updates on your assigned tickets
3. ✅ Analyzes issues and suggests solutions
4. ✅ Runs skills when you approve
5. ✅ Posts resolutions to DevRev and closes tickets

**Your job:** Just validate and approve!

---

## 🔄 Workflow 1: New Unassigned Tickets (PSE Pod)

### What the Bot Does Automatically

#### 1. **Monitors PSE Pod**
The bot watches for new tickets in:
- **Parts:** "Distribution channel and reseller", "Wallet as service", "Issuance"
- **Stage:** "Triage"
- **Owner:** Unassigned only

Configured in [config/env.dev.yaml](config/env.dev.yaml):
```yaml
monitor:
  enabled: true
  interval_minutes: 20  # Checks every 20 minutes
  new_ticket_filters:
    applies_to_part_names:
      - "distribution channel and reseller"
      - "issuance"
      - "wallet as service"
    stage_names: ["triage"]
    unassigned_only: true
```

#### 2. **Auto-Analyzes New Tickets**
When a new ticket appears, the bot:
- Reads the title and description
- Searches your past solved tickets for similar issues
- Uses AI (with optimizations from Phase 1) to suggest solution
- Identifies which skill to run

#### 3. **Posts to Slack Thread**
The bot posts an interactive message in your bucket channel:

```
🆕 **New PSE Ticket (Triage, unassigned)**
**ISS-123456** — Customer can't redeem GC

**Analysis:** Gift card redemption issue for customer. Similar to past ticket ISS-98765 (gc validation fix).

**Approach:**
1. Check GC code format and validity
2. Verify redemption service logs
3. Check balance/expiry date

**Skill to run:** gc-redemption-report
**Confidence:** high

—Reply **Yes** to run the skill, then **Approve** to post resolution and close ticket.
```

#### 4. **You Reply "Yes"**
The bot:
- ✅ Extracts required parameters (e.g., order_id from ticket)
- ✅ Runs the skill script
- ✅ Captures output
- ✅ Posts result in the SAME thread:

```
Work done. Output:
```
GC Code: ABC123XYZ
Status: Valid
Balance: $50.00
Expiry: 2026-12-31
Issue: Redemption service timeout
Recommendation: Retry redemption or escalate to dev
```

Review. If correct, reply **Approve** to post this on the ticket and close it.
```

#### 5. **You Verify & Reply "Approve"**
The bot:
- ✅ Posts the resolution as a comment on the DevRev ticket
- ✅ Changes ticket stage to "Closed"
- ✅ Confirms in Slack thread: "Posted update and set stage to **Closed**. Done."

---

## 🔄 Workflow 2: Updates on Assigned Tickets

### What the Bot Does Automatically

#### 1. **Monitors Your Assigned Tickets**
The bot watches tickets assigned to you in states:
- **States:** "open", "in_progress", "triaged"

#### 2. **Detects New Replies/Updates**
When someone adds a comment or update to your ticket, the bot:
- ✅ Detects the new timeline entry
- ✅ Fetches the NEW content (what was just added)
- ✅ Analyzes it with AI

**Example scenarios:**
- **"Awaiting info from reporter"** → Reporter provides the missing details
- **"Escalated to dev"** → Dev team responds with findings or fix

#### 3. **Analyzes the Update**
The bot:
- Reads the latest reply content
- Combines it with ticket context (title, stage)
- Finds similar past resolved issues
- Suggests next steps and skill to run

#### 4. **Posts to Slack Thread**
```
📝 **Assigned Ticket Update**
**ISS-789012** — Booking visibility issue (Stage: Awaiting info from reporter)

**Latest update:**
Customer provided order ID: order_xyz123. Error: "Order not found in customer view"

**AI Analysis:**
Order visibility issue for order_xyz123. Similar to ISS-45678 (customer mapping bug).

**Approach:**
1. Run order trace to check state
2. Verify customer-to-order mapping
3. Check visibility flags

**Skill to run:** order-trace-debugger
**Confidence:** high

—Reply **Yes** to run the skill, then **Approve** to post resolution.
```

#### 5. **Same Approval Flow**
- **You reply "Yes"** → Bot runs skill, posts output
- **You verify & reply "Approve"** → Bot posts resolution and updates DevRev

---

## ⚙️ Setup Instructions

### 1. Configure Monitor Settings

Your [config/env.dev.yaml](config/env.dev.yaml) is already configured:

```yaml
monitor:
  enabled: true  # ✅ Monitor is enabled
  interval_minutes: 20  # Check every 20 minutes

  # New unassigned tickets in PSE pod
  new_ticket_filters:
    applies_to_part_names:
      - "distribution channel and reseller"
      - "issuance"
      - "wallet as service"
    state: ["open", "triaged", "backlog"]
    stage_names: ["triage"]  # Only Triage stage
    unassigned_only: true  # Only unassigned tickets

  # Your assigned tickets
  my_tickets:
    enabled: true
    states_to_watch: ["open", "in_progress", "triaged"]
    awaiting_info_stage_names: ["Awaiting info from reporter", "Awaiting Customer"]
```

### 2. Set Slack Bucket Channel

In [scripts/.env](scripts/.env), add:

```bash
SLACK_BUCKET_CHANNEL_ID=C01234567  # Your Slack channel ID
```

**How to get channel ID:**
1. Right-click your Slack channel
2. Click "View channel details"
3. Scroll down - Channel ID is at the bottom

### 3. Start the Monitor

```bash
cd /Users/karalapati.manideep/Desktop/manideep-bot
manideep-bot-monitor
```

Or run in loop mode (continuous monitoring):
```bash
# In scripts/monitor_loop.sh or manually:
python -m manideep_bot.monitor_cli loop
```

---

## 🚀 Running the Complete System

### Option 1: Run Both (Recommended)

**Terminal 1 - Slack Bot (for thread interactions):**
```bash
manideep-bot
```

**Terminal 2 - Monitor (for proactive detection):**
```bash
manideep-bot-monitor loop
```

### Option 2: Systemd Service (Production)

Create `/etc/systemd/system/manideep-bot.service`:

```ini
[Unit]
Description=Manideep Bot Slack Socket Mode
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/Users/karalapati.manideep/Desktop/manideep-bot
ExecStart=/usr/bin/python3 -m manideep_bot.app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

And `/etc/systemd/system/manideep-monitor.service`:

```ini
[Unit]
Description=Manideep Bot Monitor
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/Users/karalapati.manideep/Desktop/manideep-bot
ExecStart=/usr/bin/python3 -m manideep_bot.monitor_cli loop
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable manideep-bot
sudo systemctl enable manideep-monitor
sudo systemctl start manideep-bot manideep-monitor
```

---

## 📊 What Gets Automated

| Step | Manual (Before) | Automated (Now) |
|------|----------------|-----------------|
| **Find new tickets** | Check DevRev manually | ✅ Bot monitors every 20 min |
| **Analyze issue** | Read ticket, search past cases | ✅ Bot uses AI + retrieval |
| **Suggest solution** | Think through approach | ✅ Bot suggests with confidence level |
| **Run diagnostics** | Copy order ID, run script | ✅ Bot extracts ID and runs skill |
| **Post resolution** | Copy output, paste to DevRev | ✅ Bot posts after your approval |
| **Close ticket** | Manually change stage | ✅ Bot sets to "Closed" |
| **Check assigned tickets** | Monitor DevRev for updates | ✅ Bot detects new replies |
| **Analyze updates** | Read new comments | ✅ Bot analyzes and suggests next steps |

**Your job:** Just reply "Yes" → verify → "Approve"

---

## 🔧 Troubleshooting

### Monitor Not Posting to Slack

**Check:**
1. `SLACK_BOT_TOKEN` is set in `scripts/.env`
2. `SLACK_BUCKET_CHANNEL_ID` is set
3. Bot is invited to the channel
4. Monitor is running: `ps aux | grep monitor`

**Test manually:**
```bash
python -m manideep_bot.monitor_cli once
```

### Bot Not Responding in Threads

**Check:**
1. Slack bot (`manideep-bot`) is running
2. Bot has Socket Mode enabled
3. Reply in the thread, not main channel

### Skills Not Running

**Check:**
1. Skill scripts exist in `scripts/` folder
2. Skills are executable: `chmod +x scripts/*.py`
3. Required dependencies installed
4. Check logs for error messages

---

## 📝 Example Complete Flow

### Scenario: New GC Redemption Issue

#### 11:00 AM - Bot Detects New Ticket
```
Monitor run: Found 1 new PSE ticket
Posted to Slack: ISS-567890
```

#### 11:01 AM - Slack Notification
You receive in `#manideep-bot-queue`:

```
🆕 New PSE Ticket (Triage, unassigned)
ISS-567890 — GC redemption failing with error: invalid_code

Analysis: Gift card validation error. Matches ISS-234567 (gc code format).
Approach: 1. Check GC code 2. Verify logs 3. Check balance/expiry
Skill to run: gc-redemption-report
Confidence: high

—Reply **Yes** to run the skill, then **Approve** to post resolution and close ticket.
```

#### 11:05 AM - You Reply "Yes"
Bot responds in thread:

```
Work done. Output:
```
GC Code: ABCD1234
Format: Valid
Balance: $100.00
Expiry: 2027-01-15
Issue: Redemption service returned 500 error
Root cause: Service timeout
Recommendation: Retry redemption after 5 minutes or escalate
```

Review. If correct, reply **Approve** to post this on the ticket and close it.
```

#### 11:07 AM - You Reply "Approve"
Bot responds:

```
Posted update on ticket and set stage to **Closed**. Done.
```

**On DevRev ticket ISS-567890:**
```
Resolution:
GC Code: ABCD1234
Format: Valid
Balance: $100.00
Issue: Service timeout
Recommendation: Retry after 5 minutes

[Stage changed to: Closed]
```

**Total time:** 7 minutes (vs 30+ minutes manually)
**Your effort:** 2 approvals

---

## 🎯 Key Benefits

### Time Savings
- **Before:** 30-60 min per ticket (search, analyze, test, resolve, document)
- **After:** 2-5 min (validate + approve)
- **Savings:** ~90% time reduction

### Consistency
- ✅ Always checks past similar tickets
- ✅ Follows proven solutions
- ✅ Documents resolutions uniformly

### Coverage
- ✅ Never miss new unassigned tickets
- ✅ Never miss updates on your tickets
- ✅ Works 24/7, even when you're offline

### Quality
- ✅ Retrieval finds best similar cases
- ✅ AI provides confident suggestions
- ✅ You validate before posting

---

## 🔐 Security Notes

### What the Bot CAN Do (When You Approve)
- ✅ Read DevRev tickets
- ✅ Run diagnostic skills (read-only analysis)
- ✅ Post comments on tickets (after your approval)
- ✅ Change ticket stage to "Closed" (after your approval)

### What the Bot CANNOT Do
- ❌ Post without your approval
- ❌ Delete or modify existing data
- ❌ Access customer PII without permission
- ❌ Make code changes
- ❌ Deploy to production

### Approval Gates
- **"Yes"** → Run diagnostic skill (read-only)
- **"Approve"** → Post to DevRev and close (write operation)

You control every write operation!

---

## 📈 Monitoring & Logs

### Check Monitor Status
```bash
# See recent runs
tail -f /path/to/logs/monitor.log

# Check state
cat data/monitor_state.json | python3 -m json.tool
```

### Monitor Metrics
- **New tickets detected:** Logged every run
- **Assigned ticket updates:** Logged with ticket IDs
- **AI analysis success rate:** Check logs for errors
- **Skill execution success:** Logged per skill run

---

## 🚀 Next Steps

1. **Start the system:**
   ```bash
   # Terminal 1
   manideep-bot

   # Terminal 2
   manideep-bot-monitor loop
   ```

2. **Test with a ticket:**
   - Wait for bot to detect a new ticket OR
   - Manually trigger: `python -m manideep_bot.monitor_cli once`

3. **Validate the workflow:**
   - Check Slack for bot message
   - Reply "Yes" → verify skill output
   - Reply "Approve" → check DevRev ticket updated

4. **Let it run!**
   - Bot works 24/7
   - You just validate and approve
   - Enjoy your newfound free time! 🎉

---

## ❓ FAQ

**Q: What if the bot suggests the wrong skill?**
A: Don't reply "Yes". Instead, @mention the bot with more context and it will re-analyze.

**Q: What if the skill fails to run?**
A: Bot will ask for missing information (e.g., order_id). Provide it and reply "Yes" again.

**Q: Can I customize which tickets the bot monitors?**
A: Yes! Edit `config/env.dev.yaml` → `monitor.new_ticket_filters` to change parts, stages, or states.

**Q: What if I want to handle a ticket manually?**
A: Just don't reply to the bot's message. The ticket stays in Triage for you to handle.

**Q: Can I review what the bot will post before it posts?**
A: Yes! The bot shows you the output after "Yes". Only reply "Approve" if it looks good.

---

**Your bot is now your AI assistant that works 24/7!** 🤖✨
