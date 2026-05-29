"""Public engines API: the privacy-proxy client, the per-engine adapters, and the aggregator.

Importers should depend on `searchmob_desktop.engines` and not reach into submodules unless they
need internals. The CLI and (later) the GUI both compose `aggregate(ctx, [fetch_*, ...])` to run
a metasearch.
"""

from __future__ import annotations

from searchmob_desktop.engines.aggregator import EngineFn, aggregate
from searchmob_desktop.engines.brave_api import fetch_brave_api
from searchmob_desktop.engines.duckduckgo import fetch_duckduckgo
from searchmob_desktop.engines.kagi_api import fetch_kagi_api
from searchmob_desktop.engines.keyed import bind_api_key
from searchmob_desktop.engines.marginalia import fetch_marginalia
from searchmob_desktop.engines.mojeek import fetch_mojeek
from searchmob_desktop.engines.mojeek_api import fetch_mojeek_api
from searchmob_desktop.engines.mwmbl import fetch_mwmbl
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
    "bind_api_key",
    "fetch_brave_api",
    "fetch_duckduckgo",
    "fetch_kagi_api",
    "fetch_marginalia",
    "fetch_mojeek",
    "fetch_mojeek_api",
    "fetch_mwmbl",
    "fetch_wikipedia",
    "make_privacy_client",
    "normalize_url",
]
