"""Brave Search API adapter (bring-your-own key).

Mirrors the Android `BraveApiAdapter.kt`: GET `/res/v1/web/search?q=<terms>` on
`api.search.brave.com` with headers `Accept: application/json` and
`X-Subscription-Token: <api_key>`. Brave's response is `{web:{results:[{title,url,description}]}}`.

The key is BYO: callers pass `api_key=None` when the user has not configured one, in which case
the adapter short-circuits and returns `[]` without making any HTTP request. The CLI binds the key
read from `SEARCHMOB_BRAVE_API_KEY` via `functools.partial`.

Fail-soft: any HTTP error (including 401 on a bad key), timeout, or parse failure returns `[]`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "brave"
_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


async def fetch_brave_api(
    client: httpx.AsyncClient,
    ctx: EngineContext,
    api_key: str | None = None,
) -> list[SearchResult]:
    """Fetch Brave API results. Returns `[]` when `api_key` is `None` or on any failure."""
    if not api_key:
        return []
    params = {"q": ctx.query, "count": str(ctx.max_results)}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    try:
        response = await client.get(f"{_ENDPOINT}?{urlencode(params)}", headers=headers)
        response.raise_for_status()
        payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []
    web = payload.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
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
