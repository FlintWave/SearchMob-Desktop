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
import secrets
import socket
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, replace
from ipaddress import ip_address
from urllib.parse import parse_qsl, urlencode, urlsplit

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

from searchmob_desktop.data.history import HistoryEntry
from searchmob_desktop.engines import (
    DEFAULT_POOL_SIZE,
    AggregateOutcome,
    EngineContext,
    EngineFn,
    EngineOutcome,
    SearchResult,
    aggregate_with_status,
)
from searchmob_desktop.engines.correct import SpellCorrector
from searchmob_desktop.engines.media_intent import (
    build_actions_row,
    detect_category,
    promote_media,
)
from searchmob_desktop.engines.rank import (
    Lens,
    PersonalizationModel,
    RankingRules,
    RankRule,
    apply_ranking,
    host_of_url,
    parse_goggles,
    parse_scope_token,
    personalize_reorder,
)
from searchmob_desktop.engines.rank.personalize import query_terms, update_from_click
from searchmob_desktop.engines.rank.slop_blocklist import load_slop_domains
from searchmob_desktop.engines.region import language_region_for
from searchmob_desktop.engines.sort import SortMode, sort_results
from searchmob_desktop.engines.verticals import Vertical, default_sort, transform_query
from searchmob_desktop.engines.wiki_summary import SummaryBox
from searchmob_desktop.i18n import (
    is_supported,
    normalize_tag,
    resolve_os_locale,
    set_request_locale,
)
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.opensearch import build_descriptor
from searchmob_desktop.server.templates import (
    render_home_page,
    render_results_page,
    render_settings_page,
)
from searchmob_desktop.update import VersionTag
from searchmob_desktop.version import __version__

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# Upper bound on the accepted `q` length. Mirrors the Android `MAX_QUERY_LENGTH`; longer input is
# clamped at the route boundary before it reaches the metasearch or the suggestions provider, and
# the echoed `query` field returns the clamped value (so the caller sees what was actually used).
MAX_QUERY_LENGTH = 512

# Cap on the number of suggestions the suggestions endpoint may return. Same value as Android's
# `MAX_SUGGESTIONS`; the provider is asked for at most this many and the result is also sliced.
MAX_SUGGESTIONS = 8

# Cap on imported goggle text (bytes of the form field). Goggle files are tiny in practice; the cap
# stops a huge paste from being parsed into memory. Mirrors the in-app importer's intent.
_MAX_GOGGLE_CHARS = 512 * 1024
# How many recent history entries the served Settings page shows.
_HISTORY_VIEW_LIMIT = 50

_SUGGESTIONS_CONTENT_TYPE = "application/x-suggestions+json"
_OPENSEARCH_CONTENT_TYPE = "application/opensearchdescription+xml"

# The running app's version code, used to decide whether a persisted pending-update record is still
# newer than what is installed (so the owner-only banner self-clears after an in-place update even
# before the next background check rewrites prefs). 0 if the version string is unparseable.
_parsed_version = VersionTag.parse(__version__)
_CURRENT_VERSION_CODE = _parsed_version.to_version_code() if _parsed_version is not None else 0


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
    _MUTATION_PATHS = frozenset(
        {
            "/rules/domain",
            "/scope",
            "/language",
            "/settings/prefs",
            "/settings/lens",
            "/settings/lens/delete",
            "/settings/goggles",
            "/settings/goggles/clear",
            "/settings/history/clear",
        }
    )

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
# through the aggregator. The default plumbs through to `aggregate_with_status`, which returns the
# per-engine outcome too; a fake may return either a bare result list or an `AggregateOutcome`, and
# `_run_metasearch` accepts both (a bare list simply has no per-engine status to show).
_MetasearchFn = Callable[
    [EngineContext, Sequence[EngineFn]], Awaitable["list[SearchResult] | AggregateOutcome"]
]

