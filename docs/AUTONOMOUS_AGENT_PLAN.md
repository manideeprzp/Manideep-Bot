# Autonomous Agent Transformation Plan

## Current State vs Target State

### Current Architecture (Semi-Manual)
```
DevRev Ticket Created
    ↓
Workflow posts to Slack #pse-tickets
    ↓
Bot detects message → Analyzes ticket
    ↓
Bot posts suggestion: "Run order-trace-debugger?"
    ↓
⏸️  WAIT for user "Yes" ⏸️
    ↓
Bot runs skill → Shows output
    ↓
⏸️  WAIT for user "Approve" ⏸️
    ↓
Bot posts to DevRev → Closes ticket
```

**Pain Points:**
- Manual approval required for each step
- You need to monitor Slack and reply
- Cannot work while you're offline/busy
- Doesn't scale when many tickets arrive

### Target Architecture (Fully Autonomous)
```
DevRev Ticket Created
    ↓
DevRev MCP notifies Agent
    ↓
Agent analyzes ticket (Claude + past tickets)
    ↓
Agent determines skill + confidence score
    ↓
IF confidence >= threshold:
    ├─→ Auto-execute skill
    ├─→ Validate output
    ├─→ Post resolution to DevRev
    ├─→ Close ticket
    └─→ Post summary to Slack (FYI only)
ELSE:
    └─→ Post to Slack asking for approval
```

**Benefits:**
- Handles 70-80% of tickets automatically (high-confidence cases)
- You only intervene when needed (low confidence, ambiguous cases)
- Works 24/7, even when you're offline
- Learns from your approvals to improve confidence

---

## Architecture Components

### 1. DevRev MCP Integration

**What is MCP?**
Model Context Protocol - allows Claude to directly access DevRev data through a standardized interface.

**Two options:**

#### Option A: Use Existing DevRev MCP Server (Recommended)
If DevRev provides an official MCP server:
```bash
# Install MCP client
pip install mcp

# Configure MCP servers in config
{
  "mcpServers": {
    "devrev": {
      "command": "npx",
      "args": ["-y", "@devrev/mcp-server"],
      "env": {
        "DEVREV_API_KEY": "your-key"
      }
    }
  }
}
```

#### Option B: Build Custom DevRev MCP Server
If no official server exists, we build one:
```python
# src/manideep_bot/mcp_server.py
# Exposes DevRev API as MCP tools:
# - get_ticket(ticket_id)
# - list_my_tickets()
# - update_ticket(ticket_id, comment, stage)
# - search_similar_tickets(query)
```

### 2. Autonomous Agent Module

New file: `src/manideep_bot/autonomous_agent.py`

```python
class AutonomousAgent:
    """
    Autonomous ticket handling with confidence-based execution.
    """

    def __init__(self, config, devrev_client, slack_client):
        self.config = config
        self.devrev = devrev_client
        self.slack = slack_client
        self.confidence_threshold = 0.85  # Auto-execute if >= 85%

    async def handle_new_ticket(self, work_id: str):
        """
        Full autonomous flow for a new ticket.
        """
        # 1. Fetch ticket details from DevRev
        ticket = await self.devrev.get_work(work_id)

        # 2. Analyze with Claude + past tickets
        analysis = await self.analyze_ticket(ticket)

        # 3. Decide: auto-execute or ask for approval
        if analysis.confidence >= self.confidence_threshold:
            # HIGH CONFIDENCE → Auto-execute
            result = await self.execute_skill(analysis.skill_name, ticket)

            if result.success:
                # Post resolution and close
                await self.devrev.add_comment(work_id, result.output)
                await self.devrev.update_stage(work_id, "closed")

                # Notify Slack (FYI only)
                await self.slack.post_message(
                    channel=self.config.slack.notifications_channel,
                    text=f"✅ Auto-resolved {ticket.display_id} using {analysis.skill_name}"
                )
            else:
                # Skill failed → Ask for help
                await self.ask_for_help(work_id, ticket, analysis, result.error)

        else:
            # LOW CONFIDENCE → Ask for approval
            await self.request_approval(work_id, ticket, analysis)

    async def analyze_ticket(self, ticket):
        """
        Use Claude + past tickets to analyze and suggest skill.
        """
        # Similar to current agent.reply() but returns structured response
        # with confidence score
        pass

    async def execute_skill(self, skill_name, ticket):
        """
        Run the skill and validate output.
        """
        # Similar to current skill_runner.run_skill()
        pass
```

