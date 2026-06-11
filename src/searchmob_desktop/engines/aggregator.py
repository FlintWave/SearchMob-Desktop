"""Result aggregator: run engines in parallel, dedup by normalized URL, rank by RRF.

Reciprocal Rank Fusion (RRF) with k=60 is the same scoring used by the Android `Aggregator.kt`.
For each engine's result list, position `i` (0-based) contributes `1 / (60 + i)` to its URL's score.
When the same normalized URL comes back from multiple engines, the scores sum and the engine label
becomes the comma-joined sorted set of contributing engine ids ("duckduckgo,wikipedia"). Title and
snippet are taken from the first engine that returned the URL (good-enough policy; matches Android).

Engines are plain `async` callables: `(client, ctx) -> list[SearchResult]`. The aggregator owns the
single shared httpx client (the privacy proxy) and fans out via `asyncio.gather`; any engine that
raises or returns a non-list is treated as an empty list. This is the desktop equivalent of the
Kotlin `EngineResult.Failure` branch.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from searchmob_desktop.engines.normalize import normalize_url, strip_tracking_params
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.rank.ranker import host_of_url
from searchmob_desktop.engines.relevance import (
    blended_score,
    content_terms,
    language_affinity,
    lexical_score,
    navigational_factor,
)
from searchmob_desktop.engines.snippet_date import parse_date
from searchmob_desktop.engines.types import EngineContext, SearchResult

EngineFn = Callable[[httpx.AsyncClient, EngineContext], Awaitable[list[SearchResult]]]

_RRF_K = 60

# Per-engine outcome for one search: it returned results, returned nothing, or raised/timed out.
EngineStatus = Literal["contributed", "empty", "failed"]


@dataclass(frozen=True, slots=True)
class EngineOutcome:
    """One engine's result for a single search. `count` is the number of results it returned."""

    name: str
    status: EngineStatus
    count: int = 0


@dataclass(frozen=True, slots=True)
class AggregateOutcome:
    """The merged, ranked results plus the per-engine outcome that produced them.

    `engines` is computed locally for owner-facing diagnostics ("N of M engines responded"); it is
    never persisted or transmitted. Callers that only want results use `aggregate`, which returns
    `results` directly.
    """

    results: list[SearchResult]
    engines: tuple[EngineOutcome, ...]


def _engine_label(fn: EngineFn) -> str:
    """A stable display id for an engine function (`fetch_duckduckgo` -> `duckduckgo`).

    Prefers an explicit `engine_id` attribute (set by `bind_api_key` for the BYO-key adapters whose
    closure has no meaningful name), else strips the `fetch_` prefix from the function name.
    """
    raw = getattr(fn, "engine_id", None) or getattr(fn, "__name__", "engine")
    return str(raw).removeprefix("fetch_").replace("_", "-")


@dataclass(slots=True)
class _Bucket:
    title: str
    url: str
    snippet: str
    engines: set[str]
    score: float
    published: int | None = None


async def aggregate(ctx: EngineContext, engines: Sequence[EngineFn]) -> list[SearchResult]:
    """Run every engine against `ctx`, dedup + RRF-rank the results, return up to `ctx.max_results`.

    The returned `SearchResult.engine` field is the comma-joined sorted list of engine ids that
    surfaced the URL (e.g. `"duckduckgo"` or `"duckduckgo,wikipedia"`). Use `aggregate_with_status`
    when the per-engine outcome is wanted too.
    """
    return (await aggregate_with_status(ctx, engines)).results


async def aggregate_with_status(
    ctx: EngineContext, engines: Sequence[EngineFn]
) -> AggregateOutcome:
    """Like `aggregate`, but also return the per-engine outcome (contributed / empty / failed).

    The outcome is derived from the same fan-out the ranking uses, so it costs nothing extra and is
    exact: an engine that raised or timed out is `failed`, distinct from one that simply returned
    nothing. It is for owner-facing diagnostics only and never leaves the device.
    """
    async with make_privacy_client(ctx.timeout_seconds) as client:
        gathered = await asyncio.gather(
            *(engine(client, ctx) for engine in engines),
            return_exceptions=True,
        )

    per_engine: list[list[SearchResult]] = []
    outcomes: list[EngineOutcome] = []
    for engine, result in zip(engines, gathered, strict=True):
        name = _engine_label(engine)
        if isinstance(result, BaseException):
            per_engine.append([])
            outcomes.append(EngineOutcome(name, "failed"))
        elif isinstance(result, list) and result:
            per_engine.append(result)
            outcomes.append(EngineOutcome(name, "contributed", len(result)))
        else:
            per_engine.append([])
            outcomes.append(EngineOutcome(name, "empty"))

    now_ms = int(time.time() * 1000)

    def _published_of(item: SearchResult) -> int | None:
        # A structured date from the engine wins; else parse the snippet/title. A weak (bare-year)
        # parse is dropped to None so it never earns a freshness boost.
        if item.published is not None:
            return item.published
        parsed = parse_date(f"{item.snippet} {item.title}", now_ms)
        return None if parsed is None or parsed.weak else parsed.epoch_ms

    buckets: dict[str, _Bucket] = {}
    for engine_results in per_engine:
        for rank, item in enumerate(engine_results):
            key = normalize_url(item.url)
            contribution = 1.0 / (_RRF_K + rank)
            existing = buckets.get(key)
            if existing is None:
                buckets[key] = _Bucket(
                    title=item.title,
                    # Surface a tracker-stripped URL so the link the user clicks does not carry
                    # utm_*/fbclid/etc.; the lossy `key` above is still used only for dedup.
                    url=strip_tracking_params(item.url),
                    snippet=item.snippet,
                    engines={item.engine},
                    score=contribution,
                    published=_published_of(item),
                )
            else:
                existing.engines.add(item.engine)
                existing.score += contribution
                if not existing.snippet and item.snippet:
                    existing.snippet = item.snippet
                # Keep the newest known date when several engines surface the same URL.
                candidate = _published_of(item)
                if candidate is not None and (
                    existing.published is None or candidate > existing.published
                ):
                    existing.published = candidate

    # Fold a lexical query-match score into the RRF score so the final order leads with relevance
    # (does the result actually contain the query's content words, especially the title) and keeps
    # engine consensus as a strong secondary signal. Without this, near-tied RRF scores let an
    # irrelevant result one engine ranked highly sit among the top hits.
    terms = content_terms(ctx.query)

    def _final_score(b: _Bucket) -> float:
        # Navigational promotion: when the squished query names this result's domain (query
        # "threejs" -> threejs.org), float it to the top past the demotion-only relevance blend, so
        # the official site is not buried under forum posts that merely contain the word.
        nav = navigational_factor(terms, host_of_url(b.url) or "")
        return (
            blended_score(
                b.score,
                lexical_score(b.title, b.snippet, terms),
                language_affinity(ctx.query, b.title, b.snippet),
            )
            * nav
        )

    ranked = sorted(buckets.values(), key=_final_score, reverse=True)
    results = [
        SearchResult(
            title=b.title,
            url=b.url,
            snippet=b.snippet,
            engine=",".join(sorted(b.engines)),
            published=b.published,
        )
        for b in ranked[: ctx.max_results]
    ]
    return AggregateOutcome(results, tuple(outcomes))
