"""Served media actions row: shown for a resolved media entity, gated by the Settings toggle."""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.wiki_summary import SummaryBox
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.app import build_app


async def _summary(_query: str) -> SummaryBox:
    return SummaryBox(
        title="Inception",
        description="2010 science fiction film directed by Christopher Nolan",
        extract="Inception is a 2010 film.",
        url="https://en.wikipedia.org/wiki/Inception",
    )


async def _metasearch(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="A page", url="https://a.example/x", snippet="s", engine="e")]


def _app(*, media_on: bool) -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        summary_provider=_summary,
        metasearch=_metasearch,  # type: ignore[arg-type]
        prefs_provider=lambda: UserPreferences(media_actions_enabled=media_on),
        host_allowlist_enabled=False,
    )


def test_actions_row_rendered_for_a_resolved_media_entity() -> None:
    client = TestClient(_app(media_on=True))
    html = client.get("/search", params={"q": "inception"}).text
    assert 'class="actions-row"' in html
    assert "Watch on" in html  # the Film & TV verb
    assert "imdb.com" in html  # a film platform deep link
    assert "en.wikipedia.org/wiki/Inception" in html  # Wikipedia leads the row


def test_no_actions_row_when_toggle_off() -> None:
    client = TestClient(_app(media_on=False))
    html = client.get("/search", params={"q": "inception"}).text
    assert 'class="actions-row"' not in html
