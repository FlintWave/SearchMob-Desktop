"""Tests for the local-first + opt-in-upstream composite suggestions provider."""

from __future__ import annotations

import pytest

from searchmob_desktop.suggest import CompositeSuggestionsProvider


class _Counter:
    """Awaitable helper that records calls so we can assert no-call when upstream disabled."""

    def __init__(self, items: list[str]) -> None:
        self.items = items
        self.calls = 0

    async def __call__(self, _query: str, _limit: int) -> list[str]:
        self.calls += 1
        return list(self.items)


@pytest.mark.asyncio
async def test_local_first_with_upstream_disabled_skips_upstream() -> None:
    upstream = _Counter(["should not appear"])
    composite = CompositeSuggestionsProvider(
        history=_Counter(["alpha", "beta"]),
        upstream=upstream,
        upstream_enabled=lambda: False,
    )
    assert await composite("a", 5) == ["alpha", "beta"]
    assert upstream.calls == 0


@pytest.mark.asyncio
async def test_local_first_merges_upstream_when_enabled() -> None:
    composite = CompositeSuggestionsProvider(
        history=_Counter(["alpha", "beta"]),
        upstream=_Counter(["beta", "gamma", "delta"]),
        upstream_enabled=lambda: True,
    )
    assert await composite("a", 5) == ["alpha", "beta", "gamma", "delta"]


@pytest.mark.asyncio
async def test_dedup_is_case_insensitive_and_keeps_local_casing() -> None:
    composite = CompositeSuggestionsProvider(
        history=_Counter(["Privacy Tools"]),
        upstream=_Counter(["privacy tools", "Privacy Settings"]),
        upstream_enabled=lambda: True,
    )
    result = await composite("priv", 10)
    assert result == ["Privacy Tools", "Privacy Settings"]


@pytest.mark.asyncio
async def test_caps_at_max_suggestions_default_8() -> None:
    composite = CompositeSuggestionsProvider(
        history=_Counter([f"h{i}" for i in range(10)]),
        upstream=_Counter([f"u{i}" for i in range(10)]),
        upstream_enabled=lambda: True,
    )
    result = await composite("x", 100)
    assert len(result) == 8


@pytest.mark.asyncio
async def test_caps_at_caller_limit_when_lower_than_max() -> None:
    composite = CompositeSuggestionsProvider(
        history=_Counter([f"h{i}" for i in range(10)]),
        upstream=_Counter([f"u{i}" for i in range(10)]),
        upstream_enabled=lambda: True,
    )
    result = await composite("x", 3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_history_exception_is_fail_soft() -> None:
    class _Boom:
        async def __call__(self, _q: str, _n: int) -> list[str]:
            raise RuntimeError("boom")

    composite = CompositeSuggestionsProvider(
        history=_Boom(),
        upstream=_Counter(["only upstream"]),
        upstream_enabled=lambda: True,
    )
    assert await composite("x", 5) == ["only upstream"]


@pytest.mark.asyncio
async def test_upstream_exception_is_fail_soft() -> None:
    class _Boom:
        async def __call__(self, _q: str, _n: int) -> list[str]:
            raise RuntimeError("boom")

    composite = CompositeSuggestionsProvider(
        history=_Counter(["only local"]),
        upstream=_Boom(),
        upstream_enabled=lambda: True,
    )
    assert await composite("x", 5) == ["only local"]
