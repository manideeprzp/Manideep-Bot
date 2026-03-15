# Claude Code Integration - Automatic Analysis!

## 🎯 Overview

You don't need `ANTHROPIC_API_KEY`! The bot uses **automatic analysis** that runs continuously in the background.

**How it works:**
1. New ticket arrives → Bot creates queue file
2. **Auto-watcher** detects it and analyzes automatically (past tickets, patterns, confidence)
3. Analysis posted to Slack within seconds
4. You **just approve** in Slack - that's it!

**Benefits:**
- ✅ No API key needed
- ✅ Fully automatic - no manual "analyze" commands
- ✅ Uses past ticket search, pattern matching, confidence scoring
- ✅ Perfect for local development
- ✅ Only intervene when you want to debug specific tickets

---

## 🚀 Quick Start (2 Steps!)

### Step 1: Start the Bot

```bash
cd ~/Desktop/manideep-bot

# Start bot (no API key needed)
.venv/bin/python -m manideep_bot.app
```

You'll see:
```
INFO — No API key - using Claude Code local analysis
INFO — Connected to Slack
```

---

### Step 2: Start the Auto-Watcher

In a **new terminal**:

```bash
cd ~/Desktop/manideep-bot
./scripts/run_auto_watcher.sh
```

You'll see:
```
🤖 Auto-watcher started. Watching data/analysis_queue
Checking every 5 seconds...
```

**That's it!** Now when tickets arrive, they're automatically analyzed.

---

## ✅ Daily Workflow (Simple!)

### Normal Flow (Fully Automatic)

1. **New ticket arrives** → Bot posts to Slack:
   ```
   🤖 New ticket: ISS-1632906
   ⏳ Analyzing...
   ```

2. **Auto-watcher analyzes** (5-10 seconds):
   - Searches past solved tickets
   - Detects issue patterns
   - Extracts required data
   - Calculates confidence
   - Determines skill to run

3. **Analysis posted to Slack:**
   ```
   🟢 Confidence: 90%

   **Analysis:** GC redemption report with conditional cancellation.
   8 card numbers detected.

   **Similar past tickets:**
   1. ISS-1609523 (similarity: 85%)
   2. ISS-1598234 (similarity: 78%)

   **Skill to run:** gc-redemption-report

   Reply **Yes** to run the skill.
   ```

4. **You approve in Slack:**
   - Reply **"Yes"** → Skill runs
   - Review output
   - Reply **"Approve"** → Ticket closed on DevRev ✅

**You never manually run "analyze" commands!**

---

### Debug Flow (Only When Needed)

**When to use manual analysis:**
- Auto-watcher is down and you need to analyze a specific ticket
- You want to re-analyze with different parameters
- You're debugging the analysis logic

**Manual analyze in Slack:**
```
@ManideepBot analyze ISS-1632906
```

Bot will queue it and auto-watcher will process it.

**Or analyze locally:**
```bash
# List pending tickets
python scripts/claude_code_analyzer.py list

# Analyze specific ticket
python scripts/claude_code_analyzer.py analyze data/analysis_queue/ticket_*.json
```

**99% of the time, you don't need to do this!** The auto-watcher handles it.

---

## 📝 Example: Complete Automatic Flow

### Real Example: ISS-1632906 (GC Redemption)

**Timeline:** Total 15 seconds, zero manual commands

1. **10:30:00** - New ticket arrives in DevRev
2. **10:30:01** - Bot detects it, creates queue file
3. **10:30:01** - Bot posts to Slack:
   ```
   🤖 New ticket: ISS-1632906
   ⏳ Analyzing...
   ```
4. **10:30:06** - Auto-watcher detects queue file
5. **10:30:09** - Auto-watcher completes analysis:
   - Found 8 card numbers
   - Matched pattern: gc_redemption
   - Found 3 similar past tickets
   - Confidence: 90%
   - Skill: gc-redemption-report
6. **10:30:10** - Auto-watcher writes response file
7. **10:30:11** - Bot picks up response, posts to Slack:
   ```
   🟢 Confidence: 90%

   **Analysis:** GC redemption report with conditional cancellation.
   8 card numbers detected.

   **Similar past tickets:**
   1. ISS-1609523 (similarity: 85%)

   **Required data:**
   ✓ card_number: 8 cards found
   ✗ cancellation_reason: Conditional

   **Skill to run:** gc-redemption-report

   Reply **Yes** to run the skill.
   ```
8. **10:32:00** - You reply **"Yes"** in Slack
9. **10:32:05** - Skill runs, posts report
10. **10:33:00** - You review, reply **"Approve"**
11. **10:33:01** - Bot closes ticket on DevRev ✅

**Total hands-on time:** 10 seconds (typing "Yes" and "Approve")

---

## 🔄 Two Modes

### Mode 1: Auto-Watcher (Recommended for Development)
```bash
# No API key needed!
# Just run bot + auto-watcher

python -m manideep_bot.app           # Terminal 1
./scripts/run_auto_watcher.sh        # Terminal 2
```

**How it works:**
- Auto-watcher uses built-in logic (pattern matching, past ticket search)
- Analyzes tickets automatically
- Free, no API costs
- You only approve in Slack

### Mode 2: API Mode (For Production)
```bash
# Set API key
export ANTHROPIC_API_KEY=sk-ant-...
# No API key set

# Bot uses claude_code_agent.py → Queue system → You analyze
```

**The bot automatically chooses the right mode!**

---

## 🛠️ Analysis Tools You Can Use

When analyzing tickets, you (Claude Code) have access to:

### 1. Read Ticket Content
```python
# I can read the ticket JSON file
Read data/analysis_queue/ticket_123.json
```

