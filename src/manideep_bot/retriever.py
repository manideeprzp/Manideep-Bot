"""
Find relevant past solved tickets for a given issue description.
Uses BM25 (when available) + tag boost; optional embeddings (OpenAI) for semantic similarity
and min_similarity threshold to avoid misleading top-k when no good match exists.
Thread text (timeline/conversation) is included in corpus and embeddings for better matching.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional
from difflib import SequenceMatcher

from .config import Config

# Optional BM25 for better text relevance
try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None
    _BM25_AVAILABLE = False

# Global cache for BM25 index to avoid rebuilding on every query
_BM25_CACHE = None
_CACHE_HASH = None

# Simple stopwords to avoid matching on noise
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "can", "this", "that", "these",
        "those", "it", "its", "we", "our", "they", "them", "he", "she", "i",
        "please", "kindly", "hi", "hello", "thanks", "regards", "detail", "details",
    }
)


def _tokenize(text: str) -> set[str]:
    """Lowercase, split on non-alphanumeric, drop short and stopwords. Returns set."""
    if not text:
        return set()
    text = (text or "").lower().strip()
    words = re.findall(r"[a-z0-9]{2,}", text)
    return set(w for w in words if w not in _STOP)


def _tokenize_list(text: str) -> list[str]:
    """Same as _tokenize but returns ordered list (for BM25 corpus)."""
    if not text:
        return []
    text = (text or "").lower().strip()
    words = re.findall(r"[a-z0-9]{2,}", text)
    return [w for w in words if w not in _STOP]


def _tag_tokens(tag_names: list) -> set[str]:
    """Tokenize tag names (e.g. 'redemption_report' -> redemption, report)."""
    out = set()
    for t in tag_names or []:
        if isinstance(t, str):
            for part in re.split(r"[_:\s]+", t.lower()):
                if len(part) >= 2 and part not in _STOP:
                    out.add(part)
    return out


def _preprocess_query(query: str) -> str:
    """Expand domain-specific abbreviations for better matching."""
    if not query:
        return query

    # Domain-specific expansions (add more as you identify patterns)
    expansions = {
        r"\bgc\b": "gc gift card giftcard",
        r"\bredemption\b": "redemption redeem gift card",
        r"\bbooking\b": "booking order reservation book",
        r"\bcancel\b": "cancel cancellation cancelled",
        r"\border\b": "order booking reservation",
        r"\btrace\b": "trace debug debugger tracking",
    }

    query_lower = query.lower()
    for pattern, expansion in expansions.items():
        query_lower = re.sub(pattern, expansion, query_lower)

    return query_lower


def _get_bm25_index(corpus: list, tickets_count: int):
    """Get or build cached BM25 index. Cache is invalidated when ticket count changes."""
    global _BM25_CACHE, _CACHE_HASH

    cache_key = str(tickets_count)

    if _BM25_CACHE is not None and _CACHE_HASH == cache_key:
        return _BM25_CACHE

    _BM25_CACHE = BM25Okapi(corpus)
    _CACHE_HASH = cache_key
    return _BM25_CACHE


def _fuzzy_tag_score(query_terms: set, tag: str, threshold: float = 0.8) -> float:
    """Fuzzy match tags to query terms (handles typos)."""
    if not tag or not query_terms:
        return 0.0

    tag_clean = tag.lower().replace("_", " ").replace(":", " ")
    max_ratio = 0.0

    for query_term in query_terms:
        ratio = SequenceMatcher(None, query_term, tag_clean).ratio()
        if ratio >= threshold:
            max_ratio = max(max_ratio, ratio)

    return max_ratio * 2.0 if max_ratio > 0 else 0.0


def _smart_snippet(body: str, query_terms: set, max_len: int = 400) -> str:
    """Extract snippet containing query terms, or fallback to first N chars."""
    if not body:
        return ""

    body = body.strip()
    if len(body) <= max_len:
        return body

    # Try to find a sentence containing query terms
    if query_terms:
        sentences = re.split(r'[.!?]\s+', body)
        for sent in sentences:
            sent_terms = _tokenize(sent)
            if sent_terms & query_terms:
                # Found relevant sentence
                if len(sent) <= max_len:
                    return sent + "…"
                return sent[:max_len].rsplit(maxsplit=1)[0] + "…"

    # Fallback: first N chars at word boundary
    return body[:max_len].rsplit(maxsplit=1)[0] + "…"


def _snippet(body: str, max_len: int = 400) -> str:
    """Legacy snippet function for backward compatibility."""
    if not body:
        return ""
    body = (body or "").strip()
    if len(body) <= max_len:
        return body
    return body[:max_len].rsplit(maxsplit=1)[0] + "…"


def load_solved_tickets(data_dir: Path) -> list[dict]:
    """Load and return list of ticket dicts from data/my_solved_tickets.json."""
    p = data_dir / "my_solved_tickets.json"
    if not p.exists():
        return []
    try:
        with open(p) as f:
            data = json.load(f)
        return data.get("tickets") or []
    except Exception:
        return []


def _ticket_search_text(t: dict) -> str:
    """Single blob for BM25/embedding: title + body + thread (how it was solved)."""
    title = (t.get("title") or "") or (t.get("display_id") or "")
    body = t.get("body") or ""
    thread = t.get("thread_text") or ""
    return f"{title}\n{body}\n{thread}".strip()


def _embed_openai(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """Call OpenAI embeddings API. Returns list of vectors (one per text)."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        from openai import OpenAI
    except ImportError:
        return []
    client = OpenAI(api_key=api_key)
    # API accepts up to 2048 inputs per request; we batch
    out = []
    batch = 100
    for i in range(0, len(texts), batch):
        chunk = [t[:8000] for t in texts[i : i + batch]]
        r = client.embeddings.create(input=chunk, model=model)
        for e in r.data:
            out.append(e.embedding)
    return out


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_or_build_embeddings(tickets: list[dict], data_dir: Path, provider: str = "openai") -> list[list[float]]:
    """
    Load cached embeddings for tickets or compute via provider (OpenAI) and cache.
    Cache key: hash of sorted ticket ids so we refresh when solved set changes.
    """
    if not tickets:
        return []
    cache_file = data_dir / "my_solved_embeddings.json"
    key_ids = sorted(t.get("id") or t.get("display_id") or str(i) for i, t in enumerate(tickets))
    cache_key = hashlib.sha256(json.dumps(key_ids, sort_keys=True).encode()).hexdigest()[:32]
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                data = json.load(f)
            if data.get("cache_key") == cache_key and len(data.get("vectors", [])) == len(tickets):
                return data["vectors"]
        except Exception:
            pass
    texts = [_ticket_search_text(t) for t in tickets]
    if provider == "openai":
        vectors = _embed_openai(texts)
    else:
        vectors = []
    if len(vectors) != len(tickets):
        return []
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_file, "w") as f:
            json.dump({"cache_key": cache_key, "vectors": vectors, "model": "text-embedding-3-small"}, f)
    except Exception:
        pass
    return vectors


