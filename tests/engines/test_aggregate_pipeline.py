"""Full-pipeline integration: real `aggregate` over several fake async engines, no network.

Complements `tests/engines/test_aggregator.py` by wiring three engine callables (with an overlapping
URL across two of them) through the real `searchmob_desktop.engines.aggregate` and asserting dedup,
RRF ordering, and the combined comma-joined engine label end to end. The engines return canned data,
so the shared httpx client `aggregate` opens never issues a request.
"""

from __future__ import annotations

import httpx
import pytest

from searchmob_desktop.engines import EngineContext, SearchResult, aggregate


async def _engine_one(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(title="Shared", url="https://example.com/shared", snippet="", engine="one"),
        SearchResult(title="One only", url="https://one.example/x", snippet="", engine="one"),
    ]


async def _engine_two(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(title="Two only", url="https://two.example/y", snippet="", engine="two"),
        # Same target as engine one's top hit, with tracking params + scheme/host noise.
        SearchResult(
            title="Shared (two)",
            url="https://EXAMPLE.com/shared?utm_campaign=x",
            snippet="from two",
            engine="two",
        ),
    ]


async def _engine_three(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(title="Three only", url="https://three.example/z", snippet="", engine="three"),
    ]


@pytest.mark.asyncio
async def test_three_engines_dedup_rank_and_combined_label() -> None:
    ctx = EngineContext(query="anything", max_results=10)
    results = await aggregate(ctx, [_engine_one, _engine_two, _engine_three])

    # 5 inputs collapse to 4 distinct URLs (the shared page merges across one + two).
    assert len(results) == 4

    top = results[0]
    # The shared URL scores from two engines at rank 0 (2/60) and outranks every solo row (<=1/60).
    assert top.engine == "one,two"
    assert top.title == "Shared"  # first-seen title wins
    assert top.snippet == "from two"  # first-seen snippet was empty, so the later non-empty fills

    # The remaining rows keep their single-engine labels.
    others = {r.engine for r in results[1:]}
    assert others == {"one", "two", "three"}


@pytest.mark.asyncio
async def test_max_results_caps_the_output() -> None:
    ctx = EngineContext(query="anything", max_results=2)
    results = await aggregate(ctx, [_engine_one, _engine_two, _engine_three])
    assert len(results) == 2
