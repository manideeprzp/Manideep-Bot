"""CLI for monitor: run once or run loop."""
import logging
import os
import sys
from pathlib import Path

from .config import load_config
from .monitor import run_once, run_loop


def main():
    # Load env variables from scripts/.env
    try:
        from dotenv import load_dotenv
        _root = Path(__file__).resolve().parent.parent.parent
        load_dotenv(_root / "scripts" / ".env")
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    config = load_config()
    if not config.monitor.enabled and "run" in sys.argv:
        print("Monitor is disabled. Set monitor.enabled: true in config or MONITOR_ENABLED=1")
        sys.exit(1)
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run_loop(config)
    else:
        n_new, n_replies = run_once(config)
        print(f"Run complete: {n_new} new tickets, {n_replies} my-ticket updates")


if __name__ == "__main__":
    main()
