"""Tests for the history-backed suggestions provider."""

from __future__ import annotations

import pytest

from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.suggest import HistorySuggestionsProvider


@pytest.mark.asyncio
async def test_returns_empty_when_history_disabled() -> None:
    store = InMemoryHistoryStore()
    # Off by default.
    store.add("privacy tools")  # no-op
    provider = HistorySuggestionsProvider(store)
    assert await provider("pri", 10) == []


@pytest.mark.asyncio
async def test_returns_prefix_matches_when_enabled() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    store.add("privacy tools", timestamp_ms=100)
    store.add("private search", timestamp_ms=200)
    store.add("kotlin coroutines", timestamp_ms=300)
    provider = HistorySuggestionsProvider(store)

    suggestions = await provider("pri", 10)
    assert "privacy tools" in suggestions
    assert "private search" in suggestions
    assert "kotlin coroutines" not in suggestions


@pytest.mark.asyncio
async def test_respects_limit() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    for i in range(20):
        store.add(f"prefix-{i:02d}", timestamp_ms=i)
    provider = HistorySuggestionsProvider(store)
    suggestions = await provider("prefix-", 5)
    assert len(suggestions) == 5


class _Exploding:
    @property
    def enabled(self) -> bool:
        return True

    def set_enabled(self, enabled: bool) -> None:  # pragma: no cover - protocol surface
        pass

    def add(self, query: str, timestamp_ms: int | None = None) -> None:  # pragma: no cover
        pass

    def suggest(self, prefix: str, limit: int) -> list[str]:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_fail_soft_on_underlying_exception() -> None:
    provider = HistorySuggestionsProvider(_Exploding())  # type: ignore[arg-type]
    assert await provider("anything", 10) == []
