#!/usr/bin/env python3
"""
Auto-watcher for Claude Code integration.

Watches the analysis queue directory and automatically analyzes new tickets
using Claude Code's capabilities (past ticket search, pattern matching, etc.).

Run this in the background:
    python scripts/auto_watcher.py

Or use the shell wrapper:
    ./scripts/run_auto_watcher.sh
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from manideep_bot.config import load_config
from manideep_bot.retriever import find_relevant
from manideep_bot.enhanced_agent import IssuePattern, extract_structured_data

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_ticket_automatically(ticket_file: Path, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Automatically analyze a ticket using Claude Code's capabilities.

    This mimics what Claude Code would do:
    1. Read the ticket
    2. Search past solved tickets
    3. Detect patterns
    4. Extract structured data
    5. Generate analysis with confidence
    """
    try:
        # Read ticket
        with open(ticket_file) as f:
            ticket_data = json.load(f)

        ticket_id = ticket_data.get("ticket_id", "Unknown")
        ticket_text = ticket_data.get("text", "")

        logger.info(f"Auto-analyzing ticket {ticket_id}...")

        # 1. Search past solved tickets
        relevant_tickets = find_relevant(ticket_text, config, top_k=10)

        # 2. Detect issue pattern
        issue_type = IssuePattern.detect_issue_type(ticket_text)

        # 3. Extract structured data
        structured_data = extract_structured_data(ticket_text, issue_type)

        # 4. Calculate confidence based on:
        # - Pattern match strength
        # - Number of relevant past tickets
        # - Completeness of extracted data
        confidence = 0.0

        if issue_type != "general":
            confidence += 0.3  # Pattern detected

        if relevant_tickets:
            # More relevant tickets = higher confidence
            confidence += min(0.4, len(relevant_tickets) * 0.04)

        # Check data completeness
        required_fields = structured_data.get("required_data", {})
        if required_fields:
            found = sum(1 for v in required_fields.values() if v)
            total = len(required_fields)
            confidence += (found / total) * 0.3

        confidence = min(confidence, 0.95)  # Cap at 95%

        # 5. Determine skill to run
        skill_name = None
        if issue_type == "gc_redemption":
            skill_name = "gc-redemption-report"
        elif issue_type == "order_trace":
            skill_name = "order-trace"
        elif issue_type == "booking_check":
            skill_name = "booking-status"
        elif relevant_tickets and relevant_tickets[0].get("score", 0) > 0.7:
            # High similarity to past ticket - use same skill
            past_ticket = relevant_tickets[0]
            skill_name = past_ticket.get("skill_used") or past_ticket.get("title", "").lower().replace(" ", "-")

        # 6. Build analysis text
        analysis_parts = []

        # Confidence indicator
        if confidence >= 0.8:
            analysis_parts.append(f"🟢 Confidence: {int(confidence * 100)}%")
        elif confidence >= 0.5:
            analysis_parts.append(f"🟡 Confidence: {int(confidence * 100)}%")
        else:
            analysis_parts.append(f"🔴 Confidence: {int(confidence * 100)}%")

        analysis_parts.append("")

        # Analysis
        analysis_parts.append("**Analysis:**")
        if issue_type != "general":
            analysis_parts.append(f"Issue type: {issue_type.replace('_', ' ').title()}")

        if structured_data.get("summary"):
            analysis_parts.append(structured_data["summary"])
        else:
            analysis_parts.append(f"Based on the ticket description, this appears to be a {issue_type.replace('_', ' ')} issue.")

        analysis_parts.append("")

        # Relevant past tickets
        if relevant_tickets:
            analysis_parts.append("**Similar past tickets:**")
            for i, ticket in enumerate(relevant_tickets[:3], 1):
                ticket_ref = ticket.get("id", "Unknown")
                score = ticket.get("score", 0)
                analysis_parts.append(f"{i}. {ticket_ref} (similarity: {int(score * 100)}%)")
            analysis_parts.append("")

        # Required data
        if required_fields:
            analysis_parts.append("**Required data:**")
            for field, value in required_fields.items():
                status = "✓" if value else "✗"
                analysis_parts.append(f"{status} {field}: {value if value else 'Not found'}")
            analysis_parts.append("")

        # Skill to run
        if skill_name:
            analysis_parts.append(f"**Skill to run:** {skill_name}")
            analysis_parts.append("")

        # Recommendation
        recommendation = "ask_approval"  # Default: always ask
        if confidence >= 0.9 and all(required_fields.values()):
            recommendation = "high_confidence"
        elif confidence < 0.5:
            recommendation = "manual_review"

        analysis_parts.append(f"**Recommendation:** {recommendation.replace('_', ' ').title()}")
        analysis_parts.append("")
        analysis_parts.append("---")
        analysis_parts.append("")
        analysis_parts.append("Reply **Yes** to run the skill, or **No** to cancel.")

        # 7. Create response
        response = {
            "timestamp": ticket_data.get("timestamp"),
            "ticket_id": ticket_id,
            "status": "completed",
            "analyzed_at": datetime.now().isoformat(),
            "analysis": "\n".join(analysis_parts),
            "metadata": {
                "issue_type": issue_type,
                "skill_name": skill_name,
                "confidence": confidence,
                "recommendation": recommendation,
                "relevant_tickets_count": len(relevant_tickets),
                "auto_analyzed": True
            }
        }

        return response

    except Exception as e:
        logger.error(f"Error analyzing ticket {ticket_file}: {e}", exc_info=True)
        return None


def watch_queue(config: Dict[str, Any], interval: int = 5):
    """
    Watch the analysis queue directory and automatically analyze new tickets.

    Args:
        config: Bot configuration
        interval: Check interval in seconds
    """
    queue_dir = Path("data/analysis_queue")
    queue_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"🤖 Auto-watcher started. Watching {queue_dir}")
    logger.info(f"Checking every {interval} seconds...")

    processed = set()

    while True:
        try:
            # Find pending tickets (no response file yet)
            ticket_files = list(queue_dir.glob("ticket_*.json"))

            for ticket_file in ticket_files:
                # Skip if already processed
                if ticket_file in processed:
                    continue

                # Check if response already exists
                response_file = ticket_file.parent / f"{ticket_file.stem}_response.json"
                if response_file.exists():
                    processed.add(ticket_file)
                    continue

                # New ticket - analyze it!
                logger.info(f"📬 New ticket detected: {ticket_file.name}")

                response = analyze_ticket_automatically(ticket_file, config)

                if response:
                    # Write response
                    with open(response_file, "w") as f:
                        json.dump(response, f, indent=2)

                    logger.info(f"✅ Analysis complete: {response_file.name}")
                    logger.info(f"   Confidence: {response['metadata']['confidence']:.0%}")
                    logger.info(f"   Skill: {response['metadata'].get('skill_name', 'None')}")
                else:
                    logger.error(f"❌ Failed to analyze {ticket_file.name}")

                processed.add(ticket_file)

            # Sleep
            time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("🛑 Auto-watcher stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in watch loop: {e}", exc_info=True)
            time.sleep(interval)


def main():
    """Main entry point."""
    try:
        # Load config
        config = load_config()

        # Watch queue
        watch_queue(config, interval=5)

    except KeyboardInterrupt:
        logger.info("Goodbye!")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
