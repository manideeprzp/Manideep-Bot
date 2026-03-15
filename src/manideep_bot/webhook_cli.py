"""CLI to run the DevRev webhook HTTP server. Starts worker thread and serves POST /webhooks/devrev."""
import logging
import os
import sys
from pathlib import Path


def main():
    try:
        from dotenv import load_dotenv
        _root = Path(__file__).resolve().parent.parent.parent
        load_dotenv(_root / "scripts" / ".env")
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    from .webhook_app import create_app, run_worker_background

    run_worker_background()
    app = create_app()

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8765"))
    try:
        import uvicorn
        uvicorn.run(app, host=host, port=port, log_level="info")
    except ImportError:
        print("Install uvicorn and fastapi: pip install uvicorn fastapi", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