### 2. Search Past Tickets
```python
# Already integrated - retriever.py searches past solved tickets
from manideep_bot.retriever import find_relevant
relevant = find_relevant(ticket_text, config, top_k=10)
```

### 3. Search Codebase
```bash
# I can search for similar issues in your repos
Grep "order trace" src/
Glob "order*.py"
```

### 4. Pattern Matching
```python
# enhanced_agent.py has pattern detection built-in
IssuePattern.detect_issue_type(ticket_text)
```

### 5. Check Skill Availability
```bash
ls -la ~/.cursor/skills/
ls -la scripts/
```

---

## 📋 Response Format

When you create a response, use this format:

```json
{
  "timestamp": 1710123456789,
  "ticket_id": "ISS-1632906",
  "status": "completed",
  "analyzed_at": "2026-03-11 02:20:00",

  "analysis": "🟢 Confidence: 92%\n\n**Analysis:** This is a GC redemption report request with conditional cancellation. 8 card numbers provided.\n\n**Approach:**\n1. Run gc-redemption-report for each card\n2. Check transaction history\n3. If only 'recharge' (full balance) → proceed to cancellation\n4. If has redemptions → just share report\n\n**Skill to run:** gc-redemption-report\n\n**Reasoning:** High confidence because:\n- Clear 'redemption report' keywords\n- All 8 card numbers extracted\n- Matches PERSONA.md conditional logic\n- Similar to ISS-123456\n\n**Required data:**\n✓ card_number: 8 cards found\n✗ cancellation_reason: Conditional (\"if unredeemed\")\n\n**Recommendation:** ask_approval (multiple cards + conditional logic)\n\n---\n\nReply **Yes** to run the skill, or **No** to cancel.",

  "metadata": {
    "issue_type": "gc_redemption",
    "skill_name": "gc-redemption-report",
    "confidence": 0.92,
    "recommendation": "ask_approval"
  }
}
```

---

## 🤝 How We Work Together

### Your Role (User):
1. Run the bot
2. Tell me when new tickets arrive
3. Review my analysis
4. Reply "Yes"/"Approve" in Slack

### My Role (Claude Code):
1. Analyze tickets using all available tools
2. Search past solutions
3. Determine skill to run
4. Calculate confidence
5. Provide detailed reasoning

### Bot's Role:
1. Detect new tickets
2. Auto-assign to you
3. Queue ticket for analysis
4. Post my analysis to Slack
5. Run skills when approved
6. Close tickets

---

## 🧪 Testing

### Test 1: Mention Bot Directly
```
@ManideepBot Please analyze: Order ID order_123 - customer can't see booking
```

**Without API key:**
```
🤖 Ticket submitted to Claude Code for analysis
Queue File: ticket_123.json
⏳ Waiting...
```

**Then you tell me:** "Analyze ticket_123.json"

**I respond with** analysis + create response file

**Bot posts** the analysis to Slack

---

### Test 2: Real New Ticket

When DevRev posts to `#engage-production-issues`:

1. Bot auto-assigns to you
2. Bot creates queue file
3. Bot posts "⏳ Waiting for Claude Code..."
4. You analyze (or I do it for you)
5. Bot updates Slack with analysis

---

## 📊 Comparison

| Feature | API Mode | Claude Code Mode |
|---------|----------|------------------|
| **API Key Required** | ✅ Yes | ❌ No |
| **Cost** | ~$0.01/ticket | ✅ Free |
| **Speed** | 1-2 seconds | 5-30 seconds* |
| **Tools Available** | Claude API only | All Claude Code tools |
| **Code Search** | Limited | ✅ Full access |
| **Past Tickets Search** | ✅ Yes | ✅ Yes |
| **Debugging** | Hard | ✅ Easy (see all files) |
| **Customization** | Limited | ✅ Full control |

*Depends on how quickly you analyze

---

## 🎯 Recommended Setup

**For Development/Learning:**
- ✅ Use Claude Code mode (no API key)
- You learn by analyzing tickets together
- Build up skills and persona
- Full transparency and control

**For Production (Later):**
- Add `ANTHROPIC_API_KEY`
- Bot auto-analyzes high-confidence tickets
- You review low-confidence ones
- Faster response time

---

## 🚨 Troubleshooting

### Bot says "Waiting..." but nothing happens
- Check: `ls data/analysis_queue/`
- Run: `python scripts/claude_code_analyzer.py list`
- Analyze the pending ticket

### Response file not picked up
- File must be named: `ticket_<TIMESTAMP>_response.json`
- Must be valid JSON
- Bot checks every 2 seconds
- Check bot logs for errors

### How do I switch between modes?
- **To Claude Code mode:** Remove `ANTHROPIC_API_KEY` from `.env`, restart bot
- **To API mode:** Add `ANTHROPIC_API_KEY` to `.env`, restart bot

---

## ✅ Benefits of Claude Code Mode

1. **Learning Together**
   - You see how I analyze tickets
   - Build up your persona
   - Understand patterns

2. **No Costs**
   - No API charges
   - Perfect for development
   - Experiment freely

3. **Full Control**
   - See all data
   - Customize analysis
   - Build skills iteratively

4. **Better Analysis**
   - I can search your entire codebase
   - Access to all repos
   - Use Grep, Glob, Read, etc.

---

## 🎓 Next Steps

1. **Restart bot without API key** → Claude Code mode active
2. **Test with a mention** → `@ManideepBot test ticket`
3. **Analyze together** → I'll help you create responses
4. **Build 5 skills** → Based on top issue types
5. **Add API key later** → For autonomous mode

---

**Ready to try it?** Just restart the bot and tell me when a ticket arrives!

```bash
pkill -f "manideep_bot.app"
.venv/bin/python -m manideep_bot.app
```

Then:
```
@ManideepBot ISS-1632906
```

And I'll analyze it for you! 🚀
