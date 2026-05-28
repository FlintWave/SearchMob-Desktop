"""Launch-time GitHub update check.

Mirrors the Android `UpdateChecker.kt` + `UpdateCheckCoordinator.kt` contract:
once a day (default), ask `api.github.com` for the latest release tag, compare
versionCodes (`YY*10000 + MM*100 + VV`), and surface an update if the published
tag's code is strictly greater than the running app's. Routed through the
existing privacy-proxy `httpx.AsyncClient` so the request carries no cookies
and rotates the User-Agent like every other outbound call.

Fail-soft is non-negotiable: ANY transport error, HTTP error, JSON parse
failure, or oversized response returns `None` instead of raising. Update
checks must never block or crash the app.

The check is opt-out (default on) and disclosed in `README.md` and
`SECURITY.md` as the only outbound traffic that is not a search.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

import httpx

from searchmob_desktop.prefs import UserPreferences

__all__ = [
    "DEFAULT_INTERVAL_MS",
    "LATEST_RELEASE_API_URL",
    "MAX_RESPONSE_BYTES",
    "RELEASES_PAGE_URL",
    "UpdateInfo",
    "VersionTag",
    "check_if_due",
    "fetch_latest",
    "is_update_check_due",
]

LATEST_RELEASE_API_URL: Final = (
    "https://api.github.com/repos/FlintWave/SearchMob-Desktop/releases/latest"
)
RELEASES_PAGE_URL: Final = "https://github.com/FlintWave/SearchMob-Desktop/releases/latest"

# Throttle window: about one calendar day. Mirrors the Android default.
DEFAULT_INTERVAL_MS: Final = 24 * 3600 * 1000

# Bounded body read: a GitHub release JSON is a few KiB; anything past 16 KiB
# is treated as suspect rather than parsed. Matches the bounded-read pattern
# the security audit codified on the Android side.
MAX_RESPONSE_BYTES: Final = 16 * 1024


@dataclass(frozen=True, slots=True)
class VersionTag:
    """Parsed `YY.MM.VV` version tag.

    `parse` strips a leading `v`, splits on `.`, and tolerates a `-suffix` on
    the build segment (so `v26.05.00-rc1` parses to `26.05.00`). Anything that
    does not split cleanly into three integer parts returns `None`.
    """

    year: int
    month: int
    build: int

    def to_version_code(self) -> int:
        return self.year * 10000 + self.month * 100 + self.build

    @classmethod
    def parse(cls, tag: str) -> VersionTag | None:
        if not isinstance(tag, str):
            return None
        cleaned = tag.strip()
        if cleaned.startswith("v") or cleaned.startswith("V"):
            cleaned = cleaned[1:]
        # Strip any prerelease/build suffix that follows a `-` BEFORE splitting on `.`, so tags like
        # `26.05.00-rc1` and `26.05.00-pre.1` both reduce to `26.05.00` cleanly.
        if "-" in cleaned:
            cleaned = cleaned.split("-", 1)[0]
        parts = cleaned.split(".")
        if len(parts) != 3:
            return None
        year_s, month_s, build_s = parts
        try:
            year, month, build = int(year_s), int(month_s), int(build_s)
        except ValueError:
            return None
        if year < 0 or month < 0 or build < 0:
            return None
        return cls(year=year, month=month, build=build)


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """A newer release the user could download."""

    latest_version: VersionTag
    release_url: str

    def is_newer_than(self, current_code: int) -> bool:
        return self.latest_version.to_version_code() > current_code


async def fetch_latest(
    client: httpx.AsyncClient,
    *,
    base_url: str = LATEST_RELEASE_API_URL,
) -> UpdateInfo | None:
    """GET the GitHub Releases latest endpoint and parse it, fail-soft.

    Returns `None` on any HTTP error, transport error, oversized body,
    malformed JSON, missing fields, or a tag that does not parse as
    `YY.MM.VV`. Callers must never assume an exception.
    """
    try:
        response = await client.get(base_url, headers={"Accept": "application/vnd.github+json"})
    except (httpx.HTTPError, httpx.InvalidURL):
        return None
    if response.status_code != 200:
        return None

    content = response.content
    if len(content) > MAX_RESPONSE_BYTES:
        return None
    try:
        payload: Any = json.loads(content.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    tag = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not isinstance(tag, str):
        return None
    version = VersionTag.parse(tag)
    if version is None:
        return None
    release_url = html_url if isinstance(html_url, str) and html_url else RELEASES_PAGE_URL
    return UpdateInfo(latest_version=version, release_url=release_url)


def is_update_check_due(
    last_check_ms: int,
    *,
    now_ms: int,
    interval_ms: int = DEFAULT_INTERVAL_MS,
) -> bool:
    """True when a check has never run (`last_check_ms <= 0`) or the interval has elapsed."""
    if last_check_ms <= 0:
        return True
    return (now_ms - last_check_ms) >= interval_ms


async def check_if_due(
    prefs: UserPreferences,
    current_code: int,
    *,
    now_ms: int,
    client_factory: Callable[[], httpx.AsyncClient | Awaitable[httpx.AsyncClient]],
    interval_ms: int = DEFAULT_INTERVAL_MS,
) -> tuple[UpdateInfo | None, int]:
    """Throttled launch check. Returns `(maybe_info, stamped_last_check_ms)`.

    - If `prefs.update_check_enabled` is False, returns `(None, prefs.last_update_check_ms)`
      WITHOUT contacting the network.
    - If the throttle is not due, returns `(None, prefs.last_update_check_ms)` without contacting
      the network.
    - Otherwise builds a client (sync or async factory accepted), runs `fetch_latest`, and stamps
      `now_ms` regardless of outcome so the caller can persist it.

    The returned `UpdateInfo` is `None` unless a newer-than-current version was actually published.
    """
    if not prefs.update_check_enabled:
        return None, prefs.last_update_check_ms
    if not is_update_check_due(prefs.last_update_check_ms, now_ms=now_ms, interval_ms=interval_ms):
        return None, prefs.last_update_check_ms

    client_or_awaitable = client_factory()
    if isinstance(client_or_awaitable, httpx.AsyncClient):
        client = client_or_awaitable
    else:
        client = await client_or_awaitable

    try:
        info = await fetch_latest(client)
    finally:
        await client.aclose()

    if info is None or not info.is_newer_than(current_code):
        return None, now_ms
    return info, now_ms
