"""Mojeek HTML parser + fail-soft behavior."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.mojeek import fetch_mojeek
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext


def _fixture_html() -> str:
    return """
    <html><body>
      <ul class="results-standard">
        <li>
          <h2><a class="title" href="https://example.com/a">Result A</a></h2>
          <p class="s">Snippet for A.</p>
        </li>
        <li>
          <h2><a class="title" href="https://example.com/b">Result B</a></h2>
          <p class="s">Snippet for B.</p>
        </li>
        <li>
          <h2><a class="title" href="">No URL</a></h2>
          <p class="s">Should be skipped.</p>
        </li>
      </ul>
    </body></html>
    """


@pytest.mark.asyncio
@respx.mock
async def test_parses_mojeek_results() -> None:
    respx.get("https://www.mojeek.com/search").mock(
        return_value=httpx.Response(200, text=_fixture_html())
    )
    ctx = EngineContext(query="anything", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_mojeek(client, ctx)

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert [r.title for r in results] == ["Result A", "Result B"]
    assert results[0].snippet == "Snippet for A."
    assert all(r.engine == "mojeek" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_respects_max_results() -> None:
    respx.get("https://www.mojeek.com/search").mock(
        return_value=httpx.Response(200, text=_fixture_html())
    )
    ctx = EngineContext(query="anything", max_results=1)
    async with make_privacy_client() as client:
        results = await fetch_mojeek(client, ctx)
    assert len(results) == 1


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_500() -> None:
    respx.get("https://www.mojeek.com/search").mock(return_value=httpx.Response(500))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mojeek(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_transport_error() -> None:
    respx.get("https://www.mojeek.com/search").mock(side_effect=httpx.ConnectError("boom"))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_mojeek(client, ctx)
    assert results == []
