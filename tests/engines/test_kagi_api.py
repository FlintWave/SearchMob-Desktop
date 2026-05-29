"""Kagi API adapter: POST + Bearer auth, no-key-no-call, parsing, fail-soft."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.kagi_api import fetch_kagi_api
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext

_ENDPOINT = "https://kagi.com/api/v1/search"


def _payload() -> dict[str, object]:
    # Mirrors Kagi v1: results live under data.search[]. A non-result block (no url) is included
    # to confirm the adapter skips it, matching the Android adapter's behavior.
    return {
        "data": {
            "search": [
                {"t": 0, "url": "https://example.com/a", "title": "Result A", "snippet": "Hit A."},
                {"t": 1, "list": ["related", "searches"]},
                {"t": 0, "url": "https://example.com/b", "title": "Result B", "snippet": "Hit B."},
            ]
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_posts_with_bearer_auth_and_json_body_then_parses() -> None:
    route = respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_payload()))
    ctx = EngineContext(query="searchmob", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_kagi_api(client, ctx, api_key="dummy")

    assert route.called
    sent = route.calls.last.request
    assert sent.method == "POST"
    assert sent.headers.get("Authorization") == "Bearer dummy"
    assert sent.headers.get("Accept") == "application/json"
    import json

    assert json.loads(sent.content.decode()) == {"query": "searchmob"}

    # The non-result block (no url) is skipped; the two real hits parse in order.
    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert results[0].title == "Result A"
    assert results[1].snippet == "Hit B."
    assert all(r.engine == "kagi-api" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_no_key_means_no_http_call() -> None:
    route = respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_payload()))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_kagi_api(client, ctx, api_key=None)

    assert results == []
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_respects_max_results() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json=_payload()))
    ctx = EngineContext(query="anything", max_results=1)
    async with make_privacy_client() as client:
        results = await fetch_kagi_api(client, ctx, api_key="dummy")
    assert [r.url for r in results] == ["https://example.com/a"]


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_401() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_kagi_api(client, ctx, api_key="bad")
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_unexpected_shape() -> None:
    respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json={"data": {"search": "oops"}}))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_kagi_api(client, ctx, api_key="dummy")
    assert results == []
