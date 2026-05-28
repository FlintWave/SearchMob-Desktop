"""Mojeek Search API adapter (bring-your-own key).

Mirrors the Android `MojeekApiAdapter.kt`: GET `/search?q=<terms>&api_key=<key>&fmt=json` on
`api.mojeek.com`. Response is `{response:{results:[{title,url,desc}]}}`.

Caveat to surface for reviewers: Mojeek's API takes the key in the URL query string (not a header).
That is upstream's design, not a client flaw, but it means the key may appear in upstream-side
access logs. There is no header-based alternative supported by Mojeek's API today.

The key is BYO: callers pass `api_key=None` when the user has not configured one, in which case
the adapter short-circuits and returns `[]` without making any HTTP request. The CLI binds the key
read from `SEARCHMOB_MOJEEK_API_KEY` via `functools.partial`.

When this adapter is active it is intended to supersede the free `mojeek` HTML scraper so the same
upstream index is not queried twice; that policy is enforced by the CLI's engine list assembly, not
here.

Fail-soft: any HTTP error, timeout, JSON decode failure, or unexpected shape returns `[]`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "mojeek-api"
_ENDPOINT = "https://api.mojeek.com/search"


async def fetch_mojeek_api(
    client: httpx.AsyncClient,
    ctx: EngineContext,
    api_key: str | None = None,
) -> list[SearchResult]:
    """Fetch Mojeek API results. Returns `[]` when `api_key` is `None` or on any failure."""
    if not api_key:
        return []
    params = {"q": ctx.query, "api_key": api_key, "fmt": "json", "t": str(ctx.max_results)}
    try:
        response = await client.get(f"{_ENDPOINT}?{urlencode(params)}")
        response.raise_for_status()
        payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []
    inner = payload.get("response")
    if not isinstance(inner, dict):
        return []
    results = inner.get("results")
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
        desc = item.get("desc")
        out.append(
            SearchResult(
                title=str(title) if isinstance(title, str) else "",
                url=url,
                snippet=str(desc) if isinstance(desc, str) else "",
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= ctx.max_results:
            break
    return out
