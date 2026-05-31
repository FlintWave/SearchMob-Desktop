"""The MCP search server: the `web_search` tool's metasearch behavior and tool registration."""

from __future__ import annotations

import pytest

from searchmob_desktop import mcp_server
from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.prefs import JsonPreferencesStore


def _fake_engine(_client: object, _ctx: object) -> list[SearchResult]:
    return []


async def _fake_aggregate(ctx: EngineContext, _engines: object) -> list[SearchResult]:
    # Echo the scoped query back through a result URL so the test can assert vertical scoping.
    return [
        SearchResult(title="First", url="https://a.example/1", snippet=ctx.query, engine="ddg"),
        SearchResult(title="Second", url="https://b.example/2", snippet="s2", engine="mojeek"),
    ]


def _prefs(tmp_path: object) -> JsonPreferencesStore:
    return JsonPreferencesStore(path=tmp_path / "prefs.json")  # type: ignore[operator]


@pytest.mark.asyncio
async def test_web_search_returns_ranked_dicts(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server, "aggregate", _fake_aggregate)
    out = await mcp_server.run_web_search(
        "cats", engines=[_fake_engine], prefs_store=_prefs(tmp_path)
    )
    assert [r["title"] for r in out] == ["First", "Second"]
    assert out[0]["url"] == "https://a.example/1"
    assert set(out[0]) == {"title", "url", "snippet", "engine"}


@pytest.mark.asyncio
async def test_blank_query_and_no_engines_return_empty(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server, "aggregate", _fake_aggregate)
    assert await mcp_server.run_web_search("   ", engines=[_fake_engine]) == []
    assert await mcp_server.run_web_search("cats", engines=[], prefs_store=_prefs(tmp_path)) == []


@pytest.mark.asyncio
async def test_vertical_scopes_the_query(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server, "aggregate", _fake_aggregate)
    out = await mcp_server.run_web_search(
        "election", vertical="news", engines=[_fake_engine], prefs_store=_prefs(tmp_path)
    )
    # The scoped query (echoed into snippet by the fake) carries the news site: group.
    assert "site:reuters.com" in out[0]["snippet"]
    assert out[0]["snippet"].startswith("election (")


@pytest.mark.asyncio
async def test_limit_is_clamped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server, "aggregate", _fake_aggregate)
    out = await mcp_server.run_web_search(
        "cats", limit=1, engines=[_fake_engine], prefs_store=_prefs(tmp_path)
    )
    assert len(out) == 1


@pytest.mark.asyncio
async def test_server_registers_the_web_search_tool() -> None:
    server = mcp_server.build_mcp_server()
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "web_search" in names
    web = next(t for t in tools if t.name == "web_search")
    # The tool advertises its parameters so an agent knows how to call it.
    assert set(web.inputSchema.get("properties", {})) >= {"query", "vertical", "sort", "limit"}
