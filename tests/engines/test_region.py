"""Locale -> engine region/language params, and that DuckDuckGo + Brave append them."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.brave_api import fetch_brave_api
from searchmob_desktop.engines.duckduckgo import fetch_duckduckgo
from searchmob_desktop.engines.region import language_region_for
from searchmob_desktop.engines.types import EngineContext


def test_language_region_lookup() -> None:
    assert language_region_for("en") is None
    assert language_region_for(None) is None
    assert language_region_for("xx") is None  # unmapped
    es = language_region_for("es-MX")  # region subtag tolerated
    assert es is not None and es.ddg_kl == "es-es" and es.brave_country == "ES"
    ar = language_region_for("ar")
    assert ar is not None and ar.brave_ui_lang == "ar-SA"


@pytest.mark.asyncio
@respx.mock
async def test_duckduckgo_appends_kl_for_a_locale() -> None:
    route = respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    ctx = EngineContext(query="gato", language_region=language_region_for("es"))
    async with httpx.AsyncClient() as client:
        await fetch_duckduckgo(client, ctx)
    assert route.calls.last.request.url.params.get("kl") == "es-es"


@pytest.mark.asyncio
@respx.mock
async def test_duckduckgo_no_kl_for_english() -> None:
    route = respx.get("https://html.duckduckgo.com/html/").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    async with httpx.AsyncClient() as client:
        await fetch_duckduckgo(client, EngineContext(query="cat"))
    assert "kl" not in route.calls.last.request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_brave_appends_country_lang_for_a_locale() -> None:
    route = respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": []}})
    )
    ctx = EngineContext(query="chat", language_region=language_region_for("fr"))
    async with httpx.AsyncClient() as client:
        await fetch_brave_api(client, ctx, api_key="k")
    params = route.calls.last.request.url.params
    assert params.get("country") == "FR"
    assert params.get("search_lang") == "fr"
    assert params.get("ui_lang") == "fr-FR"
