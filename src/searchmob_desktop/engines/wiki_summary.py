"""Contextual Wikipedia summary box: the lead paragraph of a related article for some queries.

A two-step, fail-soft flow (see the research notes):

1. Resolve a candidate article title from the query via the Action API OpenSearch endpoint, then
   apply a relevance gate so an only-loosely-related page never produces a box.
2. Fetch that title's REST summary (`/api/rest_v1/page/summary/{title}`), reject disambiguation
   pages and empty extracts, and truncate the lead to a box-sized snippet.

The box is a sibling of the ranked results, not a result itself; callers render it above the list.
Everything is fail-soft: any timeout, non-200, parse error, low-confidence match, long/navigational
query, or disambiguation yields `None` and no box. It runs through the same privacy client the
engines use (no cookies, no referrer, rotated UA), adding at most one extra outbound call per search
to `en.wikipedia.org`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx

from searchmob_desktop.engines.proxy import fetch_bounded, make_privacy_client

_OPENSEARCH_ENDPOINT = "https://en.wikipedia.org/w/api.php"
_SUMMARY_ENDPOINT = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# Queries longer than this are full-text / question intents, not entity lookups; skip the box.
_MAX_QUERY_TOKENS = 6
_MAX_QUERY_CHARS = 60
# Trim the lead extract to a box-sized snippet (a sentence or two).
_MAX_EXTRACT_CHARS = 320
# Token-overlap threshold for accepting a loosely-matching title.
_MIN_JACCARD = 0.6


@dataclass(frozen=True)
class SummaryBox:
    """A knowledge-panel-style summary for the query, shown above the results."""

    title: str
    description: str
    extract: str
    url: str
    thumbnail_url: str | None = None


def _normalize(text: str) -> str:
    """Lowercase, strip diacritics/punctuation, drop a trailing parenthetical, collapse spaces."""
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)  # "Everest (2015 film)" -> "Everest"
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", stripped.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if t}


def is_entity_like_query(query: str) -> bool:
    """True when the query looks like an entity lookup rather than a question / navigation."""
    q = query.strip()
    if not q or len(q) > _MAX_QUERY_CHARS:
        return False
    if len(q.split()) > _MAX_QUERY_TOKENS:
        return False
    # URL-ish or navigational input is never an entity lookup.
    return not ("://" in q or q.startswith(("http", "www.")) or (" " not in q and "." in q))


def is_confident_match(query: str, title: str) -> bool:
    """Whether `title` is a confident match for `query` (normalized equality / token overlap)."""
    qn, tn = _normalize(query), _normalize(title)
    if not qn or not tn:
        return False
    if qn == tn:
        return True
    qt, tt = _tokens(query), _tokens(title)
    if not qt or not tt:
        return False
    if qt <= tt or tt <= qt:  # one is a subset of the other
        return True
    overlap = len(qt & tt) / len(qt | tt)
    return overlap >= _MIN_JACCARD


def _truncate(extract: str) -> str:
    extract = extract.strip()
    if len(extract) <= _MAX_EXTRACT_CHARS:
        return extract
    head = extract[:_MAX_EXTRACT_CHARS]
    # Prefer to cut at the last sentence end, else the last space, then add an ellipsis.
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    if cut >= _MAX_EXTRACT_CHARS // 2:
        return head[: cut + 1]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip() + "…"


async def _resolve_title(client: httpx.AsyncClient, query: str) -> str | None:
    params = {
        "action": "opensearch",
        "format": "json",
        "search": query,
        "limit": "3",
        "namespace": "0",
        "redirects": "resolve",
    }
    try:
        body = await fetch_bounded(client, "GET", f"{_OPENSEARCH_ENDPOINT}?{urlencode(params)}")
        if body is None:
            return None
        payload = json.loads(body)
    except (httpx.HTTPError, ValueError):
        return None
    except Exception:
        return None
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return None
    titles = [t for t in payload[1] if isinstance(t, str) and t]
    return titles[0] if titles else None


async def _fetch_rest_summary(client: httpx.AsyncClient, title: str) -> SummaryBox | None:
    url = _SUMMARY_ENDPOINT + quote(title.replace(" ", "_"), safe="")
    try:
        body = await fetch_bounded(client, "GET", url)
        if body is None:
            return None
        data = json.loads(body)
    except (httpx.HTTPError, ValueError):
        return None
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("type") == "disambiguation":
        return None
    extract = data.get("extract")
    if not isinstance(extract, str) or not extract.strip():
        return None
    page_url = ""
    content_urls = data.get("content_urls")
    if isinstance(content_urls, dict):
        desktop = content_urls.get("desktop")
        if isinstance(desktop, dict) and isinstance(desktop.get("page"), str):
            page_url = desktop["page"]
    thumb = data.get("thumbnail")
    thumb_url = thumb.get("source") if isinstance(thumb, dict) else None
    return SummaryBox(
        title=str(data.get("title") or title),
        description=str(data.get("description") or ""),
        extract=_truncate(extract),
        url=page_url,
        thumbnail_url=thumb_url if isinstance(thumb_url, str) else None,
    )


async def fetch_summary(client: httpx.AsyncClient, query: str) -> SummaryBox | None:
    """Return a contextual summary box for `query`, or `None` when one is not warranted."""
    if not is_entity_like_query(query):
        return None
    title = await _resolve_title(client, query)
    if title is None or not is_confident_match(query, title):
        return None
    return await _fetch_rest_summary(client, title)


async def summary_for_query(query: str, timeout: float = 2.0) -> SummaryBox | None:
    """Convenience provider: open a short-lived privacy client and fetch the summary, fail-soft."""
    try:
        async with make_privacy_client(timeout) as client:
            return await fetch_summary(client, query)
    except Exception:
        return None
