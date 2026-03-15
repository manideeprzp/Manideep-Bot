# Ticket monitor (continuous)

The monitor runs **separately** from the Slack bot. It polls DevRev on a schedule and posts to the **same Slack channel** (and threads) when:

1. **New issues** appear that match your filters (parts, stage, state, unassigned).
2. **Your assigned tickets** get new replies (timeline updates).

Each finding is posted as a message (or thread) with the ticket description and AI suggestion; you can reply **Yes** / **Approve** in the thread like with the interactive bot.

---

## Run continuously

From the project root:

```bash
./run-monitor.sh
```

Or with the installed CLI:

```bash
manideep-bot-monitor run
```

This loops forever: every **interval_minutes** (default 20) it runs one cycle (new tickets + my-ticket updates), then sleeps. Stop with `Ctrl+C`.

**One-off run** (e.g. to test):

```bash
python -m manideep_bot.monitor_cli once
# or
manideep-bot-monitor
```

---

## Enable the monitor

- **Config:** In `config/env.dev.yaml` set `monitor.enabled: true` (you already have this).
- **Env override:** `MONITOR_ENABLED=1` (so you can enable without editing YAML).

---

## Filters (new issues)

Configured under `config/env.dev.yaml` → `monitor.new_ticket_filters`:

| Option | Meaning |
|--------|--------|
| `applies_to_part_names` | Part names (e.g. `"distribution channel and reseller"`) — resolved to part IDs via DevRev API. |
| `applies_to_part` | DevRev part IDs if you prefer IDs over names. |
| `state` | Work states, e.g. `["open", "triaged", "backlog"]`. |
| `stage_names` | Only tickets in these stages (e.g. `["triage"]`). |
| `unassigned_only` | Only tickets with no owner. |

Env overrides (optional):

- `DEVREV_MONITOR_PART_IDS` — comma-separated part IDs.
- `DEVREV_MONITOR_PART_NAMES` — pipe-separated part names.

---

## My tickets (updates)

Under `monitor.my_tickets`:

- **enabled:** `true` — monitor tickets assigned to you.
- **states_to_watch:** DevRev work states to consider (e.g. `["open", "in_progress", "triaged"]`).

The monitor compares the **latest timeline entry ID** per work with the previous run; if it changes, it treats that as a new reply and posts to Slack with the latest update + AI analysis.

---

## Where it posts

- **Slack channel:** Same as the bot — set `slack.bucket_channel_id` in config (or `SLACK_BUCKET_CHANNEL_ID`). Invite the bot to that channel.
- **Fallback:** If the bot token or channel isn’t set, it uses `SLACK_WEBHOOK_URL` (plain message, no thread).

---

## Two processes

| Process | Command | Role |
|--------|---------|------|
| **Slack bot** | `python -m manideep_bot.app` | Responds to @mentions, thread replies (Yes/Approve). |
| **Monitor** | `./run-monitor.sh` or `manideep-bot-monitor run` | Continuously checks DevRev and posts new tickets + my-ticket updates to Slack. |

Run both if you want the interactive bot **and** continuous monitoring. On a server you can run the monitor under systemd. See [ARCHITECTURE.md](ARCHITECTURE.md) for when to use the monitor vs webhook/workflow.

---

## State

The monitor keeps state in `data/monitor_state.json` (last known new-ticket IDs and timeline entry IDs per work) so it only notifies on **new** items. This file is gitignored.
