"""Mwmbl adapter, using the community-curated index's public JSON API.

Mirrors the Android `MwmblAdapter.kt`: the endpoint is `/search/?s=<terms>` and the response is a
top-level JSON array. Each item's `title` and `extract` are arrays of `{value, is_bold}` fragments
that we concatenate into plain text. No API key.

Fail-soft: any HTTP error, timeout, JSON decode failure, or unexpected shape returns `[]`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx

from searchmob_desktop.engines.proxy import fetch_bounded
from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "mwmbl"
_ENDPOINT = "https://api.mwmbl.org/search/"


async def fetch_mwmbl(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
    """Fetch Mwmbl JSON results. Returns `[]` on any failure."""
    try:
        # Mwmbl's index does not parse `site:`/`OR` syntax; query with the operator-free form
        # (the scoping constraint stays locally enforced).
        query = ctx.unscoped_query or ctx.query
        body = await fetch_bounded(client, "GET", f"{_ENDPOINT}?{urlencode({'s': query})}")
        if body is None:
            return []
        payload: Any = json.loads(body)
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []

    if not isinstance(payload, list):
        return []

    out: list[SearchResult] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        out.append(
            SearchResult(
                title=_join_fragments(item.get("title")),
                url=url,
                snippet=_join_fragments(item.get("extract")),
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= ctx.max_results:
            break
    return out


def _join_fragments(field: object) -> str:
    """Concatenate Mwmbl's `[{value, is_bold}, ...]` fragment arrays into plain text."""
    if not isinstance(field, list):
        return ""
    parts: list[str] = []
    for fragment in field:
        if isinstance(fragment, dict):
            value = fragment.get("value")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts)
