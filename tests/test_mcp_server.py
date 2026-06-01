"""The MCP search server: the `web_search` tool's metasearch behavior and tool registration."""

from __future__ import annotations

import pytest

from searchmob_desktop import mcp_server
from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.prefs import JsonPreferencesStore, UserPreferences


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
async def test_query_is_length_clamped(monkeypatch, tmp_path) -> None:
    from searchmob_desktop.server.app import MAX_QUERY_LENGTH

    monkeypatch.setattr(mcp_server, "aggregate", _fake_aggregate)
    out = await mcp_server.run_web_search(
        "x" * (MAX_QUERY_LENGTH + 500), engines=[_fake_engine], prefs_store=_prefs(tmp_path)
    )
    # WEB vertical does not scope, so the fake echoes the (clamped) query into the snippet.
    assert len(out[0]["snippet"]) == MAX_QUERY_LENGTH


@pytest.mark.asyncio
async def test_limit_is_clamped(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(mcp_server, "aggregate", _fake_aggregate)
    out = await mcp_server.run_web_search(
        "cats", limit=1, engines=[_fake_engine], prefs_store=_prefs(tmp_path)
    )
    assert len(out) == 1


@pytest.mark.asyncio
async def test_titles_and_snippets_are_sanitized(monkeypatch, tmp_path) -> None:
    async def _agg(_ctx: object, _engines: object) -> list[SearchResult]:
        return [
            SearchResult(
                title="Hi\x00\x07there\x1b[31m",
                url="https://a.example/1",
                snippet="line1\nline2\t\tspaced   out",
                engine="ddg",
            ),
        ]

    monkeypatch.setattr(mcp_server, "aggregate", _agg)
    out = await mcp_server.run_web_search("q", engines=[_fake_engine], prefs_store=_prefs(tmp_path))
    # Control characters (NUL, BEL, ESC) become spaces, neutralizing the escape sequence, and runs
    # of whitespace collapse to single spaces; the inert "[31m" residue is left as plain text.
    assert out[0]["title"] == "Hi there [31m"
    assert out[0]["snippet"] == "line1 line2 spaced out"


@pytest.mark.asyncio
async def test_snippet_is_length_capped(monkeypatch, tmp_path) -> None:
    async def _agg(_ctx: object, _engines: object) -> list[SearchResult]:
        return [
            SearchResult(title="t", url="https://a.example/1", snippet="z" * 5000, engine="ddg"),
        ]

    monkeypatch.setattr(mcp_server, "aggregate", _agg)
    out = await mcp_server.run_web_search("q", engines=[_fake_engine], prefs_store=_prefs(tmp_path))
    assert len(out[0]["snippet"]) == mcp_server._MAX_SNIPPET + len("...")
    assert out[0]["snippet"].endswith("...")


@pytest.mark.asyncio
async def test_non_http_links_are_dropped(monkeypatch, tmp_path) -> None:
    async def _agg(_ctx: object, _engines: object) -> list[SearchResult]:
        return [
            SearchResult(title="evil", url="javascript:alert(1)", snippet="s", engine="ddg"),
            SearchResult(title="data", url="data:text/html,x", snippet="s", engine="ddg"),
            SearchResult(title="ok", url="https://good.example/x", snippet="s", engine="ddg"),
        ]

    monkeypatch.setattr(mcp_server, "aggregate", _agg)
    out = await mcp_server.run_web_search("q", engines=[_fake_engine], prefs_store=_prefs(tmp_path))
    assert [r["title"] for r in out] == ["ok"]


@pytest.mark.asyncio
async def test_agent_safety_excludes_drop_matching_domains(monkeypatch, tmp_path) -> None:
    async def _agg(_ctx: object, _engines: object) -> list[SearchResult]:
        return [
            SearchResult(title="junk", url="https://spam.example/a", snippet="s", engine="ddg"),
            SearchResult(title="keep", url="https://good.example/b", snippet="s", engine="ddg"),
        ]

    monkeypatch.setattr(mcp_server, "aggregate", _agg)
    store = _prefs(tmp_path)
    store.save(UserPreferences(agent_safety_excludes=("spam.example",)))
    out = await mcp_server.run_web_search("q", engines=[_fake_engine], prefs_store=store)
    assert [r["title"] for r in out] == ["keep"]


@pytest.mark.asyncio
async def test_slop_is_force_hidden_even_when_user_disabled_it(monkeypatch, tmp_path) -> None:
    async def _agg(_ctx: object, _engines: object) -> list[SearchResult]:
        return [
            SearchResult(title="farm", url="https://slop.example/a", snippet="s", engine="ddg"),
            SearchResult(title="real", url="https://good.example/b", snippet="s", engine="ddg"),
        ]

    monkeypatch.setattr(mcp_server, "aggregate", _agg)
    monkeypatch.setattr(mcp_server, "load_slop_domains", lambda: frozenset({"slop.example"}))
    store = _prefs(tmp_path)
    # The user turned the slop filter OFF in the app; the MCP path still hides slop for the agent.
    store.save(UserPreferences(ai_slop_mode="off"))
    out = await mcp_server.run_web_search("q", engines=[_fake_engine], prefs_store=store)
    assert [r["title"] for r in out] == ["real"]


@pytest.mark.asyncio
async def test_server_registers_the_web_search_tool() -> None:
    server = mcp_server.build_mcp_server()
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "web_search" in names
    web = next(t for t in tools if t.name == "web_search")
    # The tool advertises its parameters so an agent knows how to call it.
    assert set(web.inputSchema.get("properties", {})) >= {"query", "vertical", "sort", "limit"}
