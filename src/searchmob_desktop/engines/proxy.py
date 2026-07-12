"""Privacy-proxy HTTP client used by every engine adapter.

Guarantees, mirrored from the Android `HttpClientFactory` + `PrivacyInterceptor`:

* No cookie jar. Cookies are never stored across requests and never sent. An upstream `Set-Cookie`
  is dropped on the floor.
* One `User-Agent` per logical search, picked from a small pool of generic recent desktop
  browsers. Each search's client pins one UA for its whole conversation (initial requests and
  their redirect hops alike): switching identities between requests seconds apart from the same
  IP is itself a bot signature. Across searches the pick rotates, so upstream engines still never
  see a stable client identifier from this install.
* Fixed `Accept-Language: en-US,en;q=0.5`, again to look like a generic browser rather than a
  unique fingerprint.
* `Referer`, `X-Requested-With`, and `X-Forwarded-For` are stripped from every outgoing request even
  if a caller set them, so an adapter cannot accidentally leak provenance.
* Redirects are followed (engines like DuckDuckGo redirect a lot) and timeouts are bounded, with a
  whole-call deadline on top of httpx's per-phase timeouts (a per-read timeout resets on every
  packet, so a server that trickles bytes could otherwise hold a search open for minutes).
* Per-host politeness spacing is process-wide: consecutive requests to the same upstream host are
  spaced by a minimum interval no matter which search issued them.

Adapters receive the client via `aggregate()` and cannot bypass it.
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Final
from urllib.parse import urlsplit

import httpx

# Hard cap on a single engine response body. Upstream engines return at most a few hundred KiB of
# HTML/JSON; this bounds memory so a hostile or compromised upstream (or a redirect target) cannot
# OOM the app by streaming an unbounded body. Reads abort past this and fail soft.
MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024

USER_AGENTS: Final[tuple[str, ...]] = (
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:139.0) Gecko/20100101 Firefox/139.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:139.0) Gecko/20100101 Firefox/139.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:139.0) Gecko/20100101 Firefox/139.0",
)

_STRIPPED_HEADERS: Final[tuple[str, ...]] = ("Referer", "X-Requested-With", "X-Forwarded-For")

# Minimum spacing between consecutive requests to the same upstream host, across ALL searches.
# One shared table (guarded by a plain lock, since GUI searches run on their own event loops in
# worker threads): the next slot for a host is RESERVED under the lock and only the sleep happens
# outside it, so two concurrent requests to the same host get consecutive slots instead of both
# slipping through a read-sleep-write race. Mirrors the Android `Politeness` class.
_POLITENESS_INTERVAL_SECONDS: Final = 1.0
_politeness_lock = threading.Lock()
_next_slot_by_host: dict[str, float] = {}

# A whole-call deadline on top of the per-phase httpx timeouts. The per-read timeout resets on
# every packet, so a server that trickles bytes (or a slow 8 MB body) could otherwise hold a
# search open for minutes past the engine deadline.
_CALL_DEADLINE_SECONDS: Final = 8.0


async def _acquire_politeness_slot(host: str) -> None:
    """Sleep until this process's reserved request slot for `host` arrives."""
    if not host:
        return
    with _politeness_lock:
        now = time.monotonic()
        earliest = _next_slot_by_host.get(host, now)
        reserved = max(now, earliest)
        _next_slot_by_host[host] = reserved + _POLITENESS_INTERVAL_SECONDS
    wait = reserved - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)


def _make_privacy_request_hook(user_agent: str) -> Callable[[httpx.Request], Awaitable[None]]:
    """Build a request hook that pins `user_agent` and strips identifying headers."""

    async def hook(request: httpx.Request) -> None:
        for header in _STRIPPED_HEADERS:
            request.headers.pop(header, None)
        request.headers["User-Agent"] = user_agent
        request.headers["Accept-Language"] = "en-US,en;q=0.5"

    return hook


def make_privacy_client(timeout: float = 5.0) -> httpx.AsyncClient:
    """Build an `httpx.AsyncClient` configured with the privacy guarantees above.

    The returned client has no cookie persistence, follows redirects, applies the timeout
    uniformly, and pins one pool User-Agent for its lifetime (one client = one logical search),
    stripping identifying headers on every request. Use as
    `async with make_privacy_client() as client: ...`.
    """
    return httpx.AsyncClient(
        cookies={},
        follow_redirects=True,
        timeout=httpx.Timeout(timeout),
        event_hooks={"request": [_make_privacy_request_hook(random.choice(USER_AGENTS))]},
        # Ignore HTTP(S)_PROXY / NO_PROXY / SSLKEYLOGFILE from the environment so a hostile env
        # cannot silently route or log the user's search traffic.
        trust_env=False,
    )


async def fetch_bounded(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: object | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> bytes | None:
    """Stream a request and return the body, or `None` if it exceeds `max_bytes` (or errors).

    Raises `httpx.HTTPError` for transport/status problems so adapters keep their existing
    fail-soft `except httpx.HTTPError` handling; returns `None` when the body is too large so an
    unbounded response can never be fully buffered into memory. The whole call (politeness wait
    excluded) runs under `_CALL_DEADLINE_SECONDS`, surfaced as an `httpx.ReadTimeout` so the same
    fail-soft path handles a byte-trickling upstream.
    """
    await _acquire_politeness_slot(urlsplit(url).netloc.lower())
    try:
        async with asyncio.timeout(_CALL_DEADLINE_SECONDS):
            async with client.stream(method, url, headers=headers, json=json) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
    except TimeoutError as exc:
        raise httpx.ReadTimeout(f"whole-call deadline exceeded for {url}") from exc
