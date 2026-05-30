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

import httpx

from searchmob_desktop.engines.normalize import normalize_url, strip_tracking_params
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.snippet_date import parse_date
from searchmob_desktop.engines.types import EngineContext, SearchResult

EngineFn = Callable[[httpx.AsyncClient, EngineContext], Awaitable[list[SearchResult]]]

_RRF_K = 60


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
    surfaced the URL (e.g. `"duckduckgo"` or `"duckduckgo,wikipedia"`).
    """
    async with make_privacy_client(ctx.timeout_seconds) as client:
        gathered = await asyncio.gather(
            *(engine(client, ctx) for engine in engines),
            return_exceptions=True,
        )

    per_engine: list[list[SearchResult]] = []
    for result in gathered:
        if isinstance(result, BaseException):
            per_engine.append([])
        elif isinstance(result, list):
            per_engine.append(result)
        else:
            per_engine.append([])

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

    ranked = sorted(buckets.values(), key=lambda b: b.score, reverse=True)
    return [
        SearchResult(
            title=b.title,
            url=b.url,
            snippet=b.snippet,
            engine=",".join(sorted(b.engines)),
            published=b.published,
        )
        for b in ranked[: ctx.max_results]
    ]
