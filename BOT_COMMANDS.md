# Manideep Bot — Command Reference

## Start / Stop

```bash
# Start bot in background (survives terminal close)
./run_bot.sh daemon

# Start bot in foreground (stops when terminal closes)
./run_bot.sh

# Stop the bot
kill $(cat logs/bot.pid)

# Check if bot is running
ps aux | grep manideep_bot | grep -v grep
```

## Logs

```bash
# Watch live bot logs
tail -f logs/bot.log

# Watch live auto-watcher logs (if running)
tail -f logs/auto_watcher.log

# Check monitor log
tail -f monitor.log
```

## Scheduled Task (Claude Analysis)

- Runs automatically every **10 min, Mon–Fri 10am–6pm IST**
- Managed from the **Scheduled** section in the Cowork sidebar
- To trigger manually → Cowork sidebar → Scheduled → `manideep-bot-check` → **Run now**

## Analysis Queue

```bash
# Check pending tickets waiting for Claude analysis
ls data/claude_requests/

# Check responses written by Claude (before Slack posts them)
ls data/claude_responses/

# Check archived (already processed) tickets
ls data/claude_requests/done/
ls data/claude_responses/done/
```

## Ticket Monitoring

```bash
# Fetch latest unassigned tickets into monitor queue
python3 scripts/fetch_tickets_to_monitor.py --mode unassigned

# Fetch tickets assigned to you
python3 scripts/fetch_tickets_to_monitor.py --mode assigned-to-me
```

## DevRev API (manual)

```bash
# Load env vars first
export $(grep -v '^#' scripts/.env | grep '=' | xargs)

# Fetch a ticket by display ID (replace 1234567 with actual number)
curl -s -X POST https://api.devrev.ai/works.get \
  -H "Authorization: $DEVREV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"id":"don:core:dvrv-in-1:devo/2sRI6Hepzz:issue/1234567"}'
```

## Trigger Analysis from Slack

Just tag the bot in your Slack workspace channel:
```
@Manideep Bot ISS-XXXXXXX
```
Bot replies: ⏳ Queued for Claude analysis — response within 10 min

## Key File Paths

| What | Path |
|------|------|
| Bot config | `scripts/.env` |
| Persona / decision rules | `template/PERSONA.md` |
| Pending analysis requests | `data/claude_requests/` |
| Claude analysis responses | `data/claude_responses/` |
| Solved tickets knowledge base | `data/my_solved_tickets.json` |
| Bot logs | `logs/bot.log` |
| Bot PID | `logs/bot.pid` |
