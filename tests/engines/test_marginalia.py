"""Marginalia JSON parser + fail-soft behavior."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.marginalia import fetch_marginalia
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext


@pytest.mark.asyncio
@respx.mock
async def test_maps_marginalia_payload() -> None:
    payload = {
        "results": [
            {
                "url": "https://example.com/a",
                "title": "Result A",
                "description": "Indie web page A.",
            },
            {
                "url": "https://example.com/b",
                "title": "Result B",
                "description": "Indie web page B.",
            },
        ]
    }
    respx.get("https://api.marginalia-search.com/public/search/python").mock(
        return_value=httpx.Response(200, json=payload)
    )
    ctx = EngineContext(query="python", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_marginalia(client, ctx)

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert [r.title for r in results] == ["Result A", "Result B"]
    assert results[1].snippet == "Indie web page B."
    assert all(r.engine == "marginalia" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_non_json_body() -> None:
    respx.get("https://api.marginalia-search.com/public/search/python").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    ctx = EngineContext(query="python")
    async with make_privacy_client() as client:
        results = await fetch_marginalia(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_500() -> None:
    respx.get("https://api.marginalia-search.com/public/search/python").mock(
        return_value=httpx.Response(500)
    )
    ctx = EngineContext(query="python")
    async with make_privacy_client() as client:
        results = await fetch_marginalia(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_unexpected_shape() -> None:
    respx.get("https://api.marginalia-search.com/public/search/python").mock(
        return_value=httpx.Response(200, json={"oops": "not a results list"})
    )
    ctx = EngineContext(query="python")
    async with make_privacy_client() as client:
        results = await fetch_marginalia(client, ctx)
    assert results == []