### 3. Confidence Scoring System

Enhance `agent.py` to return confidence scores:

```python
class TicketAnalysis(BaseModel):
    issue_type: str  # "order_trace", "gc_redemption", etc.
    skill_name: str  # "order-trace-debugger"
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Why this skill?
    required_data: dict  # {"order_id": "...", "card_number": "..."}
    missing_data: list[str]  # [] if all required data found
    similar_tickets: list[str]  # ["ISS-123", "ISS-456"]
    recommendation: Literal["auto_execute", "ask_approval", "need_info"]
```

**Confidence Factors:**
1. **Similarity to past tickets** (0-30 points)
   - Very similar past ticket exists → +30
   - Somewhat similar → +15
   - No match → 0

2. **Required data present** (0-30 points)
   - All required data found in ticket → +30
   - Some data missing → +15
   - Critical data missing → 0

3. **Issue type clarity** (0-20 points)
   - Clear keywords match (e.g., "order trace", "GC redemption") → +20
   - Ambiguous but likely → +10
   - Unclear → 0

4. **Skill success rate** (0-20 points)
   - Skill has >90% success rate → +20
   - 70-90% success → +10
   - <70% → 0

**Score Thresholds:**
- **≥85%**: Auto-execute
- **70-84%**: Auto-execute but notify immediately
- **50-69%**: Ask for approval in Slack
- **<50%**: Ask for more information

### 4. Event-Driven Architecture

```python
# src/manideep_bot/event_handler.py

class EventHandler:
    """
    Listens for DevRev events via MCP or webhook.
    """

    def __init__(self, autonomous_agent):
        self.agent = autonomous_agent

    async def on_work_created(self, event):
        """
        Triggered when new DevRev ticket is created.
        """
        work_id = event["work"]["id"]

        # Filter: only handle tickets assigned to you or in specific state
        if self.should_handle(event["work"]):
            await self.agent.handle_new_ticket(work_id)

    async def on_work_updated(self, event):
        """
        Triggered when ticket is updated (new comment, etc.).
        """
        # Check if this is a reply to our question
        # If yes, re-analyze with new info
        pass

    def should_handle(self, work):
        """
        Filter logic: which tickets should bot auto-handle?
        """
        # Example filters:
        # - Assigned to me
        # - State = "open" or "triaged"
        # - Type = "issue" (not "epic")
        # - Not tagged "manual_review_needed"
        pass
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)
1. **Add confidence scoring to existing agent**
   - Enhance `TicketSuggestionResponse` with confidence field
   - Implement confidence calculation logic
   - Test on existing tickets

2. **Build autonomous agent module**
   - Create `autonomous_agent.py`
   - Implement `handle_new_ticket()` with confidence-based logic
   - Add validation and error handling

3. **Set up DevRev MCP connection**
   - Install MCP client libraries
   - Configure DevRev MCP server (or build custom one)
   - Test MCP tools from Python

### Phase 2: Integration (Week 2)
1. **Connect MCP to autonomous agent**
   - Modify agent to use MCP for DevRev queries
   - Add event listener for `work_created` events
   - Implement filtering logic (which tickets to auto-handle)

2. **Add safety mechanisms**
   - Dry-run mode (analyze but don't execute)
   - Audit log (record all autonomous actions)
   - Rollback capability (if skill output is wrong)

3. **Enhance Slack notifications**
   - Post FYI messages for auto-resolved tickets
   - Create approval threads for low-confidence cases
   - Add "Stop" command to halt autonomous processing

### Phase 3: Learning & Improvement (Week 3+)
1. **Build feedback loop**
   - Track approval/rejection rates
   - Adjust confidence thresholds based on accuracy
   - Learn from manual corrections

2. **Expand skills**
   - Build top 5 skills from SKILL_BUILDING_GUIDE.md
   - Add skill validation (check output format)
   - Implement skill chaining (run multiple skills for complex tickets)

3. **Personalization**
   - Train persona on your decision patterns
   - Add custom filters per issue type
   - Build "how I think" decision trees

---

## Safety & Guardrails

### 1. Dry Run Mode
```yaml
# config/env.dev.yaml
autonomous_agent:
  enabled: true
  dry_run: true  # Analyze but don't execute
  confidence_threshold: 0.85
  notify_on_auto_execute: true
