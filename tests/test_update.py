"""Unit tests for the launch-time GitHub update check."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.update import (
    LATEST_RELEASE_API_URL,
    RELEASES_PAGE_URL,
    SHA256SUMS_ASSET_NAME,
    ReleaseAsset,
    UpdateInfo,
    VersionTag,
    asset_for_system,
    check_if_due,
    fetch_latest,
    is_update_check_due,
    reconcile_pending_update,
)

# --- VersionTag.parse -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("v26.05.00", VersionTag(26, 5, 0)),
        ("26.05.00", VersionTag(26, 5, 0)),
        ("V26.05.02", VersionTag(26, 5, 2)),
        ("26.05.00-rc1", VersionTag(26, 5, 0)),
        ("26.05.00-pre.1", VersionTag(26, 5, 0)),
    ],
)
def test_version_tag_parses_supported_shapes(raw: str, expected: VersionTag) -> None:
    parsed = VersionTag.parse(raw)
    assert parsed == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "garbage",
        "26.05",
        "26.05.00.0",
        "v26.may.00",
        "26.-1.0",
    ],
)
def test_version_tag_parse_rejects_malformed(raw: str) -> None:
    assert VersionTag.parse(raw) is None


def test_version_code_formula_matches_android() -> None:
    assert VersionTag(26, 5, 1).to_version_code() == 260501


def test_version_tag_formatted_is_zero_padded() -> None:
    assert VersionTag(26, 6, 1).formatted() == "26.06.01"
    assert VersionTag(26, 12, 10).formatted() == "26.12.10"


def test_is_newer_than_compares_codes() -> None:
    info = UpdateInfo(latest_version=VersionTag(26, 5, 2), release_url="x")
    assert info.is_newer_than(260501) is True
    assert info.is_newer_than(260502) is False
    assert info.is_newer_than(260503) is False


# --- fetch_latest -----------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_returns_info_on_valid_response() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(
        200,
        json={"tag_name": "v26.05.02", "html_url": "https://example.test/r/v26.05.02"},
    )
    async with httpx.AsyncClient() as client:
        info = await fetch_latest(client)
    assert info == UpdateInfo(
        latest_version=VersionTag(26, 5, 2),
        release_url="https://example.test/r/v26.05.02",
    )


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_falls_back_to_releases_page_when_html_url_missing() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(200, json={"tag_name": "v26.05.01"})
    async with httpx.AsyncClient() as client:
        info = await fetch_latest(client)
    assert info is not None
    assert info.release_url == RELEASES_PAGE_URL


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_returns_none_on_http_error() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(404)
    async with httpx.AsyncClient() as client:
        assert await fetch_latest(client) is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_returns_none_on_malformed_json() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(200, content=b"{not json")
    async with httpx.AsyncClient() as client:
        assert await fetch_latest(client) is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_returns_none_on_unparseable_tag() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(200, json={"tag_name": "garbage"})
    async with httpx.AsyncClient() as client:
        assert await fetch_latest(client) is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_returns_none_on_transport_error() -> None:
    respx.get(LATEST_RELEASE_API_URL).mock(side_effect=httpx.ConnectError("network down"))
    async with httpx.AsyncClient() as client:
        assert await fetch_latest(client) is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_returns_none_on_oversized_body() -> None:
    big = json.dumps({"tag_name": "v26.05.00", "padding": "x" * 100_000}).encode()
    respx.get(LATEST_RELEASE_API_URL).respond(200, content=big)
    async with httpx.AsyncClient() as client:
        assert await fetch_latest(client) is None


# --- assets -----------------------------------------------------------------------------------


def _release_json_with_assets() -> dict[str, object]:
    return {
        "tag_name": "v26.07.00",
        "html_url": "https://example.test/r/v26.07.00",
        "assets": [
            {
                "name": "SearchMob-26.07.00.dmg",
                "browser_download_url": "https://example.test/dl/app.dmg",
                "size": 12345,
            },
            {
                "name": "SearchMob-26.07.00.msi",
                "browser_download_url": "https://example.test/dl/app.msi",
            },
            {
                "name": "SearchMob_26.07.00_amd64.deb",
                "browser_download_url": "https://example.test/dl/app.deb",
            },
            {
                "name": "SHA256SUMS",
                "browser_download_url": "https://example.test/dl/SHA256SUMS",
            },
            # Malformed entries (missing url / not a dict) are skipped, not fatal.
            {"name": "broken-no-url"},
            "not-a-dict",
        ],
    }


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_parses_assets() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(200, json=_release_json_with_assets())
    async with httpx.AsyncClient() as client:
        info = await fetch_latest(client)
    assert info is not None
    names = [a.name for a in info.assets]
    assert names == [
        "SearchMob-26.07.00.dmg",
        "SearchMob-26.07.00.msi",
        "SearchMob_26.07.00_amd64.deb",
        "SHA256SUMS",
    ]
    assert info.assets[0].size == 12345
    assert info.assets[1].size == 0  # missing size defaults to 0


@respx.mock
@pytest.mark.asyncio
async def test_fetch_latest_tolerates_missing_assets_field() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(200, json={"tag_name": "v26.07.00"})
    async with httpx.AsyncClient() as client:
        info = await fetch_latest(client)
    assert info is not None
    assert info.assets == ()


def _info_with_assets() -> UpdateInfo:
    return UpdateInfo(
        latest_version=VersionTag(26, 7, 0),
        release_url="https://example.test/r",
        assets=(
            ReleaseAsset("SearchMob.dmg", "https://example.test/app.dmg"),
            ReleaseAsset("SearchMob.msi", "https://example.test/app.msi"),
            ReleaseAsset("SearchMob.deb", "https://example.test/app.deb"),
            ReleaseAsset(SHA256SUMS_ASSET_NAME, "https://example.test/SHA256SUMS"),
        ),
    )


def test_asset_for_system_picks_dmg_on_macos() -> None:
    asset = _info_with_assets().asset_for_system("darwin")
    assert asset is not None and asset.name == "SearchMob.dmg"


def test_asset_for_system_picks_msi_on_windows() -> None:
    asset = _info_with_assets().asset_for_system("win32")
    assert asset is not None and asset.name == "SearchMob.msi"


def test_asset_for_system_returns_none_on_linux() -> None:
    # Linux ships several package formats; the GUI falls back to the release page rather than guess.
    assert _info_with_assets().asset_for_system("linux") is None


def test_asset_for_system_returns_none_when_no_match() -> None:
    assets = (ReleaseAsset("only.deb", "https://example.test/app.deb"),)
    assert asset_for_system(assets, "darwin") is None


def test_checksums_asset_found_and_absent() -> None:
    assert _info_with_assets().checksums_asset() is not None
    no_sums = UpdateInfo(VersionTag(26, 7, 0), "u", assets=(ReleaseAsset("a.dmg", "u"),))
    assert no_sums.checksums_asset() is None


# --- reconcile_pending_update -----------------------------------------------------------------


def test_reconcile_sets_pending_when_update_found() -> None:
    prefs = UserPreferences(last_update_check_ms=0)
    info = UpdateInfo(VersionTag(26, 7, 0), "https://example.test/r/v26.07.00")
    out = reconcile_pending_update(prefs, info, stamped=10**12)
    assert out.pending_update_version == "26.07.00"
    assert out.pending_update_url == "https://example.test/r/v26.07.00"
    assert out.last_update_check_ms == 10**12


def test_reconcile_clears_pending_when_check_ran_and_up_to_date() -> None:
    prefs = UserPreferences(
        last_update_check_ms=0,
        pending_update_version="26.07.00",
        pending_update_url="https://example.test/old",
    )
    out = reconcile_pending_update(prefs, None, stamped=10**12)
    assert out.pending_update_version == ""
    assert out.pending_update_url == ""
    assert out.last_update_check_ms == 10**12


def test_reconcile_leaves_pending_untouched_when_throttled() -> None:
    # A throttled no-op (stamped == existing last check) must not wipe a still-valid banner.
    prefs = UserPreferences(
        last_update_check_ms=555,
        pending_update_version="26.07.00",
        pending_update_url="https://example.test/r",
    )
    out = reconcile_pending_update(prefs, None, stamped=555)
    assert out.pending_update_version == "26.07.00"
    assert out == prefs


# --- throttle ---------------------------------------------------------------------------------


def test_is_due_when_never_checked() -> None:
    assert is_update_check_due(0, now_ms=10**12) is True
    assert is_update_check_due(-1, now_ms=10**12) is True


def test_is_due_when_interval_elapsed() -> None:
    interval = 24 * 3600 * 1000
    assert is_update_check_due(10**12, now_ms=10**12 + interval, interval_ms=interval) is True


def test_not_due_within_interval() -> None:
    interval = 24 * 3600 * 1000
    assert is_update_check_due(10**12, now_ms=10**12 + interval - 1, interval_ms=interval) is False


# --- check_if_due -----------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_check_if_due_returns_info_when_enabled_and_newer() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(
        200, json={"tag_name": "v26.05.02", "html_url": "https://example.test/x"}
    )
    prefs = UserPreferences(update_check_enabled=True, last_update_check_ms=0)
    info, stamped = await check_if_due(
        prefs,
        current_code=260501,
        now_ms=10**12,
        client_factory=lambda: httpx.AsyncClient(),
    )
    assert info is not None and info.latest_version == VersionTag(26, 5, 2)
    assert stamped == 10**12


@respx.mock
@pytest.mark.asyncio
async def test_check_if_due_returns_none_when_not_newer_but_still_stamps() -> None:
    respx.get(LATEST_RELEASE_API_URL).respond(200, json={"tag_name": "v26.05.01"})
    prefs = UserPreferences(update_check_enabled=True, last_update_check_ms=0)
    info, stamped = await check_if_due(
        prefs,
        current_code=260501,
        now_ms=10**12,
        client_factory=lambda: httpx.AsyncClient(),
    )
    assert info is None
    assert stamped == 10**12


@respx.mock
@pytest.mark.asyncio
async def test_check_if_due_skips_network_when_disabled() -> None:
    """When the user opts out, no HTTP call goes out; the existing timestamp is preserved."""
    route = respx.get(LATEST_RELEASE_API_URL)
    prefs = UserPreferences(update_check_enabled=False, last_update_check_ms=12345)
    info, stamped = await check_if_due(
        prefs,
        current_code=0,
        now_ms=10**12,
        client_factory=lambda: httpx.AsyncClient(),
    )
    assert info is None
    assert stamped == 12345
    assert route.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_check_if_due_skips_network_when_not_due() -> None:
    """Within the throttle window, the function returns immediately and never opens a client."""
    route = respx.get(LATEST_RELEASE_API_URL)
    interval = 24 * 3600 * 1000
    prefs = UserPreferences(
        update_check_enabled=True,
        last_update_check_ms=10**12,
    )

    async def _exploding_factory() -> httpx.AsyncClient:  # would surface if called
        raise AssertionError("factory should not be called when throttle not due")

    info, stamped = await check_if_due(
        prefs,
        current_code=0,
        now_ms=10**12 + 1,  # well within the interval
        client_factory=_exploding_factory,
        interval_ms=interval,
    )
    assert info is None
    assert stamped == 10**12
    assert route.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_check_if_due_stamps_now_even_on_failure() -> None:
    """Failure must advance the throttle so a broken upstream cannot hammer GitHub each launch."""
    respx.get(LATEST_RELEASE_API_URL).respond(500)
    prefs = UserPreferences(update_check_enabled=True, last_update_check_ms=0)
    info, stamped = await check_if_due(
        prefs,
        current_code=0,
        now_ms=10**12,
        client_factory=lambda: httpx.AsyncClient(),
    )
    assert info is None
    assert stamped == 10**12
