"""Served Settings page: the owner-only `GET /settings` view and `POST /settings/prefs` writes.

Same harness as the rules-endpoint tests: `TestClient(app, client=(host, port))` sets the ASGI
client so we can simulate a loopback owner vs a network visitor for the owner-only gate. A prefs
holder stands in for the JSON prefs store (load + save).
"""

from __future__ import annotations

from dataclasses import replace

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.app import build_app


class _Prefs:
    """In-memory stand-in for the prefs store (provider + saver over a frozen UserPreferences)."""

    def __init__(self, prefs: UserPreferences | None = None) -> None:
        self.prefs = prefs if prefs is not None else UserPreferences()

    def load(self) -> UserPreferences:
        return self.prefs

    def save(self, prefs: UserPreferences) -> bool:
        self.prefs = prefs
        return True


async def _one_result(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="A page", url="https://news.example/x", snippet="s", engine="e")]


async def _summary_box(_query: str) -> object:
    from searchmob_desktop.engines.wiki_summary import SummaryBox

    return SummaryBox(
        title="Cats",
        description="mammal",
        extract="Cats are small.",
        url="https://en.wikipedia.org/wiki/Cat",
    )


def _app(prefs: _Prefs | None, *, host: str = "127.0.0.1", with_summary: bool = False) -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: host,
        prefs_provider=prefs.load if prefs else None,
        prefs_saver=prefs.save if prefs else None,
        summary_provider=_summary_box if with_summary else None,  # type: ignore[arg-type]
        metasearch=_one_result,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _loopback(app: object) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]


def _remote(app: object) -> TestClient:
    return TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]


def test_owner_sees_settings_page_reflecting_current_prefs() -> None:
    prefs = _Prefs(UserPreferences(sort_mode="date", ai_slop_mode="hide"))
    with _loopback(_app(prefs)) as client:
        resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Settings" in resp.text
    # The current values are pre-selected in the form.
    assert '<option value="date" selected>' in resp.text
    assert '<option value="hide" selected>' in resp.text


def test_remote_visitor_cannot_see_settings() -> None:
    prefs = _Prefs()
    with _remote(_app(prefs)) as client:
        assert client.get("/settings").status_code == 404


def test_no_saver_means_no_settings_page() -> None:
    with _loopback(_app(None)) as client:
        assert client.get("/settings").status_code == 404
        assert client.post("/settings/prefs", data={"sort_mode": "date"}).status_code == 503


def test_loopback_post_updates_prefs_and_redirects() -> None:
    prefs = _Prefs(UserPreferences(summary_enabled=True, upstream_suggestions_enabled=False))
    with _loopback(_app(prefs)) as client:
        resp = client.post(
            "/settings/prefs",
            data={
                "sort_mode": "relevance",
                "ai_slop_mode": "off",
                "upstream_suggestions_enabled": "on",
                # summary_enabled omitted == unchecked.
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings?saved=1"
    assert prefs.prefs.sort_mode == "relevance"
    assert prefs.prefs.ai_slop_mode == "off"
    assert prefs.prefs.summary_enabled is False
    assert prefs.prefs.upstream_suggestions_enabled is True


def test_post_rejects_invalid_values_keeping_current() -> None:
    prefs = _Prefs(UserPreferences(sort_mode="fresh", ai_slop_mode="downrank"))
    with _loopback(_app(prefs)) as client:
        client.post("/settings/prefs", data={"sort_mode": "bogus", "ai_slop_mode": "nonsense"})
    assert prefs.prefs.sort_mode == "fresh"
    assert prefs.prefs.ai_slop_mode == "downrank"


def test_remote_post_is_forbidden() -> None:
    prefs = _Prefs(UserPreferences(sort_mode="fresh"))
    with _remote(_app(prefs)) as client:
        assert client.post("/settings/prefs", data={"sort_mode": "date"}).status_code == 403
    assert prefs.prefs.sort_mode == "fresh"


def test_settings_link_shown_to_owner_only() -> None:
    prefs = _Prefs()
    with _loopback(_app(prefs)) as client:
        assert 'href="/settings"' in client.get("/").text
        assert 'href="/settings"' in client.get("/search", params={"q": "hi"}).text
    with _remote(_app(prefs)) as client:
        assert 'href="/settings"' not in client.get("/").text


def test_summary_toggle_gates_the_card_live() -> None:
    # Summary provider wired, but the live pref controls whether the card renders.
    prefs = _Prefs(UserPreferences(summary_enabled=False))
    with _loopback(_app(prefs, with_summary=True)) as client:
        assert "From Wikipedia" not in client.get("/search", params={"q": "cats"}).text
    prefs.prefs = replace(prefs.prefs, summary_enabled=True)
    with _loopback(_app(prefs, with_summary=True)) as client:
        assert "From Wikipedia" in client.get("/search", params={"q": "cats"}).text


def test_default_sort_follows_prefs_on_web() -> None:
    prefs = _Prefs(UserPreferences(sort_mode="date"))
    with _loopback(_app(prefs)) as client:
        html = client.get("/search", params={"q": "hi"}).text
    # No explicit ?sort, Web vertical: the sort bar reflects the prefs default.
    assert '<option value="date" selected>' in html
