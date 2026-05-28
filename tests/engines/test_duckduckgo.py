"""DuckDuckGo HTML parser + fail-soft behavior."""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest
import respx

from searchmob_desktop.engines.duckduckgo import fetch_duckduckgo
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.types import EngineContext


def _redirect(url: str) -> str:
    return f"//duckduckgo.com/l/?uddg={quote(url, safe='')}&rut=x"


def _fixture_html() -> str:
    ad_link = _redirect("https://ads.example/ad")
    a_link = _redirect("https://example.com/a")
    b_link = _redirect("https://example.com/b")
    return f"""
    <html><body>
      <div class="result result--ad">
        <a class="result__a" href="{ad_link}">Ad title</a>
        <div class="result__snippet">An ad we want filtered out.</div>
      </div>
      <div class="result">
        <a class="result__a" href="{a_link}">Result A</a>
        <a class="result__snippet">Snippet for A.</a>
      </div>
      <div class="result">
        <a class="result__a" href="{b_link}">Result B</a>
        <div class="result__snippet">Snippet for B.</div>
      </div>
    </body></html>
    """


@pytest.mark.asyncio
@respx.mock
async def test_parses_results_decodes_uddg_and_skips_ads() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_fixture_html())
    )
    ctx = EngineContext(query="anything", max_results=10)
    async with make_privacy_client() as client:
        results = await fetch_duckduckgo(client, ctx)

    assert [r.url for r in results] == ["https://example.com/a", "https://example.com/b"]
    assert [r.title for r in results] == ["Result A", "Result B"]
    assert results[0].snippet == "Snippet for A."
    assert results[1].snippet == "Snippet for B."
    assert all(r.engine == "duckduckgo" for r in results)


@pytest.mark.asyncio
@respx.mock
async def test_respects_max_results() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text=_fixture_html())
    )
    ctx = EngineContext(query="anything", max_results=1)
    async with make_privacy_client() as client:
        results = await fetch_duckduckgo(client, ctx)
    assert len(results) == 1


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_500() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(return_value=httpx.Response(500))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_duckduckgo(client, ctx)
    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_transport_error() -> None:
    respx.get("https://html.duckduckgo.com/html/").mock(side_effect=httpx.ConnectError("boom"))
    ctx = EngineContext(query="anything")
    async with make_privacy_client() as client:
        results = await fetch_duckduckgo(client, ctx)
    assert results == []
