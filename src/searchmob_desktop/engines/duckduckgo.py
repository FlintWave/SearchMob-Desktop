"""DuckDuckGo adapter, using the no-JS HTML endpoint at `html.duckduckgo.com/html`.

Mirrors the Android `DuckDuckGoAdapter.kt`: web result rows use the `.result` selector, ad rows are
`.result--ad` / `.result--ad-v2` and are excluded, and the link `href` is DuckDuckGo's redirect
(`/l/?uddg=<encoded-real-url>&...`) so we decode the `uddg` param back to the real destination.

Fail-soft: any HTTP error, timeout, or parse exception returns `[]` so a broken DDG never fails the
overall metasearch.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from searchmob_desktop.engines.proxy import fetch_bounded
from searchmob_desktop.engines.types import EngineContext, SearchResult

_ENGINE_ID = "duckduckgo"
_ENDPOINT = "https://html.duckduckgo.com/html/"
_AD_CLASSES = ("result--ad", "result--ad-v2")


async def fetch_duckduckgo(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
    """Fetch one DuckDuckGo result page and parse it. Returns `[]` on any failure."""
    params = {"q": ctx.query}
    # Tailor results to the UI language when one is set: DuckDuckGo's `kl` is a region-language code
    # (e.g. `es-es`). Absent (English / unmapped), the query stays region-neutral as before.
    if ctx.language_region is not None and ctx.language_region.ddg_kl:
        params["kl"] = ctx.language_region.ddg_kl
    try:
        body = await fetch_bounded(client, "GET", f"{_ENDPOINT}?{urlencode(params)}")
        if body is None:
            return []
        return _parse(body.decode("utf-8", errors="replace"), ctx.max_results)
    except (httpx.HTTPError, ValueError):
        return []
    except Exception:
        return []


def _parse(html: str, max_results: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    for row in soup.select(".result"):
        if not isinstance(row, Tag):
            continue
        raw_classes: object = row.get("class") or []
        classes: list[str] = (
            [str(c) for c in raw_classes] if isinstance(raw_classes, list) else [str(raw_classes)]
        )
        if any(ad in classes for ad in _AD_CLASSES):
            continue
        anchor = row.select_one(".result__a")
        if anchor is None or not isinstance(anchor, Tag):
            continue
        real_url = _decode_redirect(anchor.get("href"))
        if not real_url:
            continue
        snippet_el = row.select_one(".result__snippet")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el is not None else ""
        out.append(
            SearchResult(
                title=anchor.get_text(" ", strip=True),
                url=real_url,
                snippet=snippet,
                engine=_ENGINE_ID,
            )
        )
        if len(out) >= max_results:
            break
    return out


def _decode_redirect(href: object) -> str | None:
    """Unwrap DDG's `/l/?uddg=<encoded>` redirect, or pass through plain absolute URLs."""
    if not isinstance(href, str) or not href:
        return None
    # DDG's redirect URLs are commonly protocol-relative ("//duckduckgo.com/l/?uddg=..."). urlsplit
    # handles those, but we coax it into giving us the query without needing a scheme.
    query = urlsplit(href).query or href.split("?", 1)[-1] if "?" in href else ""
    if query:
        params = parse_qs(query)
        uddg = params.get("uddg")
        if uddg and uddg[0]:
            return uddg[0]
    return href if href.startswith(("http://", "https://")) else None
