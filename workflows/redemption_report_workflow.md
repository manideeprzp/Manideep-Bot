# Redemption Report Workflow Template

**Issue Type:** Gift Card Redemption Issues
**Tag:** `redemption_report`
**Volume:** 74 tickets (8.0% of all tickets)
**Priority:** #1 (Highest volume skill to build)

---

## 📋 Fill This Out - I'll Build the Skill

### 1. What triggers this issue type?

**Common scenarios (check all that apply):**
- [ ] Customer can't redeem gift card
- [ ] Redemption API returns error
- [ ] Gift card shows as invalid
- [ ] Balance not updated after redemption
- [ ] Redemption succeeds but customer doesn't see it
- [ ] Other: _______________________

**Most common trigger:**
```
[Your answer: e.g., "Customer tries to redeem GC but gets error: INVALID_CODE"]
```

---

### 2. Your Step-by-Step Workflow

**When you get a redemption_report ticket, what do you do? (Be specific!)**

```
Step 1: [Extract information from ticket]
   - What info do you look for? (GC code? Order ID? Customer ID? Error message?)

Step 2: [First check - what do you verify?]
   - Tool used: [Redash? Querybook? Database? API?]
   - What are you checking for?

Step 3: [If Step 2 shows X, then what?]
   -

Step 4: [If Step 2 shows Y, then what?]
   -

Step 5: [How do you verify the fix worked?]
   -

Step 6: [What do you tell the customer?]
   -
```

---

### 3. Tools & Queries You Use

#### Redash Queries
**Query #1:**
```sql
-- What does this query do? [e.g., Check GC status and balance]
-- Query ID in Redash: ______
-- Parameters needed: [gc_code? order_id?]

[Paste your SQL query here]
```

**Query #2 (if applicable):**
```sql
-- What does this query do?
-- Query ID: ______

[Paste SQL here]
```

#### Coralogix / Logs
```
Service to search: _____________
Filter/Query: __________________
What are you looking for in logs? ______________
```

#### Querybook
```
Query name: _______________
What it does: ______________
[Paste query if possible]
```

#### API Calls
```
Endpoint: _______________
Method: GET/POST/PATCH
Parameters: ______________
What does it do? ______________
```

#### Git Repositories
```
Which repo(s) do you check? _______________
What files/code do you look at? _______________
Why? _______________
```

---

### 4. Decision Tree

**Fill this out based on what you find:**

```
IF [GC code is invalid format] THEN
   → Action: _______________
   → Tell customer: _______________

ELSE IF [GC code not found in database] THEN
   → Action: _______________
   → Tell customer: _______________

ELSE IF [GC exists but balance is zero] THEN
   → Action: _______________
   → Tell customer: _______________

ELSE IF [GC exists, has balance, but redemption fails] THEN
   → Check logs for: _______________
   → If error_code == "XXXX" → _______________
   → If error_code == "YYYY" → _______________

ELSE IF [Redemption succeeded but not reflected] THEN
   → Action: _______________

ELSE
   → Escalate to: _______________
```

---

### 5. Common Error Codes/Messages

**What error messages do you see and what do they mean?**

| Error Code/Message | What it means | How you fix it |
|-------------------|---------------|----------------|
| `INVALID_CODE` | ? | ? |
| `EXPIRED` | ? | ? |
| `ALREADY_REDEEMED` | ? | ? |
| `BALANCE_ZERO` | ? | ? |
| ? | ? | ? |

---

### 6. Prerequisites (Required Information)

**What info MUST be in the ticket for you to solve it?**
- [ ] Gift card code
- [ ] Order ID
- [ ] Customer ID / Email
- [ ] Error message / screenshot
- [ ] Redemption timestamp
- [ ] Other: _______________

**If info is missing, what do you ask the customer?**
```
[Your standard reply when info is missing]
```

---

### 7. Common Patterns & Shortcuts

**What patterns have you noticed?**
```
Example: "If redemption fails with error X, it's usually because Y, so I immediately check Z"

Pattern 1: _______________
Pattern 2: _______________
Pattern 3: _______________
```

**Any shortcuts you use?**
```
Example: "I always check if GC was issued in the last 24h - if yes, it's usually a sync delay"

Shortcut 1: _______________
Shortcut 2: _______________
```

---

### 8. Success Criteria

**How do you know the issue is resolved?**
- [ ] Customer can successfully redeem
- [ ] Balance updated correctly
- [ ] No errors in logs
- [ ] Verification query shows correct status
- [ ] Other: _______________

---

### 9. When to Escalate

**When do you escalate instead of solving?**
```
Scenario 1: _______________
Scenario 2: _______________

Escalate to: [Team name? Person? Slack channel?]
```

---

### 10. Typical Resolution Time

**How long does this usually take you to solve?**
- [ ] < 5 minutes (simple lookup/fix)
- [ ] 5-15 minutes (requires investigation)
- [ ] 15-30 minutes (complex debugging)
- [ ] 30+ minutes (needs escalation or deep dive)

---

## 📝 Example Solved Ticket

**Paste one real example of how you solved a redemption_report ticket:**

```
Ticket ID: ISS-______
Customer issue: "I can't redeem my gift card, getting error INVALID_CODE"

What I did:
1. [Step by step what you did]
2.
3.

Resolution: _______________
Response to customer: _______________
```

---

## ✅ Once You Fill This Out

I will:
1. ✅ Build an automated **`redemption-report`** skill script
2. ✅ Update PERSONA.md with your decision logic
3. ✅ Add few-shot examples to improve AI accuracy
4. ✅ Create validation rules (bot won't suggest this skill unless prerequisites are met)
5. ✅ Test it on sample tickets

**Then the bot can handle 8% of your tickets automatically!** 🎉

---

**Fill this out and share it with me. I'll turn it into working automation.**
