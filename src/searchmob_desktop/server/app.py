"""Starlette app factory for the SearchMob Desktop local HTTP server.

Mirrors the route surface and hardening of the Android Ktor server (`server/SearchServer.kt`):

* `GET /` returns minimal HTML with the OpenSearch advertisement so browsers can auto-add the
  engine.
* `GET /search?q=` returns an HTML results page rendered by `templates.render_results_page`.
* `GET /api/search?q=` returns `{"query": ..., "results": [...]}` as JSON.
* `GET /healthz` returns the literal text `ok`.
* `GET /opensearch.xml` returns the OpenSearch 1.1 descriptor pointing at the actual bound port.
* `GET /suggest?q=` returns the OpenSearch two-element array `["<echoed>", [suggestions]]`.

Hardening carried over from the Android audit:

* `MAX_QUERY_LENGTH` clamps `q` on every query-bearing route before it reaches the engine list
  or the suggestions provider.
* Result anchors are only rendered when the URL passes `is_safe_http_url` (http/https only);
  anything else is rendered as plain text so a hostile upstream cannot inject a `javascript:`
  link into the loopback origin.
* All interpolated text is HTML-escaped via `html.escape` in `templates.py`.
* No access logging; uvicorn is started with `access_log=False` in `runner.py`. The privacy
  default is the same as the Android server: query data never touches a log line.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from searchmob_desktop.engines import EngineContext, EngineFn, SearchResult, aggregate
from searchmob_desktop.engines.correct import SpellCorrector
from searchmob_desktop.engines.rank import RankingRules, apply_ranking, host_of_url
from searchmob_desktop.server.opensearch import build_descriptor
from searchmob_desktop.server.templates import render_home_page, render_results_page

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# Upper bound on the accepted `q` length. Mirrors the Android `MAX_QUERY_LENGTH`; longer input is
# clamped at the route boundary before it reaches the metasearch or the suggestions provider, and
# the echoed `query` field returns the clamped value (so the caller sees what was actually used).
MAX_QUERY_LENGTH = 512

# Cap on the number of suggestions the suggestions endpoint may return. Same value as Android's
# `MAX_SUGGESTIONS`; the provider is asked for at most this many and the result is also sliced.
MAX_SUGGESTIONS = 8

_SUGGESTIONS_CONTENT_TYPE = "application/x-suggestions+json"
_OPENSEARCH_CONTENT_TYPE = "application/opensearchdescription+xml"


# A source of autocomplete suggestions for a partial query. Implementations MUST be fail-soft:
# any error, timeout, or unavailable backing source returns an empty list rather than raising, so
# the `/suggest` endpoint never hangs or fails while the user is typing. Mirrors the Kotlin
# `SuggestionsProvider` interface in `server/suggest/` (typed as a plain callable here rather than
# a Protocol so a stub like `lambda q, n: ["a"]` works without an explicit cast in tests).
SuggestionsProvider = Callable[[str, int], list[str] | Awaitable[list[str]]]


def _no_suggestions(_query: str, _limit: int) -> list[str]:
    """Default suggestions provider that returns nothing.

    Used when no real source is wired (Phase 2 has neither history nor an upstream autocomplete).
    """
    return []


def is_loopback_host(host: str) -> bool:
    """True when `host` is a loopback address (only this machine can reach the server).

    Used as the network-mode privacy gate: when the server binds a non-loopback address (e.g.
    `0.0.0.0` for LAN/Tailscale), local search-history suggestions must not be served to clients.
    """
    h = host.strip().lower()
    return h in {"localhost", "::1"} or h.startswith("127.")


def is_safe_http_url(url: str) -> bool:
    """True only when `url` parses and uses an http or https scheme.

    Anything else (`javascript:`, `data:`, `file:`, a relative/scheme-less value, or a URL that
    fails to parse) is treated as unsafe so it never becomes a clickable `href`. Mirrors
    `isSafeHttpUrl` in the Android `SearchServer.kt`.
    """
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return False
    return scheme in {"http", "https"}


def _suggestions_body(query: str, suggestions: Sequence[str]) -> str:
    """Build the OpenSearch Suggestions JSON body `["<query>", ["s1", ...]]`.

    Uses `json.dumps` (not f-strings) so the browser-controlled query and every suggestion are
    JSON-escaped. The Kotlin server uses `kotlinx.serialization` here for the same reason.
    """
    return json.dumps([query, list(suggestions)], ensure_ascii=False)


# The metasearch runner is async-callable so a fake can plug in directly in tests without going
# through `aggregate`. The default plumbs through to the real `aggregate(ctx, engines)` call.
_MetasearchFn = Callable[[EngineContext, Sequence[EngineFn]], Awaitable[list[SearchResult]]]


def build_app(
    engines: Sequence[EngineFn],
    bound_port_getter: Callable[[], int],
    *,
    bound_host_getter: Callable[[], str] = lambda: LOOPBACK_HOST,
    suggestions_provider: SuggestionsProvider | None = None,
    corrector: SpellCorrector | None = None,
    ranking_rules: RankingRules | None = None,
    max_query_length: int = MAX_QUERY_LENGTH,
    max_suggestions: int = MAX_SUGGESTIONS,
    max_results: int = 10,
    timeout_seconds: float = 5.0,
    metasearch: _MetasearchFn = aggregate,
) -> Starlette:
    """Build the Starlette application that serves the SearchMob HTTP routes.

    `engines` is the list of metasearch adapters the aggregator will fan out to; an empty list is
    valid and means every query renders zero results (used in route-shape tests).

    `bound_port_getter` returns the port the server is currently bound to so the OpenSearch
    descriptor can advertise the live origin. The Android server uses the same indirection because
    the bound port is only known after `start()` returns.

    `suggestions_provider`, when provided, supplies up to `max_suggestions` strings for the
    `/suggest` endpoint. The default (`None`) wires the `NoSuggestionsProvider`-equivalent so the
    route returns `["<echoed>", []]`. Phase 3+4 will plug in history and upstream sources.
    """
    provider: SuggestionsProvider = (
        suggestions_provider if suggestions_provider is not None else _no_suggestions
    )

    def _clamp(raw: str | None) -> str:
        if raw is None:
            return ""
        return raw[:max_query_length]

    rules = ranking_rules if ranking_rules is not None else RankingRules()

    async def _run_metasearch(query: str) -> list[SearchResult]:
        if not query.strip() or not engines:
            return []
        ctx = EngineContext(query=query, max_results=max_results, timeout_seconds=timeout_seconds)
        results = await metasearch(ctx, engines)
        # Apply the user's local personalization rules (block/lower/raise/pin, lens, goggles) after
        # aggregation so the served results match the in-app results.
        return apply_ranking(
            results,
            rules,
            host_of=lambda r: host_of_url(r.url),
            text_of=lambda r: f"{r.title} {r.snippet}",
        )

    def _correction(query: str) -> str | None:
        # On-device "did you mean". `suggest` is fail-soft and already returns None when the
        # corrected query equals the input, so any non-None result is a genuine suggestion.
        if corrector is None or not query.strip():
            return None
        try:
            suggestion = corrector.suggest(query)
        except Exception:
            return None
        return suggestion.corrected if suggestion is not None else None

    async def home(_request: Request) -> Response:
        return Response(render_home_page(), media_type="text/html; charset=utf-8")

    async def healthz(_request: Request) -> Response:
        return PlainTextResponse("ok")

    async def search_html(request: Request) -> Response:
        query = _clamp(request.query_params.get("q"))
        results = await _run_metasearch(query)
        body = render_results_page(query, results, is_safe_http_url, correction=_correction(query))
        return Response(body, media_type="text/html; charset=utf-8")

    async def search_json(request: Request) -> Response:
        query = _clamp(request.query_params.get("q"))
        results = await _run_metasearch(query)
        payload = {
            "query": query,
            "results": [asdict(result) for result in results],
            "correction": _correction(query),
        }
        return JSONResponse(payload)

    async def opensearch_xml(_request: Request) -> Response:
        body = build_descriptor(bound_host_getter(), bound_port_getter())
        return Response(body, media_type=_OPENSEARCH_CONTENT_TYPE)

    async def suggest(request: Request) -> Response:
        query = _clamp(request.query_params.get("q"))
        # Blank/whitespace-only never reaches the provider, so an idle/empty address bar costs
        # nothing and echoes nothing back. Mirrors the Android route's early return.
        if not query.strip():
            body = _suggestions_body("", [])
        else:
            # A provider may be sync (returns a list) or async (returns an awaitable list);
            # accept both so a pure local source stays simple while an upstream-backed one
            # uses async HTTP without bridging.
            raw = provider(query, max_suggestions)
            resolved = await raw if inspect.isawaitable(raw) else raw
            suggestions = list(resolved)[:max_suggestions]
            body = _suggestions_body(query, suggestions)
        return Response(body, media_type=_SUGGESTIONS_CONTENT_TYPE)

    routes = [
        Route("/", home, methods=["GET"]),
        Route("/healthz", healthz, methods=["GET"]),
        Route("/search", search_html, methods=["GET"]),
        Route("/api/search", search_json, methods=["GET"]),
        Route("/opensearch.xml", opensearch_xml, methods=["GET"]),
        Route("/suggest", suggest, methods=["GET"]),
    ]
    return Starlette(routes=routes)
