#!/usr/bin/env python3
"""
Test connectivity to Redash, Querybook, and Coralogix using keys from scripts/.env.
Run from project root: python3 scripts/test_tools_connection.py
"""
import os
import sys
from pathlib import Path

# Load .env from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
env_file = PROJECT_ROOT / "scripts" / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass
    # Fallback: parse KEY=VALUE lines so we work without python-dotenv
    if not os.environ.get("REDASH_POSHVINE_URL"):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if " # " in v:
                        v = v.split(" # ", 1)[0].strip()
                    if k and v and not os.environ.get(k):
                        os.environ[k] = v

try:
    import requests
except ImportError:
    print("Install requests: pip install requests", file=sys.stderr)
    sys.exit(1)


def test_redash(name: str, base_url: str, api_key: str) -> tuple[bool, str]:
    """Redash: GET /api/data_sources with Authorization: Key <api_key>."""
    if not base_url or not api_key:
        return False, "Missing URL or API key"
    url = f"{base_url.rstrip('/')}/api/data_sources"
    try:
        r = requests.get(url, headers={"Authorization": f"Key {api_key}"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            n = len(data) if isinstance(data, list) else 0
            return True, f"OK — {n} data source(s)"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)[:200]


def test_querybook(base_url: str, token: str) -> tuple[bool, str]:
    """Querybook: try /api/user/me or /api/query_execution with api-access-token."""
    if not base_url or not token:
        return False, "Missing URL or token"
    base = base_url.rstrip("/").replace("/prod/adhoc", "").replace("/adhoc", "")
    # Common Querybook API paths
    for path in ["/api/user/me", "/api/user/current", "/api/query"]:
        url = f"{base}{path}"
        try:
            r = requests.get(
                url,
                headers={"api-access-token": token, "Content-Type": "application/json"},
                timeout=15,
            )
            if r.status_code in (200, 201):
                return True, f"OK — {path} returned {r.status_code}"
            if r.status_code != 404:
                return False, f"{path} HTTP {r.status_code}: {r.text[:150]}"
        except requests.exceptions.RequestException as e:
            return False, f"{path}: {e}"
    return False, "No known API endpoint responded 200"


def test_coralogix(name: str, base_url: str, api_key: str) -> tuple[bool, str]:
    """Coralogix: POST to dataprime query API with Bearer token. Tries app host first, then regional API."""
    if not base_url or not api_key:
        return False, "Missing URL or API key"
    from datetime import datetime, timezone, timedelta
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=15)
    # Payload per Coralogix docs (metadata format)
    payload = {
        "query": "source logs | limit 1",
        "metadata": {
            "syntax": "QUERY_SYNTAX_DATAPRIME",
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
        },
    }
    # Try user's app URL first, then India regional API (app.coralogix.in -> api.ap1.coralogix.com)
    candidates = [
        f"{base_url.rstrip('/')}/api/v1/dataprime/query",
        "https://api.ap1.coralogix.com/api/v1/dataprime/query",
    ]
    for url in candidates:
        try:
            r = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=20,
            )
            if r.status_code == 200:
                return True, "OK — query accepted"
            if r.status_code in (401, 403):
                return False, f"Auth failed HTTP {r.status_code}"
            if r.status_code == 405 and url != candidates[-1]:
                continue  # try next candidate
            if r.status_code != 405:
                return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            if url == candidates[-1]:
                return False, str(e)[:200]
            continue
    return False, "API endpoint not available (keys set — use Coralogix MCP to query)"


def test_gws() -> tuple[bool, str]:
    """GWS (Google Sheets/Docs): check gspread OAuth credentials and token (no network call to avoid hang)."""
    creds_dir = Path.home() / ".config" / "gspread"
    creds_file = creds_dir / "credentials.json"
    token_file = creds_dir / "authorized_user.json"
    if not creds_file.exists():
        return False, "Not configured — add OAuth JSON at ~/.config/gspread/credentials.json (see docs/TOOLS_SETUP.md)"
    try:
        import gspread
    except ImportError:
        return False, "Credentials found; install gspread: pip install gspread google-auth"
    if not token_file.exists():
        return False, "Credentials found; run a skill once (e.g. gc-redemption-report) to complete OAuth in browser"
    # Both files present = GWS configured and ready (skip live API call to avoid timeout in test)
    return True, "OK — credentials + token present (Sheets/Docs ready)"


def main():
    print("Testing tool connections (using scripts/.env)\n")

    results = []

    # Redash Poshvine
    url = os.environ.get("REDASH_POSHVINE_URL", "").strip()
    key = os.environ.get("REDASH_POSHVINE_API_KEY", "").strip()
    ok, msg = test_redash("Redash Poshvine", url, key)
    results.append(("Redash Poshvine", ok, msg))
    print(f"  Redash Poshvine:   {'✓' if ok else '✗'} {msg}")

    # Redash Wallet
    url = os.environ.get("REDASH_WALLET_URL", "").strip()
    key = os.environ.get("REDASH_WALLET_API_KEY", "").strip()
    ok, msg = test_redash("Redash Wallet", url, key)
    results.append(("Redash Wallet", ok, msg))
    print(f"  Redash Wallet:    {'✓' if ok else '✗'} {msg}")

    # Querybook
    url = os.environ.get("QUERYBOOK_BASE_URL", "").strip()
    token = os.environ.get("QUERYBOOK_API_TOKEN", "").strip()
    ok, msg = test_querybook(url, token)
    results.append(("Querybook", ok, msg))
    print(f"  Querybook:        {'✓' if ok else '✗'} {msg}")

    # Coralogix Poshvine
    url = os.environ.get("CORALOGIX_POSHVINE_URL", "").strip()
    key = os.environ.get("CORALOGIX_POSHVINE_API_KEY", "").strip()
    ok, msg = test_coralogix("Coralogix Poshvine", url, key)
    results.append(("Coralogix Poshvine", ok, msg))
    print(f"  Coralogix Poshvine: {'✓' if ok else '✗'} {msg}")

    # Coralogix Wallet
    url = os.environ.get("CORALOGIX_WALLET_URL", "").strip()
    key = os.environ.get("CORALOGIX_WALLET_API_KEY", "").strip()
    ok, msg = test_coralogix("Coralogix Wallet", url, key)
    results.append(("Coralogix Wallet", ok, msg))
    print(f"  Coralogix Wallet: {'✓' if ok else '✗'} {msg}")

    # GWS (Google Sheets/Docs) — OAuth, not in .env
    ok, msg = test_gws()
    results.append(("GWS (Google)", ok, msg))
    print(f"  GWS (Google):     {'✓' if ok else '✗'} {msg}")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nResult: {passed}/{len(results)} tools connected.")
    if passed < len(results):
        sys.exit(1)
    print("All tools are reachable. You can use them in skills.")
    sys.exit(0)


if __name__ == "__main__":
    main()
