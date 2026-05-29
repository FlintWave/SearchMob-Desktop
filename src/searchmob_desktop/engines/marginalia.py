"""Marginalia adapter, using the free public JSON API at `api.marginalia-search.com`.

Mirrors the Android `MarginaliaAdapter.kt`: the path is `/public/search/<query>` (the query goes
into the URL path, URL-encoded by the HTTP client) and the response shape is
`{results:[{url, title, description}]}`. No API key, no registration.

Fail-soft: any HTTP error, timeout, JSON decode failure, or unexpected shape returns `[]`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx

from searchmob_desktop.engines.proxy import fetch_bounded
from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "marginalia"
_ENDPOINT = "https://api.marginalia-search.com/public/search"


async def fetch_marginalia(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
    """Fetch Marginalia JSON results. Returns `[]` on any failure."""
    try:
        body = await fetch_bounded(client, "GET", f"{_ENDPOINT}/{quote(ctx.query, safe='')}")
        if body is None:
            return []
        payload: Any = json.loads(body)
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []

    out: list[SearchResult] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        title = item.get("title")
        description = item.get("description")
        out.append(
            SearchResult(
                title=str(title) if isinstance(title, str) else "",
                url=url,
                snippet=str(description) if isinstance(description, str) else "",
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= ctx.max_results:
            break
    return out
