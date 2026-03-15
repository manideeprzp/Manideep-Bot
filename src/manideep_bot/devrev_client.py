"""DevRev API client: works list/update, timeline list/create."""
import os
import re
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

# Cached org devo ID — derived once from get_self(), used for instant ID construction
_DEVO_ID_CACHE: Optional[str] = None


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
    if not requests:
        return None
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Connection": "keep-alive"})
    return session


_SESSION = None


def _request_with_retry(method, url, **kwargs):
    global _SESSION
    if not requests:
        raise RuntimeError("pip install requests")
    if _SESSION is None:
        _SESSION = _get_session()
    if "timeout" not in kwargs:
        kwargs["timeout"] = (30, 60)  # faster timeout: 30s connect, 60s read
    try:
        if method.upper() == "GET":
            r = _SESSION.get(url, **kwargs)
        elif method.upper() == "POST":
            r = _SESSION.post(url, **kwargs)
        else:
            r = _SESSION.request(method, url, **kwargs)
        r.raise_for_status()
        return r
    except requests.exceptions.SSLError:
        time.sleep(2)
        r = requests.post(url, **kwargs) if method.upper() == "POST" else requests.get(url, **kwargs)
        r.raise_for_status()
        return r
    except requests.exceptions.ConnectionError:
        time.sleep(3)
        r = requests.post(url, **kwargs) if method.upper() == "POST" else requests.get(url, **kwargs)
        r.raise_for_status()
        return r


# ── Core helpers ──────────────────────────────────────────────────────────────

def get_self():
    """Current authenticated user (dev-users.self)."""
    r = _request_with_retry("GET", f"{DEVREV_BASE}/dev-users.self", headers=_headers())
    return r.json().get("dev_user", {})


def _get_devo_id() -> str:
    """
    Return the org devo ID (e.g. '2sRI6Hepzz') — cached after first call.
    Derived from the authenticated user's own ID:
      don:identity:dvrv-in-1:devo/2sRI6Hepzz:devu/9778  →  2sRI6Hepzz
    """
    global _DEVO_ID_CACHE
    if _DEVO_ID_CACHE:
        return _DEVO_ID_CACHE
    user = get_self()
    user_id = user.get("id", "")
    m = re.search(r"devo/([A-Za-z0-9]+)", user_id)
    if m:
        _DEVO_ID_CACHE = m.group(1)
    return _DEVO_ID_CACHE or ""


def display_id_to_work_id(display_id: str) -> Optional[str]:
    """
    FAST: Convert ISS-XXXXXX to internal DevRev work ID instantly.
    No pagination — just constructs the DON from org ID + numeric suffix.

    ISS-1659563  →  don:core:dvrv-in-1:devo/2sRI6Hepzz:issue/1659563
    """
    if not display_id:
        return None
    m = re.match(r"(ISS|ISSUE)-(\d+)", display_id.strip(), re.I)
    if not m:
        return None
    num = m.group(2)
    devo_id = _get_devo_id()
    if not devo_id:
        return None
    return f"don:core:dvrv-in-1:devo/{devo_id}:issue/{num}"


# ── Works ─────────────────────────────────────────────────────────────────────

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
        body["id"] = work_ids
    if cursor:
        body["cursor"] = cursor
    r = _request_with_retry("POST", f"{DEVREV_BASE}/works.list", headers=_headers(), json=body)
    return r.json()


def count_open_tickets_for_user(user_id: str) -> int:
    """
    Count how many open tickets a user has assigned.

    Args:
        user_id: DevRev user ID (e.g., don:identity:dvrv-in-1:devo/2sRI6Hepzz:devu/9778)

    Returns:
        Number of open tickets (states: open, in_progress, triaged, backlog)
    """
    try:
        result = works_list(
            owned_by=[user_id],
            state=["open", "in_progress", "triaged", "backlog"],
            limit=50  # Get first page to count
        )
        works = result.get("works", [])
        total = len(works)

        # If there's more, we need to paginate
        cursor = result.get("next_cursor")
        while cursor and total < 100:  # Stop at 100 to avoid infinite loops
            result = works_list(
                owned_by=[user_id],
                state=["open", "in_progress", "triaged", "backlog"],
                limit=50,
                cursor=cursor
            )
            works = result.get("works", [])
            total += len(works)
            cursor = result.get("next_cursor")
            if not works:
                break

        return total
    except Exception:
        # If count fails, assume it's safe to assign (don't block auto-assignment)
        return 0


def work_get(work_id: str) -> Optional[dict]:
    """GET works.get — fetch a single work by its internal DON ID. Returns the work dict or None."""
    r = _request_with_retry("GET", f"{DEVREV_BASE}/works.get", headers=_headers(), params={"id": work_id})
    return r.json().get("work")


