"""Public engines API: the privacy-proxy client, the per-engine adapters, and the aggregator.

Importers should depend on `searchmob_desktop.engines` and not reach into submodules unless they
need internals. The CLI and (later) the GUI both compose `aggregate(ctx, [fetch_*, ...])` to run
a metasearch.
"""

from __future__ import annotations

from searchmob_desktop.engines.aggregator import EngineFn, aggregate
from searchmob_desktop.engines.duckduckgo import fetch_duckduckgo
from searchmob_desktop.engines.normalize import normalize_url
from searchmob_desktop.engines.proxy import USER_AGENTS, make_privacy_client
from searchmob_desktop.engines.types import EngineContext, SearchResult
from searchmob_desktop.engines.wikipedia import fetch_wikipedia

__all__ = [
    "USER_AGENTS",
    "EngineContext",
    "EngineFn",
    "SearchResult",
    "aggregate",
    "fetch_duckduckgo",
    "fetch_wikipedia",
    "make_privacy_client",
    "normalize_url",
]
