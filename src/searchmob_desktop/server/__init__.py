"""Local HTTP server so a browser can use SearchMob Desktop as its default search engine.

Mirrors the route surface of the Android Ktor server (`server/SearchServer.kt`): `GET /`,
`GET /search`, `GET /api/search`, `GET /healthz`, `GET /opensearch.xml`, `GET /suggest`. The Kotlin
hardening (length cap, scheme allowlist for anchor rendering, no access logs, loopback default) is
carried over here.

Public surface: `build_app(...)` for the Starlette factory and `serve(...)` for the synchronous
uvicorn runner. Importers should depend on `searchmob_desktop.server`, not the submodules.
"""

from __future__ import annotations

from searchmob_desktop.server.app import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    MAX_QUERY_LENGTH,
    MAX_SUGGESTIONS,
    SuggestionsProvider,
    build_app,
    host_header_allowed,
    is_loopback_host,
    is_safe_http_url,
    local_hostnames,
    presented_token,
    requires_token,
    token_matches,
)
from searchmob_desktop.server.runner import serve

__all__ = [
    "DEFAULT_PORT",
    "LOOPBACK_HOST",
    "MAX_QUERY_LENGTH",
    "MAX_SUGGESTIONS",
    "SuggestionsProvider",
    "build_app",
    "host_header_allowed",
    "is_loopback_host",
    "is_safe_http_url",
    "local_hostnames",
    "presented_token",
    "requires_token",
    "serve",
    "token_matches",
]
