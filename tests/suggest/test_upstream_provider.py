"""Tests for the DuckDuckGo-autocomplete-backed upstream suggestions provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.suggest import UpstreamSuggestionsProvider

_AC = "https://ac.duckduckgo.com/ac/"


@respx.mock
@pytest.mark.asyncio
async def test_parses_ddg_ac_shape_and_respects_limit() -> None:
    respx.get(_AC).respond(
        200, json=["pri", ["privacy", "privacy tools", "private browsing", "primer"]]
    )
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient())
    suggestions = await provider("pri", limit=3)
    assert suggestions == ["privacy", "privacy tools", "private browsing"]


@respx.mock
@pytest.mark.asyncio
async def test_blank_query_returns_empty_without_calling_upstream() -> None:
    route = respx.get(_AC)
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient())
    assert await provider("  ", 10) == []
    assert route.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_returns_empty_on_http_error() -> None:
    respx.get(_AC).respond(500)
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient())
    assert await provider("pri", 10) == []


@respx.mock
@pytest.mark.asyncio
async def test_returns_empty_on_malformed_json() -> None:
    respx.get(_AC).respond(200, content=b"<html>oops</html>")
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient())
    assert await provider("pri", 10) == []


@respx.mock
@pytest.mark.asyncio
async def test_returns_empty_on_transport_error() -> None:
    respx.get(_AC).mock(side_effect=httpx.ConnectError("network down"))
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient())
    assert await provider("pri", 10) == []


@respx.mock
@pytest.mark.asyncio
async def test_returns_empty_on_oversized_response() -> None:
    body = b'["pri",[' + b'"x",' * 200_000 + b'"end"]]'
    respx.get(_AC).respond(200, content=body)
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient(), max_bytes=64 * 1024)
    assert await provider("pri", 10) == []


@respx.mock
@pytest.mark.asyncio
async def test_returns_empty_when_payload_is_not_list() -> None:
    respx.get(_AC).respond(200, json={"not": "a list"})
    provider = UpstreamSuggestionsProvider(lambda: httpx.AsyncClient())
    assert await provider("pri", 10) == []
