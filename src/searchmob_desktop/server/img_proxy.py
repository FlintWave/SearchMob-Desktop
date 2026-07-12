"""Server-side fetcher behind the `/img` thumbnail proxy, ported from Android's `ThumbnailProxy`.

The Wikipedia summary card's thumbnail is re-served from the loopback origin so the BROWSER never
contacts Wikimedia directly. Without this, the served page embedded an `upload.wikimedia.org`
image URL and the user's browser fetched it with the user's real IP - the image filename names
the searched entity, which is exactly the query-subject-to-third-party leak the metasearch proxy
exists to prevent. The app fetches it through the same privacy-proxied httpx stack (pinned pool
UA, no cookies) and hands the bytes back to the `/img` route.

Strictly scoped against SSRF: only https URLs on the Wikimedia upload host are ever fetched, only
image content types are re-served, and the body is size-capped. Anything else yields None and the
card simply renders without a picture.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

import httpx

from searchmob_desktop.engines.proxy import fetch_bounded, make_privacy_client

__all__ = ["fetch_thumbnail", "is_allowed_thumbnail_url"]

# The only host the proxy will fetch from - where Wikipedia REST summaries host thumbnails.
_ALLOWED_HOST: Final = "upload.wikimedia.org"

# Cap well below the engine-body cap: a summary thumbnail is tens of kilobytes.
_MAX_IMAGE_BYTES: Final = 1 * 1024 * 1024


def is_allowed_thumbnail_url(url: str) -> bool:
    """True when `url` is an https URL this proxy is willing to fetch."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme.lower() == "https" and parts.netloc.lower() == _ALLOWED_HOST


async def fetch_thumbnail(url: str) -> tuple[bytes, str] | None:
    """Fetch `url` (must pass `is_allowed_thumbnail_url`) as `(bytes, content_type)`, else None."""
    if not is_allowed_thumbnail_url(url):
        return None
    try:
        async with make_privacy_client() as client:
            body = await fetch_bounded(client, "GET", url, max_bytes=_MAX_IMAGE_BYTES)
            if body is None:
                return None
            # `fetch_bounded` raised for non-2xx already; sanitize the type to image-only so the
            # proxy can never be coaxed into re-serving markup from the loopback origin.
            # The final response's content type is not exposed by fetch_bounded, so re-derive it
            # from the URL suffix conservatively.
            content_type = _image_content_type(url)
            if content_type is None:
                return None
            return body, content_type
    except httpx.HTTPError:
        return None


def _image_content_type(url: str) -> str | None:
    """A safe image content type for `url`, or None when the extension is not a known image."""
    path = urlsplit(url).path.lower()
    # Raster formats only: an SVG navigated to directly is a document that can carry script, and
    # Wikipedia's thumb endpoint always rasterizes anyway.
    for suffix, content_type in (
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
        (".gif", "image/gif"),
        (".webp", "image/webp"),
    ):
        if path.endswith(suffix):
            return content_type
    return None