def _score_tag_bonus(tag_names: list, query_terms: set[str], query_lower: str) -> float:
    """Bonus when ticket tags match the query (with fuzzy matching support)."""
    tag_bonus = 0.0
    for tag in tag_names or []:
        if not isinstance(tag, str):
            continue
        tag_lower = tag.lower().replace("_", " ").replace(":", " ")
        tag_parts = set(re.findall(r"[a-z0-9]{2,}", tag_lower))

        # Exact tag part match
        if tag_parts and query_terms and (tag_parts & query_terms):
            tag_bonus += 2.0

        # Full tag match
        if tag_lower.replace(" ", "") in query_lower.replace(" ", ""):
            tag_bonus += 1.5

        # Fuzzy match (for typos)
        fuzzy_score = _fuzzy_tag_score(query_terms, tag)
        tag_bonus += fuzzy_score

    return tag_bonus


def find_relevant(
    query: str,
    config: Config,
    top_k: Optional[int] = None,
    data_dir: Optional[Path] = None,
    use_bm25: Optional[bool] = None,
) -> list[dict]:
    """
    Given current issue text (title + description), return top_k relevant past solved tickets.
    When use_embeddings: semantic similarity (OpenAI) + min_similarity threshold to avoid weak matches.
    Else: BM25 (text) + tag bonus. Each item has: display_id, title, tag_names, body_snippet, score.
    """
    data_dir = data_dir or config.paths.data_dir
    tickets = load_solved_tickets(data_dir)
    if not tickets:
        return []

    rcfg = getattr(config, "retriever", None)
    k = top_k if top_k is not None else (rcfg.top_k if rcfg else 12)
    do_bm25 = use_bm25 if use_bm25 is not None else (rcfg.use_bm25 if rcfg else True)
    use_embeddings = rcfg.use_embeddings if rcfg else False
    min_sim = float(rcfg.min_similarity if rcfg else 0.0)
    provider = (rcfg.embedding_provider if rcfg else "openai") or "openai"

    # Preprocess query with abbreviation expansion
    preprocessed_query = _preprocess_query(query)
    query_terms = _tokenize(preprocessed_query)
    query_lower = preprocessed_query.lower()
    query_tokens = _tokenize_list(preprocessed_query)

    # Optional: vector path (semantic similarity + threshold)
    if use_embeddings and provider == "openai" and os.environ.get("OPENAI_API_KEY", "").strip():
        vectors = _load_or_build_embeddings(tickets, data_dir, provider)
        if vectors:
            query_vecs = _embed_openai([preprocessed_query[:8000]])
            if query_vecs:
                qv = query_vecs[0]
                scored_vec: list[tuple[float, dict]] = []
                for i, t in enumerate(tickets):
                    sim = _cosine_similarity(qv, vectors[i])
                    tag_bonus = _score_tag_bonus(t.get("tag_names") or [], query_terms, query_lower)
                    score = sim + 0.1 * tag_bonus
                    if min_sim > 0 and sim < min_sim:
                        continue
                    title = (t.get("title") or "") or (t.get("display_id") or "")
                    body = t.get("body") or ""
                    snippet = _smart_snippet(body, query_terms) or (t.get("thread_text") or "")[:300].rsplit(maxsplit=1)[0] + "…"
                    scored_vec.append((score, {
                        "display_id": t.get("display_id") or "",
                        "title": title,
                        "tag_names": t.get("tag_names") or [],
                        "body_snippet": snippet,
                        "score": round(score, 2),
                    }))
                scored_vec.sort(key=lambda x: -x[0])
                if scored_vec:
                    return [item for _, item in scored_vec[:k]]
                # Fall through to BM25 if no one passed threshold

    # Build corpus: one token list per ticket (title + body + thread_text)
    corpus = []
    for t in tickets:
        corpus.append(_tokenize_list(_ticket_search_text(t)))

    # Use cached BM25 index when available
    if do_bm25 and _BM25_AVAILABLE and corpus and query_tokens:
        bm25 = _get_bm25_index(corpus, len(tickets))
        bm25_scores = bm25.get_scores(query_tokens)
        # BM25 can be negative; shift to non-negative and scale for readability
        min_s = min(bm25_scores)
        if min_s < 0:
            bm25_scores = [s - min_s for s in bm25_scores]
        max_s = max(bm25_scores) or 1
        bm25_scores = [s / max_s * 10.0 for s in bm25_scores]  # scale to ~0-10
    else:
        bm25_scores = None

    scored: list[tuple[float, dict]] = []
    for i, t in enumerate(tickets):
        title = (t.get("title") or "") or (t.get("display_id") or "")
        body = t.get("body") or ""
        tag_names = t.get("tag_names") or []

        if bm25_scores is not None:
            text_score = float(bm25_scores[i])
        else:
            ticket_terms = _tokenize(_ticket_search_text(t)) | _tag_tokens(tag_names)
            overlap = len(query_terms & ticket_terms) if query_terms else 0
            title_terms = _tokenize(title)
            title_match = len(query_terms & title_terms) if query_terms else 0
            text_score = overlap + 0.5 * title_match

        tag_bonus = _score_tag_bonus(tag_names, query_terms, query_lower)
        score = text_score + tag_bonus

        # Use smart snippet extraction (context-aware); prefer body, add thread hint if present
        snippet = _smart_snippet(body, query_terms)
        if not snippet and t.get("thread_text"):
            snippet = (t.get("thread_text") or "")[:300].rsplit(maxsplit=1)[0] + "…"

        scored.append((score, {
            "display_id": t.get("display_id") or "",
            "title": title,
            "tag_names": tag_names,
            "body_snippet": snippet,
            "score": round(score, 2),
        }))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:k]]