def get_work_by_display_id(display_id: str) -> Optional[dict]:
    """
    Fetch a work by display ID (e.g. ISS-1659563).

    FAST PATH: construct DON ID from numeric suffix → single works.get call. O(1), ~2s.
    No pagination through thousands of tickets.
    """
    import logging
    _log = logging.getLogger(__name__)
    if not (display_id or "").strip():
        return None
    display_id = display_id.strip()

    # Fast path: construct the internal DON ID and call works.get directly
    work_id = display_id_to_work_id(display_id)
    if work_id:
        try:
            work = work_get(work_id)
            if work:
                return work
        except Exception as e:
            _log.warning("works.get fast path failed for %s (%s): %s", display_id, work_id, e)

    # Slow fallback (e.g. unknown prefix, org mismatch)
    _log.warning("Falling back to pagination for %s", display_id)
    states = ["open", "triaged", "backlog", "in_progress"]
    cursor = None
    for _ in range(5):
        body = {"limit": 50, "state": states}
        if cursor:
            body["cursor"] = cursor
        r = _request_with_retry("POST", f"{DEVREV_BASE}/works.list", headers=_headers(), json=body)
        data = r.json()
        works = data.get("works") or []
        for w in works:
            if (w.get("display_id") or "").strip().upper() == display_id.upper():
                return w
        cursor = data.get("next_cursor")
        if not cursor or not works:
            break
    return None


# ── Timeline ──────────────────────────────────────────────────────────────────

def parts_list(name: list = None, limit: int = 50, cursor: str = None):
    body = {"limit": limit}
    if name:
        body["name"] = [n.strip() for n in name if n and str(n).strip()]
    if cursor:
        body["cursor"] = cursor
    r = _request_with_retry("POST", f"{DEVREV_BASE}/parts.list", headers=_headers(), json=body)
    return r.json()


def timeline_entries_list(object_id: str, limit: int = 50, cursor: str = None):
    params = {"object": object_id, "limit": limit}
    if cursor:
        params["cursor"] = cursor
    r = _request_with_retry("GET", f"{DEVREV_BASE}/timeline-entries.list", headers=_headers(), params=params)
    return r.json()


def timeline_entry_create(object_id: str, body_text: str, visibility: str = "external"):
    payload = {
        "type": "timeline_comment",
        "object": object_id,
        "body": body_text,
        "visibility": visibility,
    }
    r = _request_with_retry("POST", f"{DEVREV_BASE}/timeline-entries.create", headers=_headers(), json=payload)
    return r.json()


# ── Works update ──────────────────────────────────────────────────────────────

def work_update_stage(work_id: str, stage_name: str):
    """POST works.update – set stage (e.g. Closed)."""
    payload = {"id": work_id, "stage": {"name": stage_name}}
    r = _request_with_retry("POST", f"{DEVREV_BASE}/works.update", headers=_headers(), json=payload)
    return r.json()


def work_assign(work_id: str, user_id: str):
    """POST works.update – assign ticket to a user. Correct format: owned_by: {set: [id]}."""
    payload = {"id": work_id, "owned_by": {"set": [user_id]}}
    r = _request_with_retry("POST", f"{DEVREV_BASE}/works.update", headers=_headers(), json=payload)
    return r.json()


def work_add_tag_safe(work_id: str, tag_name: str, value: str = "") -> bool:
    """Add a tag to a work. Best-effort — logs and returns False if tag not in org."""
    try:
        work = work_get(work_id)
        if not work:
            return False
        existing = work.get("tags") or []
        new_entry = {"tag": {"name": tag_name}, "value": value or tag_name}
        if any((t.get("tag") or {}).get("name") == tag_name for t in existing):
            return True
        combined = list(existing) + [new_entry]
        payload = {"id": work_id, "tags": combined}
        _request_with_retry("POST", f"{DEVREV_BASE}/works.update", headers=_headers(), json=payload)
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("work_add_tag_safe failed: %s", e)
        return False


# ── Hybrid Search ─────────────────────────────────────────────────────────────

def search_hybrid(query: str, namespace: str = "issue", limit: int = 10) -> dict:
    """
    DevRev hybrid search — semantic + keyword search across the knowledge graph.
    namespace: 'issue', 'ticket', 'article', 'conversation', etc.
    """
    body = {"query": query, "namespace": namespace, "limit": limit}
    r = _request_with_retry("POST", f"{DEVREV_BASE}/search.hybrid", headers=_headers(), json=body)
    return r.json()


def find_similar_issues(ticket_text: str, limit: int = 5,
                        only_solved: bool = False) -> list[dict]:
    """
    Find similar issues using DevRev hybrid search (namespace=issue).
    We only deal with ISS- issues; TKT- tickets are out of scope.
    If only_solved=True, filters to closed/done/resolved issues only.
    """
    import logging
    _log = logging.getLogger(__name__)
    try:
        result = search_hybrid(ticket_text[:500], namespace="issue", limit=limit)
        works = []
        for item in (result.get("results") or []):
            work = item.get("work") or item
            if isinstance(work, dict) and work.get("display_id"):
                if only_solved and work.get("state") not in ("closed", "done", "resolved"):
                    continue
                works.append(work)
        return works
    except Exception as e:
        _log.warning("hybrid search failed: %s", e)
        return []


