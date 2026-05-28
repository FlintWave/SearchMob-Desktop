"""Privacy guarantees of the shared httpx client."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.proxy import USER_AGENTS, make_privacy_client


@pytest.mark.asyncio
@respx.mock
async def test_no_cookie_header_sent() -> None:
    route = respx.get("https://example.test/").mock(return_value=httpx.Response(200, text="ok"))
    async with make_privacy_client() as client:
        await client.get("https://example.test/")
    assert route.called
    assert "cookie" not in {h.lower() for h in route.calls.last.request.headers.keys()}


@pytest.mark.asyncio
@respx.mock
async def test_strips_identifying_headers_even_if_caller_set_them() -> None:
    route = respx.get("https://example.test/").mock(return_value=httpx.Response(200, text="ok"))
    async with make_privacy_client() as client:
        await client.get(
            "https://example.test/",
            headers={
                "Referer": "https://leaky.example/",
                "X-Requested-With": "XMLHttpRequest",
                "X-Forwarded-For": "10.0.0.1",
            },
        )
    sent_headers = {h.lower(): v for h, v in route.calls.last.request.headers.items()}
    assert "referer" not in sent_headers
    assert "x-requested-with" not in sent_headers
    assert "x-forwarded-for" not in sent_headers


@pytest.mark.asyncio
@respx.mock
async def test_accept_language_is_fixed() -> None:
    route = respx.get("https://example.test/").mock(return_value=httpx.Response(200, text="ok"))
    async with make_privacy_client() as client:
        await client.get("https://example.test/")
    assert route.calls.last.request.headers["Accept-Language"] == "en-US,en;q=0.5"


@pytest.mark.asyncio
@respx.mock
async def test_user_agent_is_from_pool_and_rotates_over_many_requests() -> None:
    respx.get("https://example.test/").mock(return_value=httpx.Response(200, text="ok"))
    seen: set[str] = set()
    async with make_privacy_client() as client:
        for _ in range(40):
            response = await client.get("https://example.test/")
            assert response.status_code == 200
            ua = response.request.headers["User-Agent"]
            assert ua in USER_AGENTS
            seen.add(ua)
    # With 5 UAs and 40 picks, the chance of seeing only one is ~5 * (1/5)**39, vanishing.
    assert len(seen) > 1
