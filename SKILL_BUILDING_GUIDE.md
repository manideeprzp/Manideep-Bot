# Skill Building Guide - Priority Order

## 📊 Analysis Summary

**Total Solved Tickets:** 923
**Coverage:**
- Top 3 issue types = **336 tickets (36.4%)**
- Top 5 issue types = **432 tickets (46.8%)**
- Top 10 issue types = **559 tickets (60.6%)**

---

## 🎯 PHASE 1: Build Skills for Top 5 (Covers 47% of All Tickets)

### 🔥 Priority 1: `redemption_report` (74 tickets, 8.0%)
**What it is:** Gift card redemption issues
**What you need to provide:**
1. **When does this happen?** (e.g., customer can't redeem GC, redemption fails, error codes)
2. **What do you check first?** (GC code validity, balance, expiry, logs?)
3. **What tools do you use?** (Redash query? Coralogix logs? API endpoint?)
4. **What's the typical solution?** (Retry? Fix DB? Escalate?)
5. **Prerequisites:** (Order ID? GC code? Customer ID?)
6. **Redash/Querybook queries:** Share the exact queries you run
7. **Common error patterns:** What error messages indicate which issues?

---

### 🔥 Priority 2: `wallet_closure` (49 tickets, 5.3%)
**What it is:** Wallet closure/termination issues
**What you need to provide:**
1. **When is wallet closure requested?** (Compliance? Customer request? Fraud?)
2. **What checks do you perform before closing?**
3. **What's the closure process?** (Step-by-step)
4. **What tools/queries do you use?**
5. **What can go wrong?** (Balance not zero? Pending transactions?)
6. **How do you verify it's done correctly?**

---

### 🔥 Priority 3: `program_reward` (47 tickets, 5.1%)
**What it is:** Program reward setup/configuration issues
**What you need to provide:**
1. **What are common reward issues?** (Not showing? Wrong amount? Not triggering?)
2. **What do you check?** (Program config? Mapping? Eligibility rules?)
3. **Where do you look?** (Which tables/services?)
4. **How do you fix it?** (Patch config? Re-trigger? Manual grant?)
5. **What queries do you run?**

---

### ⭐ Priority 4: `Wallet` (35 tickets, 3.8%)
**What it is:** General wallet issues
**What you need to provide:**
1. **What are common wallet problems?** (Balance mismatch? Transaction failed? Wallet not found?)
2. **Your debugging workflow?**
3. **Tools and queries you use?**
4. **Common fixes?**

---

### ⭐ Priority 5: `RMP_order_failure` (28 tickets, 3.0%)
**What it is:** RMP (Retail Marketplace?) order failures
**What you need to provide:**
1. **What causes RMP order failures?**
2. **How do you debug?** (Logs? Order status checks?)
3. **What queries do you run?**
4. **How do you resolve?** (Retry? Cancel? Fix data?)

---

## 🛠️ What I Need from You for Each Issue Type

For **each of the top 5 issue types above**, please provide:

### 1. **Typical Workflow (Step-by-Step)**
Example:
```
When I get a redemption_report ticket:
1. Extract GC code and order ID from ticket
2. Run Redash query #1234 to check GC status
3. Check Coralogix logs for redemption API errors
4. If balance is zero → inform customer
5. If GC is valid but redemption failed → retry via API
6. If still failing → escalate to dev team
```

### 2. **Tools & Queries**
- **Redash:** Share query IDs or SQL
- **Querybook:** Share query templates
- **Coralogix:** What logs do you search? What filters?
- **Git repos:** Which repos do you check? What files?
- **APIs:** Which endpoints do you call? With what params?

### 3. **Decision Tree**
```
IF error_code == "INVALID_GC" THEN
    → Check GC in database
    → If found → validate format
    → If not found → inform customer
ELSE IF error_code == "EXPIRED" THEN
    → Check expiry date
    → Offer extension if policy allows
...
```

### 4. **Common Patterns**
- What error messages indicate what?
- What data patterns mean what?
- What shortcuts do you use?

### 5. **Prerequisites**
- What info must be in the ticket for you to solve it?
- What do you ask the customer if missing?

---

## 📝 How to Document Your Workflow

I'll create a template for each issue type. You fill it out, and I'll:
1. Build a **skill script** that automates your workflow
2. Update **PERSONA.md** with your decision-making process
3. Add **few-shot examples** of how you solve each issue type
4. Create **validation rules** to ensure bot confidence

---

## 🔄 Next Steps

1. **Pick ONE issue type to start** (I recommend `redemption_report` - highest volume)
2. **I'll create a template for you to fill**
3. **You provide:**
   - Your step-by-step process
   - SQL queries you run
   - Log searches you do
   - Decision criteria
4. **I'll build:**
   - Automated skill script
   - Persona updates
   - Validation logic
5. **We test it on real tickets**
6. **Repeat for other top 5 issue types**

---

## 🎯 Goal

By building skills for the **top 5 issue types**, we automate **47% of your work**.
Then we can expand to top 10 (60% coverage), then beyond.

**Ready to start with `redemption_report`?** Let me know and I'll create the documentation template for you to fill!
