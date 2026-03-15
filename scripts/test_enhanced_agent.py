#!/usr/bin/env python3
"""Test the enhanced agent with sample tickets."""
import sys
from pathlib import Path

# Add src to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

from manideep_bot.config import load_config
from manideep_bot.enhanced_agent import enhanced_reply

# Sample test tickets
TEST_TICKETS = {
    "order_trace": """
        Customer can't see their booking.
        Order ID: order_abc123
        They completed payment but the order doesn't show in their account.
    """,

    "gc_redemption": """
        Please share the redemption report for card number GC123456789.
        Customer claims they never used it but wants to verify.
    """,

    "gc_cancellation": """
        Cancel card GC987654321.
        Reason: Customer wants refund, duplicate purchase.
    """,

    "low_confidence": """
        Customer is complaining about some issue with their recent transaction.
        Can you help?
    """,

    "missing_data": """
        Need to trace an order but the customer didn't provide the order ID.
        They just said "my booking from yesterday".
    """,
}


def test_ticket(name: str, text: str):
    """Test a single ticket."""
    print(f"\n{'='*80}")
    print(f"TEST: {name}")
    print(f"{'='*80}")
    print(f"\nInput:\n{text.strip()}\n")
    print(f"{'-'*80}\n")

    config = load_config()
    response = enhanced_reply(text.strip(), config)

    print("Response:")
    print(response)
    print(f"\n{'='*80}\n")


def main():
    """Run all tests or a specific one."""
    if len(sys.argv) > 1:
        # Test specific ticket
        name = sys.argv[1]
        if name in TEST_TICKETS:
            test_ticket(name, TEST_TICKETS[name])
        else:
            print(f"Unknown test: {name}")
            print(f"Available tests: {', '.join(TEST_TICKETS.keys())}")
            sys.exit(1)
    else:
        # Test all tickets
        for name, text in TEST_TICKETS.items():
            test_ticket(name, text)


if __name__ == "__main__":
    main()
