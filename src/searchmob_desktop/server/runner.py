"""Synchronous uvicorn runner for the SearchMob Desktop local HTTP server.

Builds the Starlette app via `build_app(...)` and runs it under uvicorn with `access_log=False`.
The privacy default matches the Android Ktor server: query data never touches a log line, so the
local server is safe to leave running in the background without leaking history to disk.

Phase 2 keeps the runner intentionally simple: the caller passes the port and uvicorn binds to it.
The `port=0` (OS-assigned) path that the Android `SearchServer` uses for port-stability fallback
is deferred to Phase 7 (network mode) where the bound-port publish path needs to be wired up.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

import uvicorn

from searchmob_desktop.data.history import HistoryEntry
from searchmob_desktop.engines import EngineFn
from searchmob_desktop.engines.correct import SpellCorrector
from searchmob_desktop.engines.rank import RankingRules
from searchmob_desktop.engines.wiki_summary import SummaryBox
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.app import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    MAX_QUERY_LENGTH,
    MAX_SUGGESTIONS,
    SuggestionsProvider,
    build_app,
)


def serve(
    engines: Sequence[EngineFn],
    *,
    host: str = LOOPBACK_HOST,
    port: int = DEFAULT_PORT,
    suggestions_provider: SuggestionsProvider | None = None,
    corrector: SpellCorrector | None = None,
    ranking_rules: RankingRules | None = None,
    ranking_rules_provider: Callable[[], RankingRules] | None = None,
    ranking_rules_saver: Callable[[RankingRules], bool] | None = None,
    prefs_provider: Callable[[], UserPreferences] | None = None,
    prefs_saver: Callable[[UserPreferences], bool] | None = None,
    history_provider: Callable[[], list[HistoryEntry]] | None = None,
    history_clearer: Callable[[], bool] | None = None,
    summary_provider: Callable[[str], Awaitable[SummaryBox | None]] | None = None,
    ai_slop_mode: str = "off",
    max_query_length: int = MAX_QUERY_LENGTH,
    max_suggestions: int = MAX_SUGGESTIONS,
    max_results: int = 10,
    timeout_seconds: float = 5.0,
    access_token: str | None = None,
    allowed_hosts: frozenset[str] = frozenset(),
) -> None:
    """Build the app and run uvicorn synchronously, blocking until the server stops.

    `host` defaults to loopback (`127.0.0.1`); the parameter exists today only so the Phase 7
    network-mode toggle is a one-line plumbing change. `access_log=False` is non-negotiable: it
    is the desktop port's contribution to the same privacy guarantee the Android server makes.

    `access_token` is passed through to `build_app`: when set and the bind host is non-loopback, it
    gates the query routes for off-loopback clients. Loopback binds pass `None` and never enforce.
    """
    app = build_app(
        engines,
        bound_port_getter=lambda: port,
        bound_host_getter=lambda: host,
        suggestions_provider=suggestions_provider,
        corrector=corrector,
        ranking_rules=ranking_rules,
        ranking_rules_provider=ranking_rules_provider,
        ranking_rules_saver=ranking_rules_saver,
        prefs_provider=prefs_provider,
        prefs_saver=prefs_saver,
        history_provider=history_provider,
        history_clearer=history_clearer,
        summary_provider=summary_provider,
        ai_slop_mode=ai_slop_mode,
        max_query_length=max_query_length,
        max_suggestions=max_suggestions,
        max_results=max_results,
        timeout_seconds=timeout_seconds,
        access_token=access_token,
        allowed_hosts=allowed_hosts,
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()
