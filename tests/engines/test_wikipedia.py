"""Wikipedia OpenSearch parser + fail-soft behavior."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext
from searchmob_desktop.engines.wikipedia import fetch_wikipedia


@pytest.mark.asyncio
@respx.mock
async def test_maps_opensearch_payload() -> None:
    payload = [
        "python",
        ["Python", "Python (programming language)"],
        ["A snake.", "A programming language."],
        [
            "https://en.wikipedia.org/wiki/Python",
            "https://en.wikipedia.org/wiki/Python_(programming_language)",
        ],
    ]
    respx.get("https://en.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(200, json=payload)
    )
    ctx = EngineContext(query="python", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_wikipedia(client, ctx)

    assert [r.title for r in results] == ["Python", "Python (programming language)"]
    assert results[0].url == "https://en.wikipedia.org/wiki/Python"
    assert results[1].snippet == "A programming language."
    assert all(r.engine == "wikipedia" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_non_json_body() -> None:
    respx.get("https://en.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    ctx = EngineContext(query="python")
    async with make_privacy_client() as client:
        results = await fetch_wikipedia(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_500() -> None:
    respx.get("https://en.wikipedia.org/w/api.php").mock(return_value=httpx.Response(500))
    ctx = EngineContext(query="python")
    async with make_privacy_client() as client:
        results = await fetch_wikipedia(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_unexpected_shape() -> None:
    respx.get("https://en.wikipedia.org/w/api.php").mock(
        return_value=httpx.Response(200, json={"oops": "not a list"})
    )
    ctx = EngineContext(query="python")
    async with make_privacy_client() as client:
        results = await fetch_wikipedia(client, ctx)
    assert results == []