```

### 2. Approval Override
Even in autonomous mode, you can:
- Reply "Stop" in Slack to pause autonomous processing
- Tag tickets with `manual_review_needed` to bypass auto-execution
- Set confidence threshold per issue type

### 3. Audit Trail
Every autonomous action is logged:
```json
{
  "timestamp": "2026-03-10T10:30:00Z",
  "ticket_id": "ISS-12345",
  "action": "auto_resolved",
  "skill_used": "order-trace-debugger",
  "confidence": 0.92,
  "output": "Order status: delivered",
  "devrev_comment_id": "comment-xyz"
}
```

### 4. Rollback
If autonomous resolution is wrong:
- Reply "Rollback ISS-12345" in Slack
- Bot reopens ticket, adds comment: "Auto-resolution was incorrect"
- Lowers confidence for similar future tickets

---

## Configuration

### New config options

```yaml
# config/env.dev.yaml

autonomous_agent:
  enabled: true
  dry_run: false  # Set to true for testing
  confidence_threshold: 0.85
  notify_on_auto_execute: true
  max_auto_tickets_per_hour: 10  # Safety limit

  # Which tickets to auto-handle
  filters:
    - assigned_to_me: true
    - states: ["open", "triaged"]
    - exclude_tags: ["manual_review_needed", "vip_customer"]

  # Per-skill settings
  skills:
    order-trace-debugger:
      enabled: true
      confidence_threshold: 0.90  # Higher threshold for order traces
    gc-redemption-report:
      enabled: true
      confidence_threshold: 0.85
    gc-cancellation:
      enabled: false  # Always ask for approval (destructive action)

slack:
  notifications_channel: "C123456"  # For FYI messages
  approvals_channel: "C789012"  # For low-confidence tickets

devrev_mcp:
  server_command: "npx"
  server_args: ["-y", "@devrev/mcp-server"]
  api_key: "${DEVREV_API_KEY}"
```

---

## Example Flows

### Flow 1: High-Confidence Auto-Resolve
```
1. New ticket: ISS-67890 "Order 123456 not showing"
2. MCP notifies autonomous agent
3. Agent analyzes:
   - Issue type: order_trace (confidence: 95%)
   - Required data: order_id=123456 ✓
   - Similar tickets: ISS-123, ISS-456 (both resolved with order-trace-debugger)
   - Recommendation: auto_execute
4. Agent runs order-trace-debugger
5. Skill output: "Order 123456 is delivered, customer mapping issue"
6. Agent posts to DevRev: "Order traced. Status: delivered. Customer mapping was incorrect, now fixed."
7. Agent closes ticket (stage: closed)
8. Agent posts to Slack #notifications:
   ✅ Auto-resolved ISS-67890 using order-trace-debugger (confidence: 95%)
   View: https://app.devrev.ai/ISS-67890
