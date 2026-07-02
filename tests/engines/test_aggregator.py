"""Aggregator: dedup by normalized URL, RRF ordering, combined engine field."""

from __future__ import annotations

import httpx
import pytest

from searchmob_desktop.engines.aggregator import aggregate
from searchmob_desktop.engines.types import EngineContext, SearchResult


async def _fake_a(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(
            title="Shared page", url="https://example.com/page", snippet="from A", engine="a"
        ),
        SearchResult(
            title="Only in A", url="https://example.com/only-a", snippet="a-only", engine="a"
        ),
        SearchResult(title="Solo low", url="https://example.com/low", snippet="", engine="a"),
    ]


async def _fake_b(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        # Same URL as A's first hit, but with tracking params + uppercase host. Should collapse.
        SearchResult(
            title="Shared page (B)",
            url="https://EXAMPLE.com/page?utm_source=b",
            snippet="from B",
            engine="b",
        ),
        SearchResult(
            title="Only in B", url="https://example.com/only-b", snippet="b-only", engine="b"
        ),
    ]


async def _fake_raises(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    raise RuntimeError("engine exploded")


async def _fake_official(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    # One engine, ranked last, returns the official site whose title uses the dotted brand name.
    return [
        SearchResult(
            title="ThreeJS - GameDev.net", url="https://gamedev.net/x", snippet="forum", engine="x"
        ),
        SearchResult(
            title="threejs on Stack Overflow",
            url="https://stackoverflow.com/q",
            snippet="q",
            engine="x",
        ),
        SearchResult(
            title="Three.js - JavaScript 3D Library",
            url="https://threejs.org/",
            snippet="docs",
            engine="x",
        ),
    ]


@pytest.mark.asyncio
async def test_navigational_query_promotes_official_site_over_literal_forum_hits() -> None:
    # Regression: for "threejs" the official three.js site (one engine, ranked last, dotted title)
    # must beat single-engine forum posts that literally contain "threejs". The nav boost + the
    # separator bridging together float it to the top instead of burying it.
    ctx = EngineContext(query="threejs", max_results=10)
    results = await aggregate(ctx, [_fake_official])
    assert results[0].url == "https://threejs.org/"


@pytest.mark.asyncio
async def test_dedup_rrf_and_combined_engine_label() -> None:
    ctx = EngineContext(query="anything", max_results=10)
    results = await aggregate(ctx, [_fake_a, _fake_b])

    # Shared page collapses to one row, so we get 4 distinct rows from 5 inputs.
    assert len(results) == 4

    # The shared URL appears at rank 0 in both engines: score = 2 * (1 / (60 + 0)) = 2/60.
    # Every other row has score 1/(60+rank) <= 1/60, so the shared row must rank first.
    top = results[0]
    assert top.url in {"https://example.com/page", "https://EXAMPLE.com/page?utm_source=b"}
    assert top.engine == "a,b"

    # The single-engine rows keep their lone engine id.
    others = [r for r in results if r.url != top.url]
    assert {r.engine for r in others} == {"a", "b"}

    # First-seen title wins for the merged row.
    assert top.title == "Shared page"
    # Sanity: every input URL appears once (under one of its equivalent spellings for the merged).
    distinct_paths = {r.url.lower().split("?")[0] for r in results}
    assert distinct_paths == {
        "https://example.com/page",
        "https://example.com/only-a",
        "https://example.com/only-b",
        "https://example.com/low",
    }


@pytest.mark.asyncio
async def test_failing_engine_does_not_break_others() -> None:
    ctx = EngineContext(query="anything", max_results=10)
    results = await aggregate(ctx, [_fake_raises, _fake_a])
    assert {r.url for r in results} == {
        "https://example.com/page",
        "https://example.com/only-a",
        "https://example.com/low",
    }


@pytest.mark.asyncio
async def test_respects_max_results() -> None:
    ctx = EngineContext(query="anything", max_results=2)
    results = await aggregate(ctx, [_fake_a, _fake_b])
    assert len(results) == 2


async def _fake_scoring_bait(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    # The first result matches the scoping clause's own words ("site", "reddit"), not the subject;
    # the second matches the actual subject. Rank order gives the bait the higher RRF score.
    return [
        SearchResult(
            title="Reddit site index",
            url="https://reddit.example/r/all",
            snippet="site list",
            engine="x",
        ),
        SearchResult(
            title="Rust tutorial for beginners",
            url="https://docs.example/rust",
            snippet="a rust tutorial",
            engine="x",
        ),
    ]


@pytest.mark.asyncio
async def test_ranking_terms_keep_scoping_clauses_out_of_the_lexical_score() -> None:
    # A vertical (or a user operator) appends `site:` clauses to the fetched query. The lexical
    # scorer must reason about the operator-free text, so the scored order and relevance values are
    # identical to a plain search for the same subject; the clause words never count as a match.
    scoped = "rust tutorial (site:reddit.example OR site:forum.example)"
    plain_results = await aggregate(
        EngineContext(query="rust tutorial", max_results=10), [_fake_scoring_bait]
    )
    scoped_results = await aggregate(
        EngineContext(query=scoped, max_results=10, ranking_terms="rust tutorial"),
        [_fake_scoring_bait],
    )
    assert [r.url for r in scoped_results] == [r.url for r in plain_results]
    assert [r.relevance for r in scoped_results] == [r.relevance for r in plain_results]
    # The genuinely matching result leads despite the bait's better engine rank.
    assert scoped_results[0].url == "https://docs.example/rust"


@pytest.mark.asyncio
async def test_without_ranking_terms_the_query_itself_is_scored() -> None:
    # Back-compat: callers that set no ranking_terms keep the old behavior (the full query drives
    # the lexical score), so raw `aggregate` uses stay byte-identical.
    ctx = EngineContext(query="reddit site", max_results=10)
    results = await aggregate(ctx, [_fake_scoring_bait])
    assert results[0].url == "https://reddit.example/r/all"


@pytest.mark.asyncio
async def test_surfaced_url_is_tracker_stripped() -> None:
    """The clicked link must not carry trackers, even when the result is unique (no dedup)."""

    async def _tracked(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
        return [
            SearchResult(
                title="Tracked",
                url="https://news.example/article?utm_source=x&fbclid=y&id=7",
                snippet="",
                engine="t",
            )
        ]

    ctx = EngineContext(query="anything", max_results=10)
    results = await aggregate(ctx, [_tracked])
    assert results[0].url == "https://news.example/article?id=7"
