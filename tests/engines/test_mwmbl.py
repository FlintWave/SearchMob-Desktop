"""Mwmbl JSON parser (with fragment-array title/extract) + fail-soft behavior."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.mwmbl import fetch_mwmbl
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext


@pytest.mark.asyncio
@respx.mock
async def test_maps_mwmbl_payload_concatenating_fragments() -> None:
    payload = [
        {
            "url": "https://example.com/a",
            "title": [
                {"value": "Result ", "is_bold": False},
                {"value": "A", "is_bold": True},
            ],
            "extract": [
                {"value": "Extract ", "is_bold": False},
                {"value": "for A", "is_bold": True},
                {"value": ".", "is_bold": False},
            ],
        },
        {
            "url": "https://example.com/b",
            "title": [{"value": "Result B", "is_bold": False}],
            "extract": [{"value": "Extract for B.", "is_bold": False}],
        },
    ]
    respx.get("https://api.mwmbl.org/search/").mock(return_value=httpx.Response(200, json=payload))
    ctx = EngineContext(query="anything", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_mwmbl(client, ctx)

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert results[0].title == "Result A"
    assert results[0].snippet == "Extract for A."
    assert results[1].snippet == "Extract for B."
    assert all(r.engine == "mwmbl" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_500() -> None:
    respx.get("https://api.mwmbl.org/search/").mock(return_value=httpx.Response(500))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mwmbl(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_non_json_body() -> None:
    respx.get("https://api.mwmbl.org/search/").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mwmbl(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_unexpected_shape() -> None:
    respx.get("https://api.mwmbl.org/search/").mock(
        return_value=httpx.Response(200, json={"not": "an array"})
    )
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mwmbl(client, ctx)
    assert results == []
