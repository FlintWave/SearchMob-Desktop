"""A Model Context Protocol (MCP) server exposing SearchMob's metasearch as a tool.

This lets a local AI agent (Claude Desktop, an IDE assistant, ...) run its web searches *through*
SearchMob: the same on-device metasearch, privacy proxy, ranking rules, and AI-slop filter the app
and the served page use, instead of leaking the query to a third-party search API. The transport is
stdio (the agent launches `searchmob-desktop mcp` as a subprocess), so nothing listens on the
network; the only outbound traffic is the same engine fetches a normal search makes, through the
privacy proxy. It is opt-in: nothing runs until an agent is configured to launch it.

The metasearch reuses the exact pipeline the server's `_run_metasearch` uses (vertical scoping,
sort, then the personalization + slop ranking pass), so an agent's results match the app's.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from typing import TYPE_CHECKING, Any

from searchmob_desktop.data.ranking_store import load_ranking_rules
from searchmob_desktop.engines import EngineContext, EngineFn, aggregate
from searchmob_desktop.engines.rank import apply_ranking, host_of_url
from searchmob_desktop.engines.rank.slop_blocklist import load_slop_domains
from searchmob_desktop.engines.sort import SortMode, sort_results
from searchmob_desktop.engines.verticals import Vertical, default_sort, transform_query
from searchmob_desktop.prefs import JsonPreferencesStore

if TYPE_CHECKING:
    from collections.abc import Sequence

# The default and hard cap on how many results the tool returns; agents tend to want a handful.
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 20
_TIMEOUT_SECONDS = 8.0


async def run_web_search(
    query: str,
    vertical: str = "web",
    sort: str = "",
    limit: int = _DEFAULT_LIMIT,
    *,
    engines: Sequence[EngineFn] | None = None,
    prefs_store: JsonPreferencesStore | None = None,
) -> list[dict[str, str]]:
    """Run one metasearch and return ranked results as plain dicts (title/url/snippet/engine).

    Mirrors the served `_run_metasearch`: scope the query for the vertical, aggregate across the
    engines, sort, then apply the user's personalization rules and the AI-slop filter. Fail-soft:
    a blank query or no engines returns an empty list. `engines`/`prefs_store` are injectable for
    tests; in normal use they default to the same engine list and preferences the CLI uses.
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(limit, _MAX_LIMIT))
    if engines is None:
        # Imported lazily so building the engine list (which opens the vault for BYO keys) only
        # happens when a search actually runs, not at import time.
        from searchmob_desktop.cli import _build_engines

        engines = _build_engines()
    if not engines:
        return []
    chosen = Vertical.from_value(vertical)
    sort_mode = SortMode.from_value(sort) if sort else default_sort(chosen)
    prefs = (prefs_store or JsonPreferencesStore()).load()
    scoped = transform_query(query, chosen)
    ctx = EngineContext(query=scoped, max_results=limit, timeout_seconds=_TIMEOUT_SECONDS)
    results = await aggregate(ctx, engines)
    ordered = sort_results(results, sort_mode, query, int(time.time() * 1000))
    ranked = apply_ranking(
        ordered,
        load_ranking_rules(),
        host_of=lambda r: host_of_url(r.url),
        text_of=lambda r: f"{r.title} {r.snippet}",
        slop_domains=load_slop_domains(),
        slop_mode=prefs.ai_slop_mode,
    )
    return [
        {"title": r.title, "url": r.url, "snippet": r.snippet, "engine": r.engine}
        for r in ranked[:limit]
    ]


def build_mcp_server() -> Any:
    """Build the FastMCP server exposing the `web_search` tool. The SDK is imported lazily."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("SearchMob")

    @server.tool()
    async def web_search(
        query: str,
        vertical: str = "web",
        sort: str = "",
        limit: int = _DEFAULT_LIMIT,
    ) -> list[dict[str, str]]:
        """Search the web privately through SearchMob's on-device metasearch.

        Returns ranked results (title, url, snippet, contributing engines). The query goes only to
        SearchMob's configured search engines through its privacy proxy, never to a third-party
        search API, and the user's personalization rules and AI-slop filter are applied.

        Args:
            query: The search query.
            vertical: One of "web" (default), "news", "forums", "academic"; scopes the search.
            sort: One of "fresh", "date", "relevance"; empty uses the vertical's default.
            limit: Max results to return (1-20, default 10).
        """
        return await run_web_search(query, vertical, sort, limit)

    return server


def run_stdio() -> None:
    """Run the MCP server over stdio (blocking). This is what `searchmob-desktop mcp` invokes."""
    build_mcp_server().run()


def mcp_command() -> list[str]:
    """The command an MCP client should launch to start this stdio server.

    Reuses the same console-script / frozen-app / interpreter detection the background service uses,
    so the snippet shown in Settings matches however this build was installed.
    """
    from searchmob_desktop.service import _running_frozen

    console = shutil.which("searchmob-desktop")
    if console:
        base = [console]
    elif _running_frozen():
        base = [sys.executable]
    else:
        base = [sys.executable, "-m", "searchmob_desktop"]
    return [*base, "mcp"]


def config_snippet() -> str:
    """A ready-to-paste MCP client config (Claude Desktop style) that launches this server."""
    cmd = mcp_command()
    config = {"mcpServers": {"searchmob": {"command": cmd[0], "args": cmd[1:]}}}
    return json.dumps(config, indent=2)
