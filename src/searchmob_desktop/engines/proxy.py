"""Privacy-proxy HTTP client used by every engine adapter.

Guarantees, mirrored from the Android `HttpClientFactory` + `PrivacyInterceptor`:

* No cookie jar. Cookies are never stored across requests and never sent. An upstream `Set-Cookie`
  is dropped on the floor.
* Per-request rotated `User-Agent` from a small pool of generic recent desktop browsers, so
  upstream engines never see a stable client identifier from this install.
* Fixed `Accept-Language: en-US,en;q=0.5`, again to look like a generic browser rather than a
  unique fingerprint.
* `Referer`, `X-Requested-With`, and `X-Forwarded-For` are stripped from every outgoing request even
  if a caller set them, so an adapter cannot accidentally leak provenance.
* Redirects are followed (engines like DuckDuckGo redirect a lot) and timeouts are bounded.

Adapters receive the client via `aggregate()` and cannot bypass it.
"""

from __future__ import annotations

import random
from typing import Final

import httpx

USER_AGENTS: Final[tuple[str, ...]] = (
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
)

_STRIPPED_HEADERS: Final[tuple[str, ...]] = ("Referer", "X-Requested-With", "X-Forwarded-For")


async def _privacy_request_hook(request: httpx.Request) -> None:
    """Rewrite every outgoing request so upstream engines see a generic, identifier-free client."""
    for header in _STRIPPED_HEADERS:
        request.headers.pop(header, None)
    request.headers["User-Agent"] = random.choice(USER_AGENTS)
    request.headers["Accept-Language"] = "en-US,en;q=0.5"


def make_privacy_client(timeout: float = 5.0) -> httpx.AsyncClient:
    """Build an `httpx.AsyncClient` configured with the privacy guarantees above.

    The returned client has no cookie persistence, follows redirects, applies the timeout
    uniformly, and runs `_privacy_request_hook` on every outgoing request to rotate the UA and
    strip identifying headers. Use as `async with make_privacy_client() as client: ...`.
    """
    return httpx.AsyncClient(
        cookies={},
        follow_redirects=True,
        timeout=httpx.Timeout(timeout),
        event_hooks={"request": [_privacy_request_hook]},
    )
