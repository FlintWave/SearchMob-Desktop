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
from dataclasses import dataclass, replace
from typing import Any, Final

import httpx

from searchmob_desktop.prefs import UserPreferences

__all__ = [
    "DEFAULT_INTERVAL_MS",
    "LATEST_RELEASE_API_URL",
    "MAX_RESPONSE_BYTES",
    "RELEASES_PAGE_URL",
    "SHA256SUMS_ASSET_NAME",
    "ReleaseAsset",
    "UpdateInfo",
    "VersionTag",
    "asset_for_system",
    "check_if_due",
    "fetch_latest",
    "is_update_check_due",
    "reconcile_pending_update",
]

LATEST_RELEASE_API_URL: Final = (
    "https://api.github.com/repos/FlintWave/SearchMob-Desktop/releases/latest"
)
RELEASES_PAGE_URL: Final = "https://github.com/FlintWave/SearchMob-Desktop/releases/latest"

# Throttle window: about one calendar day. Mirrors the Android default.
DEFAULT_INTERVAL_MS: Final = 24 * 3600 * 1000

# Bounded body read: a GitHub release JSON carries the tag plus the per-platform asset list
# (installer download URLs + the SHA256SUMS entry), so it runs larger than the tag-only payload
# the first cut parsed. 64 KiB comfortably covers a release with a dozen assets while still
# treating anything past it as suspect rather than parsing it. Matches the bounded-read pattern
# the security audit codified on the Android side.
MAX_RESPONSE_BYTES: Final = 64 * 1024

# The integrity-anchor asset published alongside the installers (see the release workflow). The
# updater verifies a downloaded installer's SHA-256 against the matching line in this file.
SHA256SUMS_ASSET_NAME: Final = "SHA256SUMS"


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

    def formatted(self) -> str:
        """The canonical `YY.MM.VV` string (zero-padded), matching the version-file format."""
        return f"{self.year:02d}.{self.month:02d}.{self.build:02d}"

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
class ReleaseAsset:
    """One published installer (or the SHA256SUMS file) attached to a GitHub release."""

    name: str
    download_url: str
    size: int = 0


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """A newer release the user could download, plus its published assets."""

    latest_version: VersionTag
    release_url: str
    assets: tuple[ReleaseAsset, ...] = ()

    def is_newer_than(self, current_code: int) -> bool:
        return self.latest_version.to_version_code() > current_code

    def asset_for_system(self, system: str) -> ReleaseAsset | None:
        """The single installer asset for the running platform, or None when it is ambiguous.

        macOS picks the `.dmg`, Windows the `.msi`. Linux is deliberately left to fall back to the
        release page: this build ships `.deb`, `.rpm`, and `.flatpak`, and nothing in a running
        instance reliably says which one the user installed, so guessing risks the wrong package.
        """
        return asset_for_system(self.assets, system)

    def checksums_asset(self) -> ReleaseAsset | None:
        """The SHA256SUMS asset used to verify a downloaded installer's integrity, if published."""
        for asset in self.assets:
            if asset.name == SHA256SUMS_ASSET_NAME:
                return asset
        return None


def asset_for_system(assets: tuple[ReleaseAsset, ...], system: str) -> ReleaseAsset | None:
    """Pick the installer asset matching `system` (a `sys.platform` string), or None.

    Returns the first asset whose name ends with the platform's installer suffix: `.dmg` on macOS
    (`darwin`), `.msi` on Windows (`win32`/`win...`). Any other platform (Linux included) returns
    None so the caller opens the release page instead of downloading a possibly-wrong package.
    """
    sys_lower = system.lower()
    if sys_lower.startswith("darwin"):
        suffix = ".dmg"
    elif sys_lower.startswith("win"):
        suffix = ".msi"
    else:
        return None
    for asset in assets:
        if asset.name.lower().endswith(suffix):
            return asset
    return None


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
    return UpdateInfo(
        latest_version=version,
        release_url=release_url,
        assets=_parse_assets(payload.get("assets")),
    )


def _parse_assets(raw: Any) -> tuple[ReleaseAsset, ...]:
    """Parse the release `assets` array into `ReleaseAsset`s, skipping malformed entries.

    Fail-soft like the rest of the parser: a non-list, or an entry missing a usable name or
    `browser_download_url`, is simply dropped rather than raising.
    """
    if not isinstance(raw, list):
        return ()
    assets: list[ReleaseAsset] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        url = entry.get("browser_download_url")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(url, str) or not url:
            continue
        size = entry.get("size")
        assets.append(
            ReleaseAsset(name=name, download_url=url, size=size if isinstance(size, int) else 0)
        )
    return tuple(assets)


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


def reconcile_pending_update(
    prefs: UserPreferences, info: UpdateInfo | None, *, stamped: int
) -> UserPreferences:
    """Fold a check result into prefs: stamp the check time and set/clear the pending-update fields.

    `info` is the newer-than-current release (as returned by `check_if_due`), or None. `stamped` is
    that call's returned timestamp. The pending fields drive the GUI/web banners, so they must both
    appear when an update is found AND disappear once a check confirms the user is current (e.g.
    after they updated). They are only cleared when a check actually ran (`stamped` advanced), so a
    throttled no-op never wipes a still-valid banner.
    """
    checked = stamped != prefs.last_update_check_ms
    base = replace(prefs, last_update_check_ms=stamped) if checked else prefs
    if info is not None:
        return replace(
            base,
            pending_update_version=info.latest_version.formatted(),
            pending_update_url=info.release_url,
        )
    if checked:
        return replace(base, pending_update_version="", pending_update_url="")
    return base
