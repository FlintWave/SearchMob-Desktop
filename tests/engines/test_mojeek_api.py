"""Mojeek API adapter: key in query string, no-key-no-call, parsing, fail-soft."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from searchmob_desktop.engines.mojeek_api import fetch_mojeek_api
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext


def _payload() -> dict[str, object]:
    return {
        "response": {
            "results": [
                {
                    "url": "https://example.com/a",
                    "title": "Result A",
                    "desc": "Mojeek API hit A.",
                },
                {
                    "url": "https://example.com/b",
                    "title": "Result B",
                    "desc": "Mojeek API hit B.",
                },
            ]
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_sends_api_key_query_param_and_parses_results() -> None:
    route = respx.get("https://api.mojeek.com/search").mock(
        return_value=httpx.Response(200, json=_payload())
    )
    ctx = EngineContext(query="anything", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_mojeek_api(client, ctx, api_key="dummy")

    assert route.called
    sent_url = route.calls.last.request.url
    params = parse_qs(urlsplit(str(sent_url)).query)
    assert params.get("api_key") == ["dummy"]
    assert params.get("fmt") == ["json"]
    assert params.get("q") == ["anything"]

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert results[0].title == "Result A"
    assert results[1].snippet == "Mojeek API hit B."
    assert all(r.engine == "mojeek-api" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_no_key_means_no_http_call() -> None:
    route = respx.get("https://api.mojeek.com/search").mock(
        return_value=httpx.Response(200, json=_payload())
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mojeek_api(client, ctx, api_key=None)

    assert results == []
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_non_json_body() -> None:
    respx.get("https://api.mojeek.com/search").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mojeek_api(client, ctx, api_key="dummy")
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_500() -> None:
    respx.get("https://api.mojeek.com/search").mock(return_value=httpx.Response(500))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mojeek_api(client, ctx, api_key="dummy")
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_unexpected_shape() -> None:
    respx.get("https://api.mojeek.com/search").mock(
        return_value=httpx.Response(200, json={"response": {"results": "oops"}})
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mojeek_api(client, ctx, api_key="dummy")
    assert results == []
