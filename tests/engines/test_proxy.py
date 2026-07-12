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
async def test_user_agent_is_pinned_within_a_client_and_rotates_across_clients() -> None:
    """One client = one logical search = one identity.

    Switching User-Agents between an initial request and a follow-up seconds later from the same
    IP is itself a bot signature, so a client pins one pool UA for its lifetime; fresh clients
    (fresh searches) still rotate so no stable identifier emerges across searches.
    """
    respx.get("https://example.test/").mock(return_value=httpx.Response(200, text="ok"))
    seen_across_clients: set[str] = set()
    for _ in range(40):
        async with make_privacy_client() as client:
            first = await client.get("https://example.test/")
            second = await client.get("https://example.test/")
        first_ua = first.request.headers["User-Agent"]
        assert first_ua in USER_AGENTS
        assert second.request.headers["User-Agent"] == first_ua
        seen_across_clients.add(first_ua)
    # With 5 UAs and 40 clients, the chance of seeing only one is ~5 * (1/5)**39, vanishing.
    assert len(seen_across_clients) > 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_bounded_returns_none_when_body_exceeds_cap() -> None:
    import httpx as _httpx

    from searchmob_desktop.engines.proxy import fetch_bounded

    respx.get("https://example.test/big").mock(
        return_value=_httpx.Response(200, content=b"x" * 5000)
    )
    async with make_privacy_client() as client:
        # Body (5000 bytes) exceeds the 1000-byte cap -> None (never fully buffered).
        assert (
            await fetch_bounded(client, "GET", "https://example.test/big", max_bytes=1000) is None
        )


@pytest.mark.asyncio
@respx.mock
async def test_fetch_bounded_returns_body_within_cap() -> None:
    import httpx as _httpx

    from searchmob_desktop.engines.proxy import fetch_bounded

    respx.get("https://example.test/ok").mock(return_value=_httpx.Response(200, content=b"hello"))
    async with make_privacy_client() as client:
        assert await fetch_bounded(client, "GET", "https://example.test/ok") == b"hello"


@pytest.mark.asyncio
@respx.mock
async def test_politeness_spaces_consecutive_requests_to_the_same_host() -> None:
    import time as _time

    from searchmob_desktop.engines import proxy as _proxy
    from searchmob_desktop.engines.proxy import fetch_bounded

    respx.get("https://slow.test/a").mock(return_value=httpx.Response(200, text="ok"))
    respx.get("https://slow.test/b").mock(return_value=httpx.Response(200, text="ok"))
    original = _proxy._POLITENESS_INTERVAL_SECONDS
    _proxy._POLITENESS_INTERVAL_SECONDS = 0.15
    try:
        _proxy._next_slot_by_host.pop("slow.test", None)
        async with make_privacy_client() as client:
            started = _time.monotonic()
            await fetch_bounded(client, "GET", "https://slow.test/a")
            await fetch_bounded(client, "GET", "https://slow.test/b")
            elapsed = _time.monotonic() - started
    finally:
        _proxy._POLITENESS_INTERVAL_SECONDS = original
        _proxy._next_slot_by_host.pop("slow.test", None)
    # The second request must wait for the host's next slot, so the pair spans the interval.
    assert elapsed >= 0.15


@pytest.mark.asyncio
@respx.mock
async def test_politeness_does_not_delay_distinct_hosts() -> None:
    import time as _time

    from searchmob_desktop.engines import proxy as _proxy
    from searchmob_desktop.engines.proxy import fetch_bounded

    respx.get("https://one.test/").mock(return_value=httpx.Response(200, text="ok"))
    respx.get("https://two.test/").mock(return_value=httpx.Response(200, text="ok"))
    original = _proxy._POLITENESS_INTERVAL_SECONDS
    _proxy._POLITENESS_INTERVAL_SECONDS = 0.5
    try:
        for host in ("one.test", "two.test"):
            _proxy._next_slot_by_host.pop(host, None)
        async with make_privacy_client() as client:
            started = _time.monotonic()
            await fetch_bounded(client, "GET", "https://one.test/")
            await fetch_bounded(client, "GET", "https://two.test/")
            elapsed = _time.monotonic() - started
    finally:
        _proxy._POLITENESS_INTERVAL_SECONDS = original
        for host in ("one.test", "two.test"):
            _proxy._next_slot_by_host.pop(host, None)
    # Different hosts have independent slots; the first request to each is immediate.
    assert elapsed < 0.4


@pytest.mark.asyncio
@respx.mock
async def test_whole_call_deadline_surfaces_as_read_timeout() -> None:
    import asyncio as _asyncio

    from searchmob_desktop.engines import proxy as _proxy
    from searchmob_desktop.engines.proxy import fetch_bounded

    async def _trickle(request: httpx.Request) -> httpx.Response:
        # A per-read timeout would reset on every byte; only the whole-call deadline stops this.
        async def body() -> object:
            while True:
                await _asyncio.sleep(0.02)
                yield b"x"

        return httpx.Response(200, stream=body())  # type: ignore[arg-type]

    respx.get("https://trickle.test/").mock(side_effect=_trickle)
    original = _proxy._CALL_DEADLINE_SECONDS
    _proxy._CALL_DEADLINE_SECONDS = 0.2
    try:
        async with make_privacy_client() as client:
            with pytest.raises(httpx.ReadTimeout):
                await fetch_bounded(client, "GET", "https://trickle.test/")
    finally:
        _proxy._CALL_DEADLINE_SECONDS = original
