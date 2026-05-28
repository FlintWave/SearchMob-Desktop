"""Mojeek adapter, using the no-key HTML search page at `www.mojeek.com/search`.

Mirrors the Android `MojeekAdapter.kt`: each result row is a `ul.results-standard > li`, the link
is `h2 a.title` (direct, not redirected), and the snippet is `p.s`. No API key, no cookies.

Fail-soft: any HTTP error, timeout, or parse exception returns `[]` so a broken Mojeek never fails
the overall metasearch.
"""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup, Tag

from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "mojeek"
_ENDPOINT = "https://www.mojeek.com/search"


async def fetch_mojeek(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
    """Fetch one Mojeek HTML results page and parse it. Returns `[]` on any failure."""
    try:
        response = await client.get(f"{_ENDPOINT}?{urlencode({'q': ctx.query})}")
        response.raise_for_status()
        return _parse(response.text, ctx.max_results)
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []


def _parse(html: str, max_results: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    for li in soup.select("ul.results-standard > li"):
        if not isinstance(li, Tag):
            continue
        anchor = li.select_one("h2 a.title")
        if anchor is None or not isinstance(anchor, Tag):
            continue
        href = anchor.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        snippet_el = li.select_one("p.s")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el is not None else ""
        out.append(
            SearchResult(
                title=anchor.get_text(" ", strip=True),
                url=href,
                snippet=snippet,
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= max_results:
            break
    return out
