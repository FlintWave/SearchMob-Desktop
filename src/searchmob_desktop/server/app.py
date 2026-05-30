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

import asyncio
import inspect
import json
import socket
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from ipaddress import ip_address
from urllib.parse import parse_qsl, urlsplit

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.routing import Route
from starlette.types import ASGIApp

from searchmob_desktop.engines import EngineContext, EngineFn, SearchResult, aggregate
from searchmob_desktop.engines.correct import SpellCorrector
from searchmob_desktop.engines.rank import RankingRules, RankRule, apply_ranking, host_of_url
from searchmob_desktop.engines.rank.slop_blocklist import load_slop_domains
from searchmob_desktop.engines.sort import SortMode, sort_results
from searchmob_desktop.engines.wiki_summary import SummaryBox
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


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add conservative security headers, enforce the Host allowlist, and gate the query routes.

    Three concerns, kept in one middleware so they run on every request in a single pass:

    * `Referrer-Policy: no-referrer` is the important header: without it, clicking a result would
      send the loopback URL (which contains the query) as the Referer to the destination site,
      leaking the query. The other headers are defense-in-depth, especially in network mode.
    * Host-header allowlist (DNS-rebind defense): a request whose `Host` is neither loopback, the
      bound host, nor an IP literal (when bound to a wildcard) is rejected with 400 before it
      reaches any route, so a `evil.com` rebinding `Host` cannot drive the loopback origin.
    * Network-mode token gate: when an access token is configured, a non-loopback client hitting a
      query route (`/search`, `/api/search`, `/suggest`) without the correct `?token=` is rejected
      with 403. Loopback clients and the open routes (`/`, `/opensearch.xml`, `/healthz`) bypass.
    """

    _GATED_PATHS = frozenset({"/search", "/api/search", "/suggest"})
    # State-changing routes (personalization edits from the served UI). They are owner-only: even in
    # network mode only a loopback client may POST them, so a device on the network can search but
    # cannot alter the owner's rules. A same-origin check on the Origin header blocks CSRF.
    _MUTATION_PATHS = frozenset({"/rules/domain", "/scope"})

    def __init__(
        self,
        app: ASGIApp,
        *,
        bound_host_getter: Callable[[], str],
        access_token: str | None,
        host_allowlist_enabled: bool,
        allowed_hosts: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(app)
        self._bound_host_getter = bound_host_getter
        self._access_token = access_token
        self._host_allowlist_enabled = host_allowlist_enabled
        self._allowed_hosts = allowed_hosts

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if self._host_allowlist_enabled and not host_header_allowed(
            request.headers.get("host", ""), self._bound_host_getter(), self._allowed_hosts
        ):
            return PlainTextResponse("Bad Request: host not allowed", status_code=400)

        client_host = request.client.host if request.client is not None else ""
        if (
            request.url.path in self._GATED_PATHS
            and requires_token(client_host, self._access_token)
            and request.query_params.get("token") != self._access_token
        ):
            return PlainTextResponse("Forbidden", status_code=403)

        if request.method == "POST" and request.url.path in self._MUTATION_PATHS:
            # Owner-only: only a loopback client may change personalization rules.
            if not is_loopback_host(client_host):
                return PlainTextResponse("Forbidden", status_code=403)
            # CSRF: a browser sends Origin on POST; reject if it is present and not our own origin.
            origin = request.headers.get("origin")
            if origin:
                origin_host = _hostname_only(urlsplit(origin).netloc)
                if not host_header_allowed(
                    origin_host, self._bound_host_getter(), self._allowed_hosts
                ):
                    return PlainTextResponse("Forbidden", status_code=403)

        response = await call_next(request)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


def is_loopback_host(host: str) -> bool:
    """True when `host` is a loopback address (only this machine can reach the server).

    Used as the network-mode privacy gate: when the server binds a non-loopback address (e.g.
    `0.0.0.0` for LAN/Tailscale), local search-history suggestions must not be served to clients.
    """
    h = host.strip().lower()
    return h in {"localhost", "::1"} or h.startswith("127.")


def _hostname_only(host_header: str) -> str:
    """Strip an optional `:port` and surrounding brackets from a `Host` header value.

    Returns a lowercased bare hostname. Handles IPv6 literals (`[::1]:8787` -> `::1`), the common
    `name:port` form, and a bare hostname. An empty/garbage value returns the empty string.
    """
    value = host_header.strip().lower()
    if not value:
        return ""
    if value.startswith("["):
        # Bracketed IPv6 literal, optionally followed by :port.
        end = value.find("]")
        if end != -1:
            return value[1:end]
        return value[1:]
    # IPv4 / hostname: a single trailing :port is the only colon we strip.
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _is_ip_literal(host: str) -> bool:
    """True when `host` parses as an IPv4 or IPv6 address literal (not a DNS name)."""
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def local_hostnames() -> frozenset[str]:
    """This machine's own hostname(s), lowercased, for the Host-header allowlist.

    Returns the bare hostname and, when it has no dot, the `<host>.local` mDNS form. Best-effort:
    an OS without a resolvable name yields an empty set. These are inherently "this machine" so
    allowing them does not widen the DNS-rebind surface (an attacker's foreign domain still fails).
    """
    names: set[str] = set()
    try:
        host = socket.gethostname().strip().lower()
    except OSError:
        host = ""
    if host:
        names.add(host)
        if "." not in host:
            names.add(f"{host}.local")
    return frozenset(names)


def host_header_allowed(
    host_header: str, bound_host: str, extra_allowed_hosts: frozenset[str] = frozenset()
) -> bool:
    """Decide whether a request's `Host` header is acceptable (DNS-rebind defense).

    Always allow the loopback names (`localhost`, `127.0.0.0/8`, `::1`) and the host the server is
    actually bound to. When bound to a wildcard address (`0.0.0.0` / `::`), additionally allow any
    `Host` that is an IP literal, since a LAN/Tailscale client legitimately reaches the server by
    its IP. `extra_allowed_hosts` is an explicit set of trusted hostnames (the machine's own name
    plus any the user configured, e.g. a Tailscale MagicDNS name) that are also accepted. A foreign
    DNS name (e.g. an `evil.com` used in a rebinding attack) is rejected because it is none of
    these.

    An empty `Host` header is allowed: HTTP/1.0 and some health-probe clients omit it, and it cannot
    carry a rebinding target.
    """
    name = _hostname_only(host_header)
    if not name:
        return True
    if is_loopback_host(name):
        return True
    bound = bound_host.strip().lower()
    if name == bound:
        return True
    if name in extra_allowed_hosts:
        return True
    # A wildcard bind has no single canonical hostname; accept any IP literal so LAN clients that
    # connect by address work, while still rejecting arbitrary DNS names.
    if bound in {"0.0.0.0", "::", ""} and _is_ip_literal(name):
        return True
    return False


def requires_token(client_host: str, access_token: str | None) -> bool:
    """True when a request from `client_host` must carry the access token.

    Enforcement only applies when an `access_token` is configured (network mode). Loopback clients
    are always exempt: the owner on the same machine never needs the token. Any non-loopback client
    must present it. This is factored out as a pure function so the policy is unit-testable without
    standing up a server or simulating a remote socket.
    """
    if not access_token:
        return False
    return not is_loopback_host(client_host)


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
    ranking_rules_provider: Callable[[], RankingRules] | None = None,
    ranking_rules_saver: Callable[[RankingRules], bool] | None = None,
    summary_provider: Callable[[str], Awaitable[SummaryBox | None]] | None = None,
    ai_slop_mode: str = "off",
    max_query_length: int = MAX_QUERY_LENGTH,
    max_suggestions: int = MAX_SUGGESTIONS,
    max_results: int = 10,
    timeout_seconds: float = 5.0,
    metasearch: _MetasearchFn = aggregate,
    access_token: str | None = None,
    host_allowlist_enabled: bool = True,
    allowed_hosts: frozenset[str] = frozenset(),
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

    `access_token`, when set, gates the query routes for non-loopback clients (network mode); the
    same token is baked into the OpenSearch descriptor so a browser configured off-loopback works.
    `None`/empty means loopback-only (no enforcement). `host_allowlist_enabled` defaults to True;
    set it False in tests that need to drive arbitrary `Host` headers through the app.

    `allowed_hosts` is an explicit set of trusted hostnames the Host-header allowlist accepts in
    addition to loopback / the bound host / IP literals, so a browser can reach the server by a
    friendly name (the machine's own hostname, or a configured Tailscale/mDNS name) in network mode.

    `ranking_rules_provider` is read on each search so personalization edits take effect without a
    restart; if omitted, the static `ranking_rules` is used. `ranking_rules_saver`, when provided,
    enables the served UI's editing routes (`POST /rules/domain`, `POST /scope`); those routes are
    loopback-only (a network visitor can search but not change the owner's rules).
    """
    provider: SuggestionsProvider = (
        suggestions_provider if suggestions_provider is not None else _no_suggestions
    )

    def _clamp(raw: str | None) -> str:
        if raw is None:
            return ""
        return raw[:max_query_length]

    # Read the rules through a provider so edits made from the served UI (or the in-app settings)
    # take effect on the next search without restarting the server. A static `ranking_rules` is
    # wrapped in a constant provider for back-compat (tests and callers that pass a fixed set).
    static_rules = ranking_rules if ranking_rules is not None else RankingRules()
    rules_provider: Callable[[], RankingRules] = ranking_rules_provider or (lambda: static_rules)

    async def _run_metasearch(
        query: str, sort_mode: SortMode = SortMode.FRESH_RELEVANT
    ) -> list[SearchResult]:
        if not query.strip() or not engines:
            return []
        ctx = EngineContext(query=query, max_results=max_results, timeout_seconds=timeout_seconds)
        results = await metasearch(ctx, engines)
        # Sort (relevance/date/freshness blend), then apply the user's personalization rules so the
        # served results match the in-app results and PIN/RAISE preserve the chosen order.
        ordered = sort_results(results, sort_mode, query, int(time.time() * 1000))
        return apply_ranking(
            ordered,
            rules_provider(),
            host_of=lambda r: host_of_url(r.url),
            text_of=lambda r: f"{r.title} {r.snippet}",
            slop_domains=load_slop_domains(),
            slop_mode=ai_slop_mode,
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

    def _is_owner(request: Request) -> bool:
        # The owner (a loopback client) sees the editing controls; a network-mode visitor does not,
        # because the rules-mutation routes are loopback-only. Editing also needs a saver wired.
        client_host = request.client.host if request.client is not None else ""
        return ranking_rules_saver is not None and is_loopback_host(client_host)

    async def _maybe_summary(query: str) -> SummaryBox | None:
        if summary_provider is None or not query.strip():
            return None
        try:
            return await summary_provider(query)
        except Exception:
            return None

    async def search_html(request: Request) -> Response:
        query = _clamp(request.query_params.get("q"))
        sort_mode = SortMode.from_value(request.query_params.get("sort"))
        # Fetch the contextual summary concurrently with the metasearch so the box never adds
        # latency to the results path.
        summary_task = asyncio.ensure_future(_maybe_summary(query))
        results = await _run_metasearch(query, sort_mode)
        summary = await summary_task
        body = render_results_page(
            query,
            results,
            is_safe_http_url,
            correction=_correction(query),
            rules=rules_provider(),
            editable=_is_owner(request),
            summary=summary,
            sort_mode=sort_mode.value,
        )
        return Response(body, media_type="text/html; charset=utf-8")

    def _redirect_back(request: Request) -> Response:
        # Return to the page the POST came from when it is one of our own origins; else home. 303
        # makes the browser re-fetch with GET so a refresh does not re-POST.
        referer = request.headers.get("referer", "")
        if referer:
            host = _hostname_only(urlsplit(referer).netloc)
            if host_header_allowed(host, bound_host_getter(), allowed_hosts):
                return RedirectResponse(referer, status_code=303)
        return RedirectResponse("/", status_code=303)

    async def _form(request: Request) -> dict[str, str]:
        # Parse an application/x-www-form-urlencoded body without pulling in python-multipart (which
        # Starlette's request.form() would require). Our forms are simple urlencoded posts.
        raw = await request.body()
        return dict(parse_qsl(raw.decode("utf-8", "replace")))

    async def set_domain_rule(request: Request) -> Response:
        if ranking_rules_saver is None:
            return PlainTextResponse("Personalization is read-only here.", status_code=503)
        form = await _form(request)
        domain = form.get("domain", "").strip().lower()
        action = form.get("action", "").strip().upper()
        if domain and action in RankRule.__members__:
            ranking_rules_saver(rules_provider().with_domain_rule(domain, RankRule[action]))
        return _redirect_back(request)

    async def set_scope(request: Request) -> Response:
        if ranking_rules_saver is None:
            return PlainTextResponse("Personalization is read-only here.", status_code=503)
        form = await _form(request)
        lens = form.get("lens", "").strip()
        ranking_rules_saver(rules_provider().with_active_lens(lens or None))
        return _redirect_back(request)

    async def search_json(request: Request) -> Response:
        query = _clamp(request.query_params.get("q"))
        results = await _run_metasearch(
            query, SortMode.from_value(request.query_params.get("sort"))
        )
        payload = {
            "query": query,
            "results": [asdict(result) for result in results],
            "correction": _correction(query),
        }
        return JSONResponse(payload)

    async def opensearch_xml(_request: Request) -> Response:
        body = build_descriptor(bound_host_getter(), bound_port_getter(), token=access_token)
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
        # Personalization edits from the served UI. Gated loopback-only + same-origin in the
        # middleware; no-op (503) when no saver is wired.
        Route("/rules/domain", set_domain_rule, methods=["POST"]),
        Route("/scope", set_scope, methods=["POST"]),
    ]
    middleware = [
        Middleware(
            _SecurityHeadersMiddleware,
            bound_host_getter=bound_host_getter,
            access_token=access_token,
            host_allowlist_enabled=host_allowlist_enabled,
            allowed_hosts=allowed_hosts,
        )
    ]
    return Starlette(routes=routes, middleware=middleware)
