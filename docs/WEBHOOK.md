# DevRev Webhook (new-issue trigger)

The webhook server receives **work_created** events from DevRev so new issues are processed as soon as they are created, without polling.

## How it works

1. You register your **public URL** with DevRev (e.g. `https://your-server.example.com/webhooks/devrev`).
2. When a new issue is created, DevRev POSTs to that URL with a signed payload.
3. The server verifies the signature, responds within a few seconds (required by DevRev), and enqueues the work ID.
4. A background worker fetches the work, applies the same filters as the monitor (part, stage, unassigned), analyzes it with the agent, and posts to your Slack bucket channel—same flow as the polling monitor, but triggered by the event.

## Setup

### 1. Install dependencies

```bash
pip install fastapi uvicorn
# or: pip install -r requirements.txt
```

### 2. Set the webhook secret

When you create the webhook in DevRev, DevRev returns a **secret**. Set it so the server can verify `X-DevRev-Signature`:

```bash
export DEVREV_WEBHOOK_SECRET=your-secret-from-devrev
```

Or in `config/env.dev.yaml`:

```yaml
devrev:
  webhook_secret: "your-secret-from-devrev"
```

### 3. Expose a public URL

DevRev must reach your endpoint over HTTPS. Options:

- **Deploy** the webhook server on a host with a public URL (e.g. Railway, Fly.io, or your company server). Run `manideep-bot-webhook` (or `uvicorn manideep_bot.webhook_app:create_app() --factory --host 0.0.0.0 --port 8765`) behind a reverse proxy (nginx) with TLS.
- **Local dev:** Use a tunnel (e.g. ngrok, cloudflared) and point it at your local `manideep-bot-webhook` (e.g. `http://localhost:8765`). Register the tunnel URL (e.g. `https://abc123.ngrok.io/webhooks/devrev`) with DevRev.

### 4. Register the webhook in DevRev

Call DevRev’s webhook create API (use your DevRev PAT).

**Option A — Script (recommended):** With your webhook server running at a public URL:

```bash
python3 scripts/register_devrev_webhook.py --url https://YOUR-PUBLIC-URL/webhooks/devrev
```

Then set the printed secret as `DEVREV_WEBHOOK_SECRET` and restart the server.

**Option B — curl:**

```bash
curl -X POST 'https://api.devrev.ai/webhooks.create' \
  -H "Authorization: Bearer $DEVREV_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event_types": ["work_created"],
    "url": "https://your-public-url.example.com/webhooks/devrev"
  }'
```

DevRev will send a **verify** request to your URL. Your server responds with `{"challenge": "<value from payload>"}` (no signature required for verify). After verification, DevRev sends **work_created** events to the same URL.

### 5. Run the webhook server

From the project root:

```bash
export DEVREV_API_KEY=...
export DEVREV_WEBHOOK_SECRET=...
export SLACK_BOT_TOKEN=...
export SLACK_BUCKET_CHANNEL_ID=...
export ANTHROPIC_API_KEY=...

manideep-bot-webhook
# If that command is not found, use (from project root):
#   ./venv/bin/python -m manideep_bot.webhook_cli
# or:  pip install -e .   then run  manideep-bot-webhook
```

Optional env:

- `WEBHOOK_HOST` (default `0.0.0.0`)
- `WEBHOOK_PORT` (default `8765`)

The server starts the **worker thread** automatically. Incoming **work_created** events are queued and processed (fetch work → filter → analyze → post to Slack). The Slack bot (Yes/Approve flow) is unchanged; run `manideep-bot` as usual so you can reply in threads.

## Filters

The webhook worker uses the **same filters** as the monitor: `config/env.dev.yaml` → `monitor.new_ticket_filters` (e.g. `applies_to_part_names`, `stage_names`, `unassigned_only`). Only issues that match these filters are analyzed and posted to Slack.

## Two processes

| Process            | Command               | Role                                                                 |
|--------------------|-----------------------|----------------------------------------------------------------------|
| Slack bot          | `manideep-bot`        | Handles @mentions and thread replies (Yes / Approve).                |
| Webhook server     | `manideep-bot-webhook`| Receives DevRev work_created, analyzes, posts to Slack.              |

You can keep running the **monitor** (`manideep-bot-monitor run`) as a **backup** (e.g. every 30–60 min) in case webhook delivery fails.

## Testing the webhook

1. **Start the server** (with or without `DEVREV_WEBHOOK_SECRET` for the first run). From project root:
   ```bash
   ./venv/bin/python -m manideep_bot.webhook_cli
   ```
   Or after `pip install -e .`: `manideep-bot-webhook`.  
   Expose it (e.g. `ngrok http 8765`) and note the HTTPS URL.

2. **Register:**  
   `python3 scripts/register_devrev_webhook.py --url https://YOUR-NGROK-URL/webhooks/devrev`  
   Copy the printed secret, then `export DEVREV_WEBHOOK_SECRET=...` and restart the webhook server.

3. **Trigger a real event:** In DevRev, create a new issue that matches your filters (part, stage, unassigned). You should see a post in your Slack bucket channel with the ticket and suggestion.

4. **Optional — local verify test:** Without DevRev, you can test that the server echoes the challenge:
   ```bash
   curl -X POST http://localhost:8765/webhooks/devrev \
     -H "Content-Type: application/json" \
     -d '{"type":"verify","verify":{"challenge":"test-challenge-123"}}'
   ```
   Expected response: `{"challenge":"test-challenge-123"}`.

## Security

- The server verifies **X-DevRev-Signature** (HMAC-SHA256 of the raw body with the webhook secret) for all events except `verify`. The `verify` event is accepted without a signature so registration can succeed (you get the secret after creating the webhook).
- Keep `DEVREV_WEBHOOK_SECRET` and other tokens in env or a secure config; do not commit them.
