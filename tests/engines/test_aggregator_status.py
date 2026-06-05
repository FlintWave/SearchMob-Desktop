"""Per-engine outcome: `aggregate_with_status` distinguishes contributed / empty / failed."""

from __future__ import annotations

import httpx
import pytest

from searchmob_desktop.engines.aggregator import AggregateOutcome, aggregate, aggregate_with_status
from searchmob_desktop.engines.keyed import bind_api_key
from searchmob_desktop.engines.types import EngineContext, SearchResult


async def fetch_alpha(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(title="A1", url="https://a.example/1", snippet="", engine="alpha"),
        SearchResult(title="A2", url="https://a.example/2", snippet="", engine="alpha"),
    ]


async def fetch_beta(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return []  # responded, but found nothing


async def fetch_gamma(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    raise RuntimeError("engine exploded")  # failed: must not look the same as empty


@pytest.mark.asyncio
async def test_outcome_distinguishes_failed_from_empty_from_contributed() -> None:
    ctx = EngineContext(query="q", max_results=10)
    outcome = await aggregate_with_status(ctx, [fetch_alpha, fetch_beta, fetch_gamma])

    assert isinstance(outcome, AggregateOutcome)
    by_name = {o.name: o for o in outcome.engines}
    assert by_name["alpha"].status == "contributed"
    assert by_name["alpha"].count == 2
    assert by_name["beta"].status == "empty"
    assert by_name["beta"].count == 0
    assert by_name["gamma"].status == "failed"

    # The search still succeeds on the working engine despite the failure.
    assert [r.url for r in outcome.results] == ["https://a.example/1", "https://a.example/2"]


@pytest.mark.asyncio
async def test_aggregate_keeps_the_plain_list_return() -> None:
    ctx = EngineContext(query="q", max_results=10)
    results = await aggregate(ctx, [fetch_alpha])
    assert isinstance(results, list)
    assert [r.url for r in results] == ["https://a.example/1", "https://a.example/2"]


@pytest.mark.asyncio
async def test_bound_api_key_engine_is_labelled_by_its_id() -> None:
    async def fetch_keyed(
        _client: httpx.AsyncClient, _ctx: EngineContext, _api_key: str
    ) -> list[SearchResult]:
        return []

    bound = bind_api_key(fetch_keyed, "secret", "brave")
    outcome = await aggregate_with_status(EngineContext(query="q", max_results=10), [bound])
    assert outcome.engines[0].name == "brave"