```

### Flow 2: Low-Confidence Approval Request
```
1. New ticket: ISS-99999 "Customer complaining about booking"
2. MCP notifies autonomous agent
3. Agent analyzes:
   - Issue type: unclear (confidence: 45%)
   - Missing data: order_id, error_message
   - Recommendation: need_info
4. Agent posts to Slack #approvals:
   ⚠️ ISS-99999 needs review (confidence: 45%)

   Title: Customer complaining about booking
   Missing: order_id, error details

   Reply with:
   - "order_id: XXX" to provide data
   - "Skip" to ignore this ticket
5. You reply: "order_id: 789012"
6. Agent re-analyzes with new data → auto-executes
```

### Flow 3: Destructive Action (Always Ask)
```
1. New ticket: ISS-11111 "Cancel GC XYZ, customer wants refund"
2. Agent analyzes:
   - Issue type: gc_cancellation (confidence: 95%)
   - Skill: gc-cancellation
   - BUT: skill.enabled = false (destructive action)
3. Agent posts to Slack #approvals:
   🔴 ISS-11111 requires approval (destructive action)

   Skill: gc-cancellation
   Card: GC123456789
   Reason: customer wants refund

   Reply "Approve" to proceed or "Reject" to skip
4. You reply: "Approve"
5. Agent runs gc-cancellation → closes ticket
```

---

## Next Steps

### Immediate (You + Me working together)

1. **I need from you:**
   - Do you have access to DevRev MCP server? (If not, we build a custom one)
   - Which issue types should we prioritize for autonomous handling? (Start with top 3)
   - What's your comfort level with autonomous execution? (Start with dry_run=true?)

2. **I will build:**
   - `autonomous_agent.py` module
   - Confidence scoring enhancements to `agent.py`
   - DevRev MCP integration (or custom MCP server)
   - Configuration for autonomous mode

3. **We test together:**
   - Dry-run mode on recent closed tickets (replay scenarios)
   - Measure confidence accuracy
   - Tune thresholds

### Medium-term (After autonomous agent works)

1. **Build top 5 skills** from SKILL_BUILDING_GUIDE.md
2. **Add skill validation** (check output quality before posting to DevRev)
3. **Implement feedback loop** (learn from your corrections)
4. **Expand to proactive monitoring** (agent checks for stuck tickets, SLA breaches)

### Long-term (Your "digital twin")

1. **Persona training** - Agent learns your decision patterns
2. **Skill chaining** - Complex tickets need multiple skills
3. **Proactive suggestions** - "Hey, ISS-123 is similar to ISS-100, want me to resolve it the same way?"
4. **Cross-repo code fixes** - Agent not only diagnoses but also creates PRs to fix issues

---

## Cost & Resources

### Computing
- Current: Your laptop/VM runs Slack bot
- New: Same + MCP server (lightweight)
- No additional infrastructure needed

### API Costs
- Anthropic API: ~$0.01-0.05 per ticket analysis
- If processing 50 tickets/day → ~$1-2/day
- High-confidence auto-execution saves YOUR time = worth it

### Development Time
- Phase 1: 1-2 days (confidence scoring + autonomous agent skeleton)
- Phase 2: 2-3 days (MCP integration + testing)
- Phase 3: Ongoing (skill building + tuning)

---

## Questions for You

1. **DevRev MCP**: Do you have access to DevRev's MCP server, or should we build a custom one?

2. **Comfort level**: Should we start in dry_run mode (analyze but don't execute) or go live immediately?

3. **Which issue types first?**: From your top 5 (redemption_report, wallet_closure, program_reward, wallet, RMP_order_failure), which should be fully autonomous?

4. **Destructive actions**: Actions like gc-cancellation, wallet-closure - always require approval, or auto-execute if confidence is 95%+?

5. **Existing skills**: Do you have working scripts for:
   - order-trace-debugger ✓ (I see this in code)
   - gc-redemption-report ✓
   - gc-cancellation ✓
   - Others?

**Reply with your answers and I'll start building the autonomous agent module!**
