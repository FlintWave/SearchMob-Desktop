"""The served category tabs and the `?vertical=` query parameter."""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.server.app import build_app


def _client_capturing(seen: list[str]) -> TestClient:
    async def _metasearch(ctx: EngineContext, _engines: object) -> list[SearchResult]:
        seen.append(ctx.query)
        return [SearchResult("R", "https://e/r", "", "x")]

    app = build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "127.0.0.1",
        metasearch=_metasearch,
        host_allowlist_enabled=False,
    )
    return TestClient(app)


def test_web_vertical_sends_query_verbatim() -> None:
    seen: list[str] = []
    with _client_capturing(seen) as client:
        client.get("/search", params={"q": "coffee", "vertical": "web"})
    assert seen == ["coffee"]


def test_forums_vertical_scopes_query_with_site_operators() -> None:
    seen: list[str] = []
    with _client_capturing(seen) as client:
        client.get("/search", params={"q": "coffee", "vertical": "forums"})
    assert seen, "metasearch was not called"
    scoped = seen[0]
    assert scoped.startswith("coffee (")
    assert "site:reddit.com" in scoped


def test_unknown_vertical_falls_back_to_web() -> None:
    seen: list[str] = []
    with _client_capturing(seen) as client:
        client.get("/search", params={"q": "coffee", "vertical": "bogus"})
    assert seen == ["coffee"]


def test_vertical_bar_marks_active_category() -> None:
    seen: list[str] = []
    with _client_capturing(seen) as client:
        html = client.get("/search", params={"q": "coffee", "vertical": "news"}).text
    assert 'class="verticalbar"' in html
    # The active chip carries the `active` class; inactive ones do not.
    assert 'class="chip active"' in html
    assert "vertical=academic" in html  # other categories are linked too


def test_json_route_accepts_vertical() -> None:
    seen: list[str] = []
    with _client_capturing(seen) as client:
        resp = client.get("/api/search", params={"q": "coffee", "vertical": "academic"})
    assert resp.status_code == 200
    assert seen[0].startswith("coffee (")
    assert "site:arxiv.org" in seen[0]
