# Daily tools setup (Redash, Coralogix, Querybook, GWS)

So the bot (and its skills) can use your daily tools: **Redash**, **Coralogix**, **Querybook**, and **GWS** (Google Docs/Sheets). Set these up once; skills and MCP will use them.

---

## 1. Redash

**Used for:** Running queries (e.g. gift card data, transactions). The **gc-redemption-report** skill uses Redash to fetch card and transaction data.

**What you need:**
- **Redash base URL** (e.g. `https://redash.yourcompany.com`)
- **Redash API key** (from Redash: your profile → API Key, or Settings → Data Sources → your user API key)

**Where to set:**
- **Option A (skill config):** Edit `~/.cursor/skills/gc-redemption-report/scripts/config.json`:
  - `redash_base_url`: your Redash URL
  - `redash_api_key`: your API key
- **Option B (env):** In `scripts/.env` add:
  - `REDASH_BASE_URL=https://redash.yourcompany.com`
  - `REDASH_API_KEY=your-api-key`
  (Skills that support env override will use these.)

---

## 2. Coralogix

**Used for:** Querying logs (Dataprime). Available as **MCP** in Cursor (e.g. `get_logs`, `get_traces`). When the bot or a skill needs to search logs, it uses the Coralogix MCP server.

**What you need:**
- Coralogix API URL / endpoint
- Coralogix API key or token (from Coralogix: Settings → API Keys or similar)

**Where to set:**
- In `scripts/.env` we set per-instance URL and key (e.g. `CORALOGIX_POSHVINE_URL`, `CORALOGIX_POSHVINE_API_KEY`, and same for Wallet). For **query API** calls, the India region uses **`https://api.ap1.coralogix.com`** (not the app URL). Run `python3 scripts/test_tools_connection.py` to verify.
- Configure your **Coralogix MCP server** (Cursor MCP settings) with the same keys so Cursor can query logs via MCP.

---

## 3. Querybook

**Used for:** Running Querybook queries (SQL/data). For skills or scripts that need to run Querybook queries programmatically.

**What you need:**
- **Querybook base URL** (e.g. `https://querybook.yourcompany.com`)
- **API access token:** In Querybook → profile (bottom left) → **API Access Token** → Create a Token; copy it once (it’s shown only once).

**Where to set:**
- In `scripts/.env`:
  - `QUERYBOOK_BASE_URL=https://querybook.yourcompany.com`
  - `QUERYBOOK_API_TOKEN=your-token`
- API requests use header: `api-access-token: <your-token>`.

(When we add a Querybook skill or script, it will read these.)

---

## 4. GWS (Google Docs & Sheets)

**Used for:** Writing reports to Google Sheets, creating/editing Google Docs. The **gc-redemption-report** skill writes redemption reports to a Google Sheet. GWS MCP lets Cursor/bot create/update Sheets and Docs.

**What you need:**
- **Google OAuth2 credentials** (Desktop app): client ID + client secret JSON from [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth Client ID (Desktop).

**Where to set:**

**For skill scripts (e.g. gc-redemption-report):**
1. Download the OAuth client JSON from Google Cloud Console.
2. Save it as: **`~/.config/gspread/credentials.json`**
3. Run the skill once; a browser opens for Google login. After you approve, the token is cached at `~/.config/gspread/authorized_user.json`.
4. In the skill’s `config.json` set `spreadsheet_id` to the default Sheet ID (for gc-redemption-report).

**For GWS MCP (Cursor):**
- Configure the **user-gws** MCP server with your Google credentials (as required by that server: often the same OAuth JSON path or a service account key). See Cursor MCP settings for `user-gws`.

---

## Summary table

| Tool       | Purpose              | Where to configure |
|-----------|----------------------|--------------------|
| **Redash**    | Run queries          | Skill `config.json` and/or `REDASH_BASE_URL`, `REDASH_API_KEY` in `.env` |
| **Coralogix** | Log/trace queries    | Coralogix MCP server config (URL + API key/token) |
| **Querybook** | Run queries          | `QUERYBOOK_BASE_URL`, `QUERYBOOK_API_TOKEN` in `.env` |
| **GWS**       | Sheets, Docs         | `~/.config/gspread/credentials.json` (skills); GWS MCP config for Cursor |

---

## Optional: env.example

See **scripts/.env.example** for a single list of optional env vars (Redash, Querybook, etc.). Copy to `scripts/.env` and fill in values. Slack/DevRev/Anthropic keys stay there; add the tool vars as you enable each tool.
