"""Kagi Search API adapter (bring-your-own key), v1.

Mirrors the Android `KagiApiAdapter.kt`: a POST to `https://kagi.com/api/v1/search` with HTTP Bearer
auth and a JSON body `{"query": "<terms>"}`. Kagi's response carries web results under
`data.search[]`, each item with `url`, `title`, and `snippet`. (Some `data.search` items are not
search results, e.g. related-searches blocks; those lack a `url` and are skipped.)

The key is BYO: callers pass `api_key=None` when the user has not configured one, in which case the
adapter short-circuits and returns `[]` without making any HTTP request, so an inactive engine
costs nothing and never bills the user's Kagi account.

Fail-soft: any HTTP error (including 401 on a bad key), timeout, or parse failure returns `[]`.
"""

from __future__ import annotations

from typing import Any

import httpx

from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "kagi-api"
_ENDPOINT = "https://kagi.com/api/v1/search"


async def fetch_kagi_api(
    client: httpx.AsyncClient,
    ctx: EngineContext,
    api_key: str | None = None,
) -> list[SearchResult]:
    """Fetch Kagi API results. Returns `[]` when `api_key` is `None`/empty or on any failure."""
    if not api_key:
        return []
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        response = await client.post(_ENDPOINT, headers=headers, json={"query": ctx.query})
        response.raise_for_status()
        payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    search = data.get("search")
    if not isinstance(search, list):
        return []

    out: list[SearchResult] = []
    for item in search:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        title = item.get("title")
        snippet = item.get("snippet")
        out.append(
            SearchResult(
                title=str(title) if isinstance(title, str) else "",
                url=url,
                snippet=str(snippet) if isinstance(snippet, str) else "",
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= ctx.max_results:
            break
    return out