# Upper bound on remembered result renders for owner click-tracking (one per recent owner search).
# Small on purpose: only the most recent few pages need clickable tracking links at once.
_RENDER_CACHE_MAX = 64


@dataclass(frozen=True)
class _RenderedResults:
    """One owner-rendered result page: the query and the displayed (url, host) order.

    Held briefly in memory so the owner-only `/click` endpoint can resolve a click to its result and
    its skipped-above neighbors using server state, never a client-supplied URL. Never persisted.
    """

    query: str
    items: list[tuple[str, str | None]]


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
    personalization_provider: Callable[[], PersonalizationModel | None] | None = None,
    personalization_saver: Callable[[PersonalizationModel], bool] | None = None,
    prefs_provider: Callable[[], UserPreferences] | None = None,
    prefs_saver: Callable[[UserPreferences], bool] | None = None,
    history_provider: Callable[[], list[HistoryEntry]] | None = None,
    history_clearer: Callable[[], bool] | None = None,
    summary_provider: Callable[[str], Awaitable[SummaryBox | None]] | None = None,
    ai_slop_mode: str = "off",
    max_query_length: int = MAX_QUERY_LENGTH,
    max_suggestions: int = MAX_SUGGESTIONS,
    max_results: int = DEFAULT_POOL_SIZE,
    timeout_seconds: float = 5.0,
    metasearch: _MetasearchFn = aggregate_with_status,
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

    `prefs_provider` is read on each request so the served Settings page reflects live preferences
    and so toggles (AI-slop filter mode, Wikipedia summary, default sort) take effect without a
    restart. `prefs_saver`, when provided, enables the loopback-only `GET /settings` page and its
    `POST /settings/prefs` route; without it, no settings page is served. Like the ranking routes
    these are owner-only (loopback) and same-origin guarded.
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

    # Per-app, in-memory map of recent owner renders (render id -> displayed order), used only to
    # resolve owner clicks on the served page back to their result for the `/click` endpoint.
    _render_cache: OrderedDict[str, _RenderedResults] = OrderedDict()

    def _load_prefs() -> UserPreferences | None:
        # Read live preferences per request so the served Settings toggles apply without a restart.
        # Fail-soft: any error reading prefs falls back to the static defaults passed to build_app.
        if prefs_provider is None:
            return None
        try:
            return prefs_provider()
        except Exception:
            return None

    def _accept_language_locale(request: Request) -> str | None:
        # First supported language from the visitor's Accept-Language header (q-values ignored; the
        # browser already lists them best-first). Used when the owner has not pinned a UI language.
        header = request.headers.get("accept-language", "")
        for part in header.split(","):
            tag = part.split(";", 1)[0].strip()
            if is_supported(tag):
                return normalize_tag(tag)
        return None

    def _resolve_locale(request: Request) -> str:
        # The page language for this request: the owner's pinned `language` pref wins; absent that,
        # the visitor's Accept-Language; absent that, the server's OS locale (else English). Set as
        # the per-request override so the templates' bare `tr(...)` calls localize without threading
        # a locale through every helper, and isolated to this request task (never the GUI's locale).
        prefs = _load_prefs()
        if prefs is not None and prefs.language and is_supported(prefs.language):
            locale = normalize_tag(prefs.language)
        else:
            locale = _accept_language_locale(request) or resolve_os_locale()
        set_request_locale(locale)
        return locale

    async def _run_metasearch(
        query: str,
        sort_mode: SortMode = SortMode.FRESH_RELEVANT,
        vertical: Vertical = Vertical.WEB,
        *,
        model: PersonalizationModel | None = None,
        active_lens: str | None = None,
        locale: str | None = None,
        # The contextual-summary task, already in flight, so media promotion can read the resolved
        # entity's category and lift its canonical platforms before the user's domain rules run
        # (pin/raise/block still win). None disables promotion (e.g. the JSON endpoint).
        summary_task: Awaitable[SummaryBox | None] | None = None,
    ) -> tuple[list[SearchResult], tuple[EngineOutcome, ...]]:
        if not query.strip() or not engines:
            return [], ()
        # Scope the query for the chosen vertical (a `site:` OR group the engines understand); the
        # original query still drives sort/summary/correction so freshness keywords are detected.
        scoped = transform_query(query, vertical)
        # Tailor results to the UI language: a non-English locale carries per-engine region/language
        # params (DuckDuckGo `kl`, Brave country/search_lang/ui_lang); None leaves results neutral.
        ctx = EngineContext(
            query=scoped,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            language_region=language_region_for(locale),
        )
        # The runner returns either a bare result list (a test fake) or an `AggregateOutcome` with
        # the per-engine status (the real `aggregate_with_status`); accept both.
        raw = await metasearch(ctx, engines)
        if isinstance(raw, AggregateOutcome):
            results, engine_outcomes = raw.results, raw.engines
        else:
            results, engine_outcomes = raw, ()
        # The AI-slop filter mode is taken live from prefs when wired, so the Settings toggle takes
        # effect on the next search; otherwise the static build-time value is used.
        prefs = _load_prefs()
        slop_mode = prefs.ai_slop_mode if prefs is not None else ai_slop_mode
        # Sort (relevance/date/freshness blend), then nudge by the owner's learned click model (only
        # when a model is passed, which the caller does for the loopback owner), then apply the
        # user's rules so the served results match the in-app results and PIN/RAISE preserve order.
        now_ms = int(time.time() * 1000)
        ordered = sort_results(results, sort_mode, query, now_ms)
        if model is not None:
            ordered = personalize_reorder(
                ordered, lambda r: host_of_url(r.url), query, model, now_ms
            )
        # Media promotion: for a resolved media entity, nudge its canonical platforms up (bounded),
        # after relevance/personalization and before the user's rules, so pin/raise/block still win.
        # The summary is fetched concurrently; awaiting it here adds no latency past the metasearch.
        media_on = prefs is None or prefs.media_actions_enabled
        if media_on and summary_task is not None:
            media_summary = await summary_task
            category = (
                detect_category(media_summary.description) if media_summary is not None else None
            )
            if category is not None:
                ordered = promote_media(ordered, category)
        # An inline `+name` scope token (parsed from the query at the route) overrides the saved
        # active scope for this one request only; the persisted selection is never written.
        rules = rules_provider()
        if active_lens is not None:
            rules = rules.with_active_lens(active_lens)
        ranked = apply_ranking(
            ordered,
            rules,
            host_of=lambda r: host_of_url(r.url),
            text_of=lambda r: f"{r.title} {r.snippet}",
            slop_domains=load_slop_domains(),
            slop_mode=slop_mode,
        )
        return ranked, engine_outcomes

    def _owner_model(request: Request) -> PersonalizationModel | None:
        # The learned model for the loopback owner, or None when off / disabled / not the owner.
        # Used to personalize the owner's results and to gate click-tracking links and `/click`.
        if personalization_provider is None or not _is_loopback_request(request):
            return None
        try:
            return personalization_provider()
        except Exception:
            return None

    def _register_render(query: str, results: list[SearchResult]) -> str:
        # Remember the exact displayed order under a fresh, unguessable id so an owner click can be
        # matched to its result (and its skipped-above neighbors) without trusting any client input.
        # Bounded and in-memory only; never persisted.
        rid = secrets.token_urlsafe(9)
        items = [(r.url, host_of_url(r.url)) for r in results]
        _render_cache[rid] = _RenderedResults(query=query, items=items)
        while len(_render_cache) > _RENDER_CACHE_MAX:
            _render_cache.popitem(last=False)  # evict the oldest render
        return rid

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

    async def home(request: Request) -> Response:
        locale = _resolve_locale(request)
        body = render_home_page(
            settings_link=_is_settings_owner(request),
            rules=rules_provider(),
            editable=_is_owner(request),
            update_banner=_owner_update_banner(request),
            locale=locale,
        )
        return Response(body, media_type="text/html; charset=utf-8")

    async def healthz(_request: Request) -> Response:
        return PlainTextResponse("ok")

    def _is_owner(request: Request) -> bool:
        # The owner (a loopback client) sees the editing controls; a network-mode visitor does not,
        # because the rules-mutation routes are loopback-only. Editing also needs a saver wired.
        client_host = request.client.host if request.client is not None else ""
        return ranking_rules_saver is not None and is_loopback_host(client_host)

    def _is_loopback_request(request: Request) -> bool:
        # Loopback = the owner's own machine. Gates applying the learned personalization model so it
        # never reorders results for a network visitor (and never exposes the owner's bubble).
        client_host = request.client.host if request.client is not None else ""
        return is_loopback_host(client_host)

    def _owner_update_banner(request: Request) -> tuple[str, str] | None:
        # The "update available" banner is owner-only: a network visitor cannot install anything and
        # should not learn the owner's version. Read live from prefs (set by the background check),
        # and only show it when the pending version still parses newer than what is installed.
        if not _is_loopback_request(request):
            return None
        prefs = _load_prefs()
        if prefs is None:
            return None
        version, url = prefs.pending_update_version, prefs.pending_update_url
        if not version or not url:
            return None
        parsed = VersionTag.parse(version)
        if parsed is None or parsed.to_version_code() <= _CURRENT_VERSION_CODE:
            return None
        return version, url

    async def _maybe_summary(query: str) -> SummaryBox | None:
        if summary_provider is None or not query.strip():
            return None
        # The Wikipedia summary card honors the live pref when wired: a caller that always passes a
        # provider lets the Settings toggle control it (prefs absent = always on, back-compat).
        prefs = _load_prefs()
        if prefs is not None and not prefs.summary_enabled:
            return None
        try:
            return await summary_provider(query)
        except Exception:
            return None

    def _is_settings_owner(request: Request) -> bool:
        # The Settings page and its writes are owner-only: a loopback client, and only when a prefs
        # saver is wired (so there is something to persist to).
        client_host = request.client.host if request.client is not None else ""
        return prefs_saver is not None and is_loopback_host(client_host)

    async def search_html(request: Request) -> Response:
        locale = _resolve_locale(request)
        raw_query = _clamp(request.query_params.get("q"))
        # An inline `+name` token applies a saved scope to this one search, additively and without
        # persisting it. The engines, summary, and correction run on the cleaned query; the original
        # text is echoed in the box so the token round-trips and re-running re-applies the scope.
        query, scope = parse_scope_token(raw_query, rules_provider())
        vertical = Vertical.from_value(request.query_params.get("vertical"))
        # An explicit `?sort=` wins. Absent it, a non-default vertical keeps its sensible default
        # (e.g. News favors Date); the plain Web view honors the user's configured default sort from
        # prefs when wired, so the Settings choice is what the browser sees by default.
        sort_param = request.query_params.get("sort")
        prefs = _load_prefs()
        if sort_param:
            sort_mode = SortMode.from_value(sort_param)
        elif vertical is Vertical.WEB and prefs is not None:
            sort_mode = SortMode.from_value(prefs.sort_mode)
        else:
            sort_mode = default_sort(vertical)
        # Fetch the contextual summary concurrently with the metasearch so the box never adds
        # latency to the results path.
        summary_task = asyncio.ensure_future(_maybe_summary(query))
        model = _owner_model(request)
        results, engine_outcomes = await _run_metasearch(
            query,
            sort_mode,
            vertical,
            model=model,
            active_lens=scope,
            locale=locale,
            summary_task=summary_task,
        )
        summary = await summary_task
        # For a resolved media entity, build the "Listen/Watch/Read/Play on" actions row (the same
        # toggle and the same Wikipedia lookup the summary card uses; the platform links are local).
        actions_row = None
        if (prefs is None or prefs.media_actions_enabled) and summary is not None:
            category = detect_category(summary.description)
            if category is not None:
                actions_row = build_actions_row(category, summary.title, summary.url)
        # When personalization is on for the owner, route result links through `/click` so a click
        # can train the model; everyone else (and a disabled owner) gets the plain destination link.
        link_builder: Callable[[int, str], str] | None = None
        if model is not None and results:
            rid = _register_render(query, results)
            link_builder = lambda pos, _url, _rid=rid: f"/click?rid={_rid}&pos={pos}"  # noqa: E731
        body = render_results_page(
            raw_query,
            results,
            is_safe_http_url,
            correction=_correction(query),
            rules=rules_provider(),
            editable=_is_owner(request),
            summary=summary,
            sort_mode=sort_mode.value,
            vertical=vertical.value,
            settings_link=_is_settings_owner(request),
            link_builder=link_builder,
            update_banner=_owner_update_banner(request),
            locale=locale,
            # Per-engine status is diagnostic and owner-only: never shown to a LAN visitor, and
            # the same loopback gate the editing controls use.
            engine_status=engine_outcomes if _is_owner(request) else (),
            actions_row=actions_row,
        )
        return Response(body, media_type="text/html; charset=utf-8")

    async def click(request: Request) -> Response:
        # Owner-only redirector that learns from a click on the served results page. It resolves the
        # destination from server-side render state (never a caller-supplied URL), so it cannot be
        # an open redirect, and it trains only the loopback owner's model.
        if not _is_loopback_request(request):
            return PlainTextResponse("not found", status_code=404)
        render = _render_cache.get(request.query_params.get("rid", ""))
        if render is None:
            return RedirectResponse("/", status_code=303)
        try:
            pos = int(request.query_params.get("pos", ""))
        except ValueError:
            return RedirectResponse("/", status_code=303)
        if pos < 0 or pos >= len(render.items):
            return RedirectResponse("/", status_code=303)
        dest_url, _host = render.items[pos]
        if not is_safe_http_url(dest_url):
            return RedirectResponse("/", status_code=303)
        if personalization_provider is not None and personalization_saver is not None:
            model = _owner_model(request)
            if model is not None:
                try:
                    hosts = [host for _u, host in render.items]
                    update_from_click(
                        model, hosts, pos, query_terms(render.query), int(time.time() * 1000)
                    )
                    personalization_saver(model)
                except Exception:
                    pass  # Learning is best-effort; never block the navigation on it.
        return RedirectResponse(dest_url, status_code=302)

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

    def _redirect_to_results(form: dict[str, str]) -> Response:
        # Return to the results page a scope/rule POST came from, rebuilt from the hidden q/sort/
        # vertical fields the served forms carry, so the new ranking is applied to the same search
        # instead of dumping the owner on the home page. (Our no-referrer policy strips the Referer,
        # so the Referer-based _redirect_back always fell through to "/".) No query - the home-page
        # or settings scope selector - falls back to home. 303 -> re-fetch with GET.
        query = form.get("q", "").strip()
        if not query:
            return RedirectResponse("/", status_code=303)
        sort_mode = form.get("sort", "").strip() or "fresh"
        vertical = form.get("vertical", "").strip() or "web"
        target = "/search?" + urlencode({"q": query, "vertical": vertical, "sort": sort_mode})
        return RedirectResponse(target, status_code=303)

    async def set_domain_rule(request: Request) -> Response:
        if ranking_rules_saver is None:
            return PlainTextResponse("Personalization is read-only here.", status_code=503)
        form = await _form(request)
        domain = form.get("domain", "").strip().lower()
        action = form.get("action", "").strip().upper()
        if domain and action in RankRule.__members__:
            ranking_rules_saver(rules_provider().with_domain_rule(domain, RankRule[action]))
        return _redirect_to_results(form)

    async def set_scope(request: Request) -> Response:
        if ranking_rules_saver is None:
            return PlainTextResponse("Personalization is read-only here.", status_code=503)
        form = await _form(request)
        lens = form.get("lens", "").strip()
        ranking_rules_saver(rules_provider().with_active_lens(lens or None))
        return _redirect_to_results(form)

    def _csv_tuple(raw: str) -> tuple[str, ...]:
        # Split a comma- or newline-separated field into clean, de-duplicated, lowercased entries.
        seen: dict[str, None] = {}
        for piece in raw.replace("\n", ",").split(","):
            item = piece.strip().lower()
            if item:
                seen.setdefault(item, None)
        return tuple(seen)

    async def set_lens(request: Request) -> Response:
        # Create or update a lens (replace by exact name). A blank name is ignored. Redirects to the
        # Settings page so the saved lens shows immediately.
        if ranking_rules_saver is None:
            return PlainTextResponse("Settings are read-only here.", status_code=503)
        form = await _form(request)
        name = form.get("name", "").strip()
        if name:
            lens = Lens(
                name=name,
                include_domains=_csv_tuple(form.get("include_domains", "")),
                exclude_domains=_csv_tuple(form.get("exclude_domains", "")),
                include_keywords=_csv_tuple(form.get("include_keywords", "")),
                exclude_keywords=_csv_tuple(form.get("exclude_keywords", "")),
            )
            ranking_rules_saver(rules_provider().with_lens(lens))
        return RedirectResponse("/settings?saved=1", status_code=303)

    async def delete_lens(request: Request) -> Response:
        if ranking_rules_saver is None:
            return PlainTextResponse("Settings are read-only here.", status_code=503)
        form = await _form(request)
        name = form.get("name", "").strip()
        if name:
            ranking_rules_saver(rules_provider().without_lens(name))
        return RedirectResponse("/settings?saved=1", status_code=303)

    async def import_goggles(request: Request) -> Response:
        # Parse Brave-style goggle text and append the rules to the existing set (mirrors the in-app
        # importer). The text is size-capped before parsing so a huge paste cannot exhaust memory.
        if ranking_rules_saver is None:
            return PlainTextResponse("Settings are read-only here.", status_code=503)
        form = await _form(request)
        text = form.get("goggles", "")[:_MAX_GOGGLE_CHARS]
        parsed = parse_goggles(text)
        if parsed:
            ranking_rules_saver(rules_provider().with_added_goggles(tuple(parsed)))
        return RedirectResponse("/settings?saved=1", status_code=303)

    async def clear_goggles(request: Request) -> Response:
        if ranking_rules_saver is None:
            return PlainTextResponse("Settings are read-only here.", status_code=503)
        ranking_rules_saver(rules_provider().with_goggles(()))
        return RedirectResponse("/settings?saved=1", status_code=303)

    async def clear_history(_request: Request) -> Response:
        if history_clearer is None:
            return PlainTextResponse("History is not available here.", status_code=503)
        history_clearer()
        return RedirectResponse("/settings?saved=1", status_code=303)

    async def settings_page(request: Request) -> Response:
        # Owner-only: the page is served to a loopback client when a prefs saver is wired. A network
        # visitor (or a build with no saver) gets 404 so the surface is invisible off-loopback.
        if not _is_settings_owner(request):
            return PlainTextResponse("Not found", status_code=404)
        locale = _resolve_locale(request)
        prefs = _load_prefs() or UserPreferences()
        saved = request.query_params.get("saved") == "1"
        history: list[HistoryEntry] | None = None
        if history_provider is not None:
            try:
                history = list(history_provider())[:_HISTORY_VIEW_LIMIT]
            except Exception:
                history = []
        body = render_settings_page(
            prefs,
            rules_provider(),
            saved=saved,
            history=history,
            history_clearable=history_clearer is not None,
            locale=locale,
        )
        return Response(body, media_type="text/html; charset=utf-8")

    async def set_language(request: Request) -> Response:
        # Persist the chosen UI language (a shipped locale tag, or empty to follow the OS). It is
        # loopback-only via the same owner gate as the other preference writes; redirects so the
        # interface re-renders in the new language. Unknown tags are ignored (left unchanged).
        if prefs_saver is None:
            return PlainTextResponse("Settings are read-only here.", status_code=503)
        form = await _form(request)
        chosen = form.get("lang", "").strip()
        if chosen and not is_supported(chosen):
            return _redirect_back(request)
        current = _load_prefs() or UserPreferences()
        prefs_saver(replace(current, language=normalize_tag(chosen) if chosen else ""))
        return _redirect_back(request)

    _BOOL_FORM = {"on", "true", "1", "yes"}

    async def set_prefs(request: Request) -> Response:
        if prefs_saver is None:
            return PlainTextResponse("Settings are read-only here.", status_code=503)
        form = await _form(request)
        current = _load_prefs() or UserPreferences()
        # Only accept known, valid values; anything unexpected leaves that field unchanged. A
        # checkbox absent from the POST means unchecked (HTML omits unchecked checkboxes).
        sort_mode = form.get("sort_mode", current.sort_mode)
        if sort_mode not in {"relevance", "date", "fresh"}:
            sort_mode = current.sort_mode
        slop = form.get("ai_slop_mode", current.ai_slop_mode)
        if slop not in {"off", "downrank", "hide"}:
            slop = current.ai_slop_mode
        updated = replace(
            current,
            sort_mode=sort_mode,
            ai_slop_mode=slop,
            summary_enabled=form.get("summary_enabled", "").lower() in _BOOL_FORM,
            media_actions_enabled=form.get("media_actions_enabled", "").lower() in _BOOL_FORM,
            upstream_suggestions_enabled=(
                form.get("upstream_suggestions_enabled", "").lower() in _BOOL_FORM
            ),
        )
        prefs_saver(updated)
        return RedirectResponse("/settings?saved=1", status_code=303)

    async def search_json(request: Request) -> Response:
        locale = _resolve_locale(request)
        raw_query = _clamp(request.query_params.get("q"))
        # Same inline `+name` scope token as the HTML route: applied to this request only, with the
        # engines/correction run on the cleaned query and the original echoed back as `query`.
        query, scope = parse_scope_token(raw_query, rules_provider())
        vertical = Vertical.from_value(request.query_params.get("vertical"))
        sort_param = request.query_params.get("sort")
        sort_mode = SortMode.from_value(sort_param) if sort_param else default_sort(vertical)
        results, _ = await _run_metasearch(
            query,
            sort_mode,
            vertical,
            model=_owner_model(request),
            active_lens=scope,
            locale=locale,
        )
        payload = {
            "query": raw_query,
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
        # Owner-only click redirector that trains the personalization model (loopback-only; a
        # non-owner gets 404, and it only redirects to a server-recorded result URL).
        Route("/click", click, methods=["GET"]),
        # Personalization edits from the served UI. Gated loopback-only + same-origin in the
        # middleware; no-op (503) when no saver is wired.
        Route("/rules/domain", set_domain_rule, methods=["POST"]),
        Route("/scope", set_scope, methods=["POST"]),
        Route("/language", set_language, methods=["POST"]),
        # Settings page + preference writes (owner-only; 404 / 503 otherwise).
        Route("/settings", settings_page, methods=["GET"]),
        Route("/settings/prefs", set_prefs, methods=["POST"]),
        # Lens management from the Settings page (owner-only; domain rules reuse /rules/domain and
        # the active-lens selector reuses /scope).
        Route("/settings/lens", set_lens, methods=["POST"]),
        Route("/settings/lens/delete", delete_lens, methods=["POST"]),
        # Goggles import / clear and history clear (owner-only).
        Route("/settings/goggles", import_goggles, methods=["POST"]),
        Route("/settings/goggles/clear", clear_goggles, methods=["POST"]),
        Route("/settings/history/clear", clear_history, methods=["POST"]),
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
