"""The served sort control and the `?sort=` query parameter."""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.server.app import build_app

_NEW = 1_900_000_000_000  # newer epoch ms
_OLD = 1_700_000_000_000  # older epoch ms


async def _metasearch(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    # Returned in relevance order: undated first, then old, then new.
    return [
        SearchResult("Undated", "https://e/undated", "", "x", published=None),
        SearchResult("Old", "https://e/old", "", "x", published=_OLD),
        SearchResult("New", "https://e/new", "", "x", published=_NEW),
    ]


def _client() -> TestClient:
    app = build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "127.0.0.1",
        metasearch=_metasearch,
        host_allowlist_enabled=False,
    )
    return TestClient(app)


def _order(html: str, *urls: str) -> list[str]:
    return sorted(urls, key=lambda u: html.find(u))


def test_sort_bar_present_with_selected_option() -> None:
    with _client() as client:
        html = client.get("/search", params={"q": "hi", "sort": "date"}).text
    assert 'name="sort"' in html
    assert '<option value="date" selected>' in html


def test_date_sort_orders_newest_first_then_undated() -> None:
    with _client() as client:
        html = client.get("/search", params={"q": "hi", "sort": "date"}).text
    assert _order(html, "https://e/new", "https://e/old", "https://e/undated") == [
        "https://e/new",
        "https://e/old",
        "https://e/undated",
    ]


def test_relevance_sort_keeps_input_order() -> None:
    with _client() as client:
        html = client.get("/search", params={"q": "hi", "sort": "relevance"}).text
    assert _order(html, "https://e/undated", "https://e/old", "https://e/new") == [
        "https://e/undated",
        "https://e/old",
        "https://e/new",
    ]
