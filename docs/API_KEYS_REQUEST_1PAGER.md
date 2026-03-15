# API Keys Request: 1-Pager & Misuse Prevention

**Requestor:** Manideep  
**Purpose:** Manideep Bot — DevRev ticket assistant (Slack bot that suggests approaches and skills for PSE tickets)  
**Keys requested:** Anthropic (Claude), OpenAI (embeddings)

---

## 1. One-pager: What we need and why

### What is it?

A **Slack bot** used by PSE (Product Support Engineering) that:

1. **Reads new DevRev tickets** (via Slack when a new issue is posted).
2. **Understands the ticket** (title/description) and finds **similar past solved tickets** from my own solved set.
3. **Suggests an approach and a skill to run** (e.g. order-trace-debugger, gc-redemption-report) so I can resolve the ticket faster.
4. I reply **Yes** → bot runs the skill; **Approve** → bot posts resolution on DevRev and closes the ticket.

All usage is **only for my own DevRev tickets and my own Slack workspace**; no customer-facing or multi-tenant product.

---

### Which keys and for what?

| Key | Provider | Use in the bot | Model / product |
|-----|----------|----------------|------------------|
| **ANTHROPIC_API_KEY** | Anthropic | Understand ticket text and suggest approach + skill name (one API call per ticket when I ask for a suggestion). | **claude-sonnet-4-20250514** (Messages API) |
| **OPENAI_API_KEY** | OpenAI | Semantic search over my solved tickets (embedding + similarity) so the bot surfaces the most relevant past tickets; no chat/completion. | **text-embedding-3-small** (embeddings only) |

**Why two keys?**  
- Claude is used for **understanding and suggestion** (Anthropic does not offer embeddings).  
- OpenAI is used **only for embeddings** (vector search over solved tickets). There is no OpenAI chat/completion usage.

---

### Scope and data

- **Input:** DevRev ticket title/description (and, when available, my past solved tickets metadata).
- **Output:** Plain-text suggestion (approach + skill name) shown in Slack; optional embedding vectors stored locally for retrieval.
- **No PII/card data** is sent to these APIs beyond ticket text (same as what I already see in DevRev/Slack). Embeddings are computed from ticket text only.
- **Runs on:** My machine / a single bot process; keys stored in `scripts/.env` (gitignored) or environment variables.

---

## 2. How we ensure no misuse of these keys

| Control | Implementation |
|---------|----------------|
| **Single use / single user** | Keys are used only by the Manideep Bot for my own DevRev + Slack flow. No other applications or users use these keys. |
| **No sharing** | Keys live in local `.env` (or env vars) on the machine running the bot; not committed to git, not shared with anyone. |
| **Scoped usage** | Anthropic: one-off “understand this ticket + suggest skill” calls. OpenAI: only embedding API (text-embedding-3-small); no chat, no other models. |
| **No customer data** | Only ticket title/description and my solved-ticket text are sent; no payment data, card numbers, or customer PII beyond what’s already in ticket text. |
| **Auditability** | Usage is tied to my Anthropic/OpenAI account and API key; provider dashboards can be used to monitor usage if needed. |
| **Revocation** | If keys are compromised or no longer needed, they can be revoked/rotated in Anthropic and OpenAI consoles; bot will stop working until new keys are configured. |

---

## 3. Asks

- **Anthropic:** 1x API key for Claude (model: **claude-sonnet-4-20250514**) for the use case above.  
- **OpenAI:** 1x API key with access to **text-embedding-3-small** (embeddings only).  

Once approved by security, I will store keys in `scripts/.env` (gitignored) and use them only for this bot. Happy to provide a short demo or architecture diagram if that helps the security review.

---

*Doc prepared for internal approval. Last updated: March 2025.*
