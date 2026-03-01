"""DevRev API client: works list/update, timeline list/create."""
import os
import time
from pathlib import Path
from typing import Optional

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

DEVREV_BASE = "https://api.devrev.ai"


def _token():
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(root / "scripts" / ".env")
    return os.environ.get("DEVREV_API_KEY") or os.environ.get("DEVREV_TOKEN", "")


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _get_session():
    """Get requests session with retry logic for flaky connections."""
    if not requests:
        return None

    session = requests.Session()

    # Retry strategy: More retries with longer backoff for VPN
    retry_strategy = Retry(
        total=5,  # More retries
        backoff_factor=1,  # 1s, 2s, 4s, 8s, 16s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
        raise_on_status=False  # Don't raise on retry
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=1,  # Reduce connection pool for VPN
        pool_maxsize=1
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Force HTTP/1.1 (sometimes VPNs struggle with HTTP/2)
    session.headers.update({'Connection': 'keep-alive'})

    return session


# Global session for reuse
_SESSION = None


def _request_with_retry(method, url, **kwargs):
    """Make HTTP request with retry logic and better error handling."""
    global _SESSION

    if not requests:
        raise RuntimeError("pip install requests")

    if _SESSION is None:
        _SESSION = _get_session()

    # Shorter connect timeout, longer read timeout (better for VPN)
    if 'timeout' not in kwargs:
        # (connect_timeout, read_timeout) - VPN needs time to establish, then read is fast
        kwargs['timeout'] = (60, 240)  # 60s to connect, 240s to read

    try:
        if method.upper() == "GET":
            r = _SESSION.get(url, **kwargs)
        elif method.upper() == "POST":
            r = _SESSION.post(url, **kwargs)
        elif method.upper() == "PUT":
            r = _SESSION.put(url, **kwargs)
        else:
            r = _SESSION.request(method, url, **kwargs)

        r.raise_for_status()
        return r

    except requests.exceptions.SSLError as e:
        # SSL errors - wait and retry once more
        time.sleep(2)
        if method.upper() == "GET":
            r = requests.get(url, **kwargs)
        else:
            r = requests.post(url, **kwargs)
        r.raise_for_status()
        return r

    except requests.exceptions.ConnectionError as e:
        # Connection errors - wait and retry once more
        time.sleep(3)
        if method.upper() == "GET":
            r = requests.get(url, **kwargs)
        else:
            r = requests.post(url, **kwargs)
        r.raise_for_status()
        return r


def get_self():
    """Current user (dev-users.self)."""
    r = _request_with_retry("GET", f"{DEVREV_BASE}/dev-users.self", headers=_headers())
    return r.json().get("dev_user", {})


def parts_list(name: list = None, limit: int = 50, cursor: str = None):
    """POST parts.list – list parts, optionally filtered by name(s). Returns list of parts with id, name."""
    body = {"limit": limit}
    if name:
        body["name"] = [n.strip() for n in name if n and str(n).strip()]
    if cursor:
        body["cursor"] = cursor
    r = _request_with_retry("POST", f"{DEVREV_BASE}/parts.list", headers=_headers(), json=body)
    return r.json()


def works_list(
    owned_by: list = None,
    state: list = None,
    applies_to_part: list = None,
    work_ids: list = None,
    limit: int = 50,
    cursor: str = None,
):
    """POST works.list with filters."""
    body = {"limit": limit}
    if owned_by:
        body["owned_by"] = owned_by
    if state:
        body["state"] = state
    if applies_to_part:
        body["applies_to_part"] = applies_to_part
    if work_ids:
        body["id"] = work_ids  # Fetch specific work IDs
    if cursor:
        body["cursor"] = cursor
    r = _request_with_retry("POST", f"{DEVREV_BASE}/works.list", headers=_headers(), json=body)
    return r.json()


def timeline_entries_list(object_id: str, limit: int = 50, cursor: str = None):
    """GET timeline-entries.list for a work item (comments/replies)."""
    params = {"object": object_id, "limit": limit}
    if cursor:
        params["cursor"] = cursor
    r = _request_with_retry("GET", f"{DEVREV_BASE}/timeline-entries.list", headers=_headers(), params=params)
    return r.json()


def timeline_entry_create(object_id: str, body_text: str, visibility: str = "external"):
    """POST timeline-entries.create (add comment on ticket)."""
    payload = {
        "type": "timeline_comment",
        "object": object_id,
        "body": body_text,
        "visibility": visibility,
    }
    r = _request_with_retry("POST", f"{DEVREV_BASE}/timeline-entries.create", headers=_headers(), json=payload)
    return r.json()


def work_update_stage(work_id: str, stage_name: str):
    """POST works.update – set stage (e.g. Closed)."""
    payload = {"id": work_id, "stage": {"name": stage_name}}
    r = _request_with_retry("POST", f"{DEVREV_BASE}/works.update", headers=_headers(), json=payload)
    return r.json()