def format_relevant_for_prompt(relevant: list[dict], max_items: int = 10) -> str:
    """Format retrieved tickets for injection into the AI prompt."""
    if not relevant:
        return "No relevant past tickets found. Use your best judgment and known skills."
    lines = []
    for i, t in enumerate(relevant[:max_items], 1):
        tid = t.get("display_id") or "?"
        title = (t.get("title") or "")[:120]
        tags = ", ".join(t.get("tag_names") or [])[:80]
        snippet = (t.get("body_snippet") or "")[:300]
        lines.append(f"{i}. [{tid}] {title}")
        if tags:
            lines.append(f"   Tags: {tags}")
        if snippet:
            lines.append(f"   Summary: {snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def format_related_ticket_links(
    relevant: list[dict],
    app_base_url: str = "https://app.devrev.ai",
    max_items: int = 5,
) -> str:
    """Format top relevant tickets as Slack links for 'Related past tickets' line."""
    if not relevant:
        return ""
    base = (app_base_url or "https://app.devrev.ai").rstrip("/")
    parts = []
    for t in relevant[:max_items]:
        display_id = (t.get("display_id") or "").strip()
        if not display_id:
            continue
        url = f"{base}/works/{display_id}"
        parts.append(f"<{url}|{display_id}>")
    if not parts:
        return ""
    return "Related past tickets: " + ", ".join(parts)
