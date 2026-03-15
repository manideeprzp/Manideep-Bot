# Use DevRev Workflow to notify your channel (no webhook / no ngrok)

If your company already gets DevRev "new issue" notifications in Slack (e.g. in `#engage-production-issues`), you can get the same into **your** channel and let the bot react there. No webhook server, no ngrok, no VPN issues.

## Is there an API to create the workflow?

**No.** DevRev does not expose a public REST API to create or edit workflow definitions (e.g. "trigger: work_created → action: post to Slack"). Workflows are created and managed in the **DevRev UI** (or via a **snap-in** if you build one with the DevRev SDK). So you need to create the "new issue → post to Slack" workflow **in the UI** (see below). Once it exists, your bot will react to the messages it posts.

## How it works

1. **DevRev Workflow (or Slack integration)** runs when a work item is created and **posts a message to your Slack channel** (e.g. `#pse-tickets`). The message should contain the issue identifier (e.g. `ISSUE-123` or a DevRev link).
2. **Manideep Bot** is in that channel. When it sees a **new top-level message** that contains an issue ref (`ISSUE-XXX` or `devrev.ai/...`), it:
   - Fetches the work from DevRev (by display_id),
   - Runs the usual analysis (past tickets + skill suggestion),
   - **Replies in a thread** with the suggestion and "Reply **Yes** to run the skill, then **Approve** to close."
3. You reply **Yes** / **Approve** in that thread as usual.

## Setup

### 1. Create or use a channel

Create a channel (e.g. `#pse-tickets`) and **invite the Manideep Bot** to it. Set `SLACK_BUCKET_CHANNEL_ID` (or `slack.bucket_channel_id` in config) to that channel’s ID.

### 2. Configure DevRev to post new issues to that channel

Use one of these:

- **DevRev Workflow**  
  In DevRev, create a workflow (or use an existing one):
  - **Trigger:** Work / Issue created (or equivalent).
  - **Action:** Post to Slack → choose your channel (`#pse-tickets`).  
  Ensure the message includes the issue id (e.g. `ISSUE-123`) or a link to the issue so the bot can parse it.

- **DevRev ↔ Slack integration**  
  If DevRev has an integration that posts new issues to Slack, add your channel to the list of channels that receive those notifications (or create a similar rule that posts to your channel).

- **Slack workflow / Zapier**  
  If new-issue notifications already go to another channel, you could add a Slack workflow or Zapier step that copies (or forwards) those messages to your channel, as long as the text still contains the issue id or link.

### 3. Run the bot

Run only the Slack app (no webhook server):

```bash
./venv/bin/python -m manideep_bot.app
```

When a new-issue message appears in your channel (from the workflow or integration), the bot will reply in a thread with the analysis and Yes/Approve flow.

## Requirements

- The notification message in Slack must contain something the bot can parse as an issue ref: e.g. `ISSUE-123`, `TICKET-456`, or a `devrev.ai` link.
- The issue must be recent enough and in a state that DevRev’s `works.list` returns (e.g. open, triaged, backlog). The bot resolves `ISSUE-123` by listing recent works and matching `display_id`.

## Summary

| Approach              | Trigger                    | Needs public URL? |
|-----------------------|----------------------------|--------------------|
| Webhook               | DevRev POSTs to your server| Yes (ngrok/deploy) |
| **Workflow → Slack**  | Message in your channel    | No                 |

Using the **Workflow** (or equivalent) to post into your channel avoids webhooks and works behind VPN.
