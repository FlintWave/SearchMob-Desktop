"""Wikipedia adapter, using the OpenSearch JSON endpoint.

`action=opensearch` returns a four-element array `[query, titles, snippets, urls]`. We zip the
three result arrays into `SearchResult` rows. The endpoint takes a `limit` so we ask for at most
`ctx.max_results`.

Fail-soft: any HTTP error, timeout, JSON decode failure, or unexpected shape returns `[]`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx

from searchmob_desktop.engines.proxy import fetch_bounded
from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "wikipedia"
_ENDPOINT = "https://en.wikipedia.org/w/api.php"


async def fetch_wikipedia(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
    """Fetch Wikipedia OpenSearch results. Returns `[]` on any failure."""
    params = {
        "action": "opensearch",
        "format": "json",
        # Wikipedia's title index does not parse `site:`/`OR` syntax; a vertical's scoping clause
        # as literal text matches nothing, so query with the operator-free form. The constraint is
        # still enforced locally over the merged results.
        "search": ctx.unscoped_query or ctx.query,
        "limit": str(ctx.max_results),
    }
    try:
        body = await fetch_bounded(client, "GET", f"{_ENDPOINT}?{urlencode(params)}")
        if body is None:
            return []
        payload: Any = json.loads(body)
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []

    if not isinstance(payload, list) or len(payload) < 4:
        return []
    titles = payload[1]
    snippets = payload[2]
    urls = payload[3]
    if not (isinstance(titles, list) and isinstance(snippets, list) and isinstance(urls, list)):
        return []

    out: list[SearchResult] = []
    for title, snippet, url in zip(titles, snippets, urls, strict=False):
        if not isinstance(url, str) or not url:
            continue
        out.append(
            SearchResult(
                title=str(title) if title is not None else "",
                url=url,
                snippet=str(snippet) if snippet is not None else "",
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= ctx.max_results:
            break
    return out
