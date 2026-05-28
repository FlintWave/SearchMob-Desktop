"""Implementations of the suggestions providers. Public API is re-exported from `__init__`."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

import httpx

from searchmob_desktop.data.history import HistoryStore

__all__ = [
    "MAX_SUGGESTIONS",
    "CompositeSuggestionsProvider",
    "HistorySuggestionsProvider",
    "NoSuggestionsProvider",
    "UpstreamSuggestionsProvider",
]

# Cap on the merged suggestion list. Same value as Android's `MAX_SUGGESTIONS`.
MAX_SUGGESTIONS: Final = 8

# DuckDuckGo's autocomplete endpoint. We hit it through the same privacy-proxy client used by
# every other outbound call so no cookies leak and the UA is rotated.
_DDG_AC_URL: Final = "https://ac.duckduckgo.com/ac/"

# Bounded body read for the autocomplete response. The DDG ac payload is tiny (a few hundred
# bytes); anything past 64 KiB is treated as suspect rather than parsed.
_MAX_RESPONSE_BYTES: Final = 64 * 1024

# Default short timeout for the upstream call so a slow autocomplete never lags the address bar.
_UPSTREAM_TIMEOUT_SECONDS: Final = 2.0


class _AsyncClientFactory(Protocol):
    """Callable that produces an `httpx.AsyncClient`, sync or async.

    Used by `UpstreamSuggestionsProvider` so tests can hand it a `respx`-mocked client.
    """

    def __call__(self) -> httpx.AsyncClient | Awaitable[httpx.AsyncClient]: ...


class NoSuggestionsProvider:
    """Always returns an empty list. The default when nothing else is wired."""

    async def __call__(self, _query: str, _limit: int) -> list[str]:
        return []


class HistorySuggestionsProvider:
    """Suggestions sourced from the user's local encrypted search history.

    `HistoryStore.suggest` is fail-soft: a locked or disabled vault returns
    `[]` rather than raising, so wrapping it here is enough.
    """

    def __init__(self, history_store: HistoryStore) -> None:
        self._store = history_store

    async def __call__(self, query: str, limit: int) -> list[str]:
        try:
            return list(self._store.suggest(query, limit))
        except Exception:
            return []


class UpstreamSuggestionsProvider:
    """DuckDuckGo autocomplete via the privacy-proxy client.

    Off by default in the composite, because it sends the partial query
    upstream. When enabled, every keystroke costs one anonymized HTTP
    round-trip to `ac.duckduckgo.com`.
    """

    def __init__(
        self,
        client_factory: _AsyncClientFactory,
        *,
        base_url: str = _DDG_AC_URL,
        timeout_seconds: float = _UPSTREAM_TIMEOUT_SECONDS,
        max_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        self._client_factory = client_factory
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    async def __call__(self, query: str, limit: int) -> list[str]:
        if not query.strip() or limit <= 0:
            return []
        client_or_awaitable = self._client_factory()
        client: httpx.AsyncClient
        if isinstance(client_or_awaitable, httpx.AsyncClient):
            client = client_or_awaitable
        else:
            client = await client_or_awaitable
        try:
            try:
                response = await client.get(
                    self._base_url,
                    params={"q": query, "type": "list"},
                    timeout=self._timeout_seconds,
                )
            except (httpx.HTTPError, httpx.InvalidURL):
                return []
            if response.status_code != 200:
                return []
            content = response.content
            if len(content) > self._max_bytes:
                return []
            try:
                payload: Any = json.loads(content.decode("utf-8", errors="replace"))
            except ValueError:
                return []
        finally:
            await client.aclose()

        # DDG ac response shape: ["echoed query", ["sug1", "sug2", ...]].
        if not isinstance(payload, list) or len(payload) < 2:
            return []
        items = payload[1]
        if not isinstance(items, list):
            return []
        cleaned: list[str] = []
        for item in items:
            if isinstance(item, str) and item:
                cleaned.append(item)
                if len(cleaned) >= limit:
                    break
        return cleaned


class CompositeSuggestionsProvider:
    """Local-first merge of history + (opt-in) upstream suggestions.

    `upstream_enabled` is a callable, NOT a captured boolean, so a settings
    toggle takes effect on the next keystroke without restarting the server.
    """

    def __init__(
        self,
        history: Callable[[str, int], Awaitable[list[str]]],
        upstream: Callable[[str, int], Awaitable[list[str]]],
        upstream_enabled: Callable[[], bool],
        *,
        max_total: int = MAX_SUGGESTIONS,
    ) -> None:
        self._history = history
        self._upstream = upstream
        self._upstream_enabled = upstream_enabled
        self._max_total = max_total

    async def __call__(self, query: str, limit: int) -> list[str]:
        cap = min(limit, self._max_total)
        if cap <= 0:
            return []
        try:
            local = await self._history(query, cap)
        except Exception:
            local = []
        local_clean = [item for item in local if isinstance(item, str)]

        if not self._upstream_enabled():
            return local_clean[:cap]

        try:
            upstream = await self._upstream(query, cap)
        except Exception:
            upstream = []

        seen: set[str] = {item.casefold() for item in local_clean}
        merged: list[str] = list(local_clean)
        for item in upstream:
            if not isinstance(item, str) or not item:
                continue
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= cap:
                break
        return merged[:cap]
