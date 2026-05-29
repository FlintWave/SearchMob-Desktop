"""Bind a bring-your-own-key fetcher to a concrete key, yielding a plain `EngineFn`.

The BYO-key adapters (`fetch_brave_api`, `fetch_mojeek_api`, `fetch_kagi_api`) take an extra
`api_key` argument that the aggregator's `EngineFn` shape does not. `bind_api_key` closes over a
resolved key so the result matches `EngineFn` and can sit in the engine list next to the free
adapters. A typed factory (rather than an inline default-argument closure) keeps the closure's
parameter types intact for the type checker.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from searchmob_desktop.engines.aggregator import EngineFn
from searchmob_desktop.engines.types import EngineContext, SearchResult

KeyedEngineFn = Callable[[httpx.AsyncClient, EngineContext, str], Awaitable[list[SearchResult]]]


def bind_api_key(fetch: KeyedEngineFn, api_key: str) -> EngineFn:
    """Return an `EngineFn` that calls `fetch` with `api_key` already supplied."""

    async def _run(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
        return await fetch(client, ctx, api_key)

    return _run
