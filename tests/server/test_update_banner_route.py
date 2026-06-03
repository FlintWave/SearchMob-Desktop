"""Served pages show the "update available" banner only to the loopback owner.

A network visitor must never see it (they cannot install anything and it would leak the owner's
version), and a pending record that is not actually newer than the running build must not render.
"""

from __future__ import annotations

from dataclasses import replace

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.app import _CURRENT_VERSION_CODE, build_app
from searchmob_desktop.update import VersionTag

# A version strictly newer than the running build, formatted the way prefs stores it.
_NEWER = VersionTag(
    _CURRENT_VERSION_CODE // 10000,
    (_CURRENT_VERSION_CODE // 100) % 100,
    (_CURRENT_VERSION_CODE % 100) + 1,
).formatted()
_RELEASE_URL = "https://example.test/r/newer"


async def _metasearch(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="One", url="https://a.example/1", snippet="s", engine="e")]


def _app(prefs: UserPreferences) -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "0.0.0.0",
        prefs_provider=lambda: prefs,
        metasearch=_metasearch,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _pending_prefs() -> UserPreferences:
    return UserPreferences(
        pending_update_version=_NEWER,
        pending_update_url=_RELEASE_URL,
    )


def test_owner_sees_update_banner_on_home_and_results() -> None:
    app = _app(_pending_prefs())
    owner = TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]
    home = owner.get("/").text
    assert 'class="updatebar"' in home
    assert _RELEASE_URL in home
    assert f"SearchMob {_NEWER} is available." in home

    results = owner.get("/search", params={"q": "hi"}).text
    assert 'class="updatebar"' in results
    assert _RELEASE_URL in results


def test_network_visitor_never_sees_update_banner() -> None:
    app = _app(_pending_prefs())
    remote = TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]
    assert 'class="updatebar"' not in remote.get("/").text
    assert 'class="updatebar"' not in remote.get("/search", params={"q": "hi"}).text


def test_no_banner_when_pending_not_newer_than_current() -> None:
    # Pending equals the running version -> stale, must not render (self-clears after an update).
    current = VersionTag(
        _CURRENT_VERSION_CODE // 10000,
        (_CURRENT_VERSION_CODE // 100) % 100,
        _CURRENT_VERSION_CODE % 100,
    ).formatted()
    prefs = replace(_pending_prefs(), pending_update_version=current)
    owner = TestClient(_app(prefs), client=("127.0.0.1", 9))  # type: ignore[arg-type]
    assert 'class="updatebar"' not in owner.get("/").text


def test_no_banner_when_no_pending_record() -> None:
    owner = TestClient(_app(UserPreferences()), client=("127.0.0.1", 9))  # type: ignore[arg-type]
    assert 'class="updatebar"' not in owner.get("/").text