def get_tags_from_work(work: dict) -> list[dict]:
    """Extract tags from a work object. Returns [{"name": ..., "value": ...}, ...]."""
    tags_raw = work.get("tags") or []
    result = []
    for t in tags_raw:
        tag_obj = t.get("tag") or {}
        name = tag_obj.get("name") or ""
        if name:
            result.append({"name": name, "value": t.get("value") or "", "id": tag_obj.get("id") or ""})
    return result


def get_custom_fields_from_work(work: dict) -> dict:
    """
    Extract custom fields from a work object.
    Handles both top-level (tnt__*, ctype__*) and nested (custom_fields dict) formats.
    """
    fields = {}
    # Top-level custom fields (from works.get REST API)
    for k, v in work.items():
        if (k.startswith("tnt__") or k.startswith("ctype__")) and v is not None and v != "":
            fields[k] = v
    # Nested custom_fields dict (from fetch_object_context MCP)
    nested = work.get("custom_fields") or {}
    for k, v in nested.items():
        if v is not None and v != "" and k not in fields:
            # Skip internal Slack sync fields
            if k.startswith("app_slack__"):
                continue
            fields[k] = v
    return fields


# ── Comprehensive work update ─────────────────────────────────────────────────

def work_update_full(
    work_id: str,
    stage_name: str = None,
    tags_to_add: list[dict] = None,
    comment: str = None,
    comment_visibility: str = "external",
    custom_fields: dict = None,
) -> dict:
    """
    Comprehensive work update: stage + tags + custom fields + optional comment.

    Args:
        work_id: DevRev work DON ID
        stage_name: Stage to transition to (e.g. "Closed")
        tags_to_add: List of {"name": ..., "value": ...} to add (deduped against existing)
        comment: If provided, post as a timeline comment
        comment_visibility: "external", "internal", or "private"
        custom_fields: Dict of custom fields (e.g. {"tnt__sla_status": "Hit"})

    Returns: API response dict
    """
    import logging
    _log = logging.getLogger(__name__)

    payload = {"id": work_id}

    if stage_name:
        payload["stage"] = {"name": stage_name}

    if tags_to_add:
        try:
            work = work_get(work_id)
            existing_tags = (work or {}).get("tags") or []
            existing_names = {(t.get("tag") or {}).get("name") for t in existing_tags}
            combined = list(existing_tags)
            for tag in tags_to_add:
                if tag.get("name") and tag["name"] not in existing_names:
                    combined.append({"tag": {"name": tag["name"]}, "value": tag.get("value", "")})
            payload["tags"] = combined
        except Exception as e:
            _log.warning("Failed to merge tags for %s: %s", work_id, e)

    if custom_fields:
        for k, v in custom_fields.items():
            payload[k] = v

    result = {}
    try:
        r = _request_with_retry("POST", f"{DEVREV_BASE}/works.update", headers=_headers(), json=payload)
        result = r.json()
    except Exception as e:
        _log.error("work_update_full failed for %s: %s", work_id, e)

    if comment:
        try:
            timeline_entry_create(work_id, comment, visibility=comment_visibility)
        except Exception as e:
            _log.error("Comment post failed for %s: %s", work_id, e)

    return result


def build_resolution_comment(
    summary: str,
    skill_name: str = "",
    similar_ticket_id: str = "",
) -> str:
    """Build a structured resolution comment for posting on a DevRev ticket."""
    parts = ["**Resolution:**", summary]
    if skill_name:
        parts.append(f"\n**Resolved via skill:** `{skill_name}`")
    if similar_ticket_id:
        parts.append(f"\n**Similar solved ticket:** {similar_ticket_id}")
    return "\n".join(parts)


def build_tags_for_closure(
    skill_name: str = "",
    similar_ticket_tags: list[dict] = None,
    extra_tags: list[dict] = None,
) -> list[dict]:
    """
    Build the tag list for closing a ticket:
      1. Tags copied from the similar solved ticket (same category/type)
      2. Skill tag (e.g. "skill:rmp-order-trace-debugger")
      3. "bot_resolved" marker tag
      4. Any extra tags
    """
    tags = []
    seen = set()

    if similar_ticket_tags:
        for t in similar_ticket_tags:
            name = t.get("name", "")
            if name and name not in seen:
                tags.append({"name": name, "value": t.get("value", "")})
                seen.add(name)

    if skill_name:
        skill_tag = f"skill:{skill_name}"
        if skill_tag not in seen:
            tags.append({"name": skill_tag, "value": skill_name})
            seen.add(skill_tag)

    bot_tag = "bot_resolved"
    if bot_tag not in seen:
        tags.append({"name": bot_tag, "value": "manideep-bot"})
        seen.add(bot_tag)

    for t in (extra_tags or []):
        name = t.get("name", "")
        if name and name not in seen:
            tags.append({"name": name, "value": t.get("value", "")})
            seen.add(name)

    return tags
