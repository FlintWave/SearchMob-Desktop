"""The contextual Wikipedia summary box on the served results page."""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.wiki_summary import SummaryBox
from searchmob_desktop.server.app import build_app


async def _empty_metasearch(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return []


_BOX = SummaryBox(
    title="Mount Everest",
    description="Earth's highest mountain",
    extract="Mount Everest is Earth's highest mountain above sea level.",
    url="https://en.wikipedia.org/wiki/Mount_Everest",
    thumbnail_url="https://upload.wikimedia.org/everest.jpg",
)


async def _provider(query: str) -> SummaryBox | None:
    return _BOX if query == "everest" else None


def _client(provider: object) -> TestClient:
    app = build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "127.0.0.1",
        summary_provider=provider,  # type: ignore[arg-type]
        metasearch=_empty_metasearch,
        host_allowlist_enabled=False,
    )
    return TestClient(app)


def test_summary_box_rendered_when_provider_returns_one() -> None:
    with _client(_provider) as client:
        html = client.get("/search", params={"q": "everest"}).text
    assert 'class="summary"' in html
    assert "Mount Everest" in html
    assert "highest mountain" in html
    assert "https://en.wikipedia.org/wiki/Mount_Everest" in html
    assert "From Wikipedia" in html


def test_no_summary_box_when_provider_returns_none() -> None:
    with _client(_provider) as client:
        html = client.get("/search", params={"q": "something else"}).text
    assert 'class="summary"' not in html


def test_no_summary_box_without_a_provider() -> None:
    with _client(None) as client:
        html = client.get("/search", params={"q": "everest"}).text
    assert 'class="summary"' not in html
