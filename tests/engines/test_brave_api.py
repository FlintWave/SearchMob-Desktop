"""Brave API adapter: header injection, no-key-no-call, parsing, fail-soft."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.brave_api import fetch_brave_api
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext


def _payload() -> dict[str, object]:
    return {
        "web": {
            "results": [
                {
                    "url": "https://example.com/a",
                    "title": "Result A",
                    "description": "Brave hit A.",
                },
                {
                    "url": "https://example.com/b",
                    "title": "Result B",
                    "description": "Brave hit B.",
                },
            ]
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_sends_subscription_token_header_and_parses_results() -> None:
    route = respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json=_payload())
    )
    ctx = EngineContext(query="anything", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_brave_api(client, ctx, api_key="dummy")

    assert route.called
    sent = route.calls.last.request
    assert sent.headers.get("X-Subscription-Token") == "dummy"
    assert sent.headers.get("Accept") == "application/json"

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert results[0].title == "Result A"
    assert results[1].snippet == "Brave hit B."
    assert all(r.engine == "brave" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_no_key_means_no_http_call() -> None:
    route = respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json=_payload())
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_brave_api(client, ctx, api_key=None)

    assert results == []
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_401() -> None:
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_brave_api(client, ctx, api_key="bad")
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_unexpected_shape() -> None:
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": "oops"}})
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_brave_api(client, ctx, api_key="dummy")
    assert results == []
