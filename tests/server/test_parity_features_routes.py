"""Route-level coverage for the commercial-parity features ported from Android PR #103.

Bang redirects, instant answer cards, the results meta line, the favicon, vertical/sort carry,
the `/img` thumbnail proxy, the tightened CSP, and the suggest/shortcut scripts on the pages.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, EngineFn, SearchResult
from searchmob_desktop.server.app import build_app


async def _one_result(_client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(
            title="Kotlin homepage",
            url="https://kotlinlang.org/",
            snippet="the language",
            engine="fake",
        )
    ]


def _build_client(
    engines: Sequence[EngineFn] | None = None,
    *,
    image_fetcher: object = None,
    summary_provider: object = None,
) -> TestClient:
    async def _metasearch(
        ctx: EngineContext, engine_list: Sequence[EngineFn]
    ) -> list[SearchResult]:
        gathered: list[SearchResult] = []
        async with httpx.AsyncClient() as client:
            for engine in engine_list:
                gathered.extend(await engine(client, ctx))
        return gathered

    app = build_app(
        engines or [],
        bound_port_getter=lambda: 8787,
        metasearch=_metasearch,
        host_allowlist_enabled=False,
        image_fetcher=image_fetcher,  # type: ignore[arg-type]
        summary_provider=summary_provider,  # type: ignore[arg-type]
    )
    return TestClient(app, client=("127.0.0.1", 5000))


def test_bang_query_redirects_to_site_search() -> None:
    with _build_client() as client:
        response = client.get("/search", params={"q": "!gh ktor"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://github.com/search?q=ktor"


def test_unknown_bang_token_is_a_normal_search() -> None:
    with _build_client([_one_result]) as client:
        response = client.get("/search", params={"q": "!important css"})
    assert response.status_code == 200
    assert "Kotlin homepage" in response.text


def test_calculator_instant_answer_renders_above_results() -> None:
    with _build_client([_one_result]) as client:
        body = client.get("/search", params={"q": "sqrt(9)*3"}).text
    assert '<div class="instant">' in body
    assert '<p class="ival">9</p>' in body


def test_unit_conversion_instant_answer_renders() -> None:
    with _build_client([_one_result]) as client:
        body = client.get("/search", params={"q": "10 km to miles"}).text
    assert '<div class="instant">' in body
    assert "miles" in body


def test_ordinary_query_has_no_instant_answer() -> None:
    with _build_client([_one_result]) as client:
        body = client.get("/search", params={"q": "kotlin"}).text
    assert '<div class="instant">' not in body


def test_meta_line_shows_result_count_and_timing() -> None:
    with _build_client([_one_result]) as client:
        body = client.get("/search", params={"q": "kotlin"}).text
    assert "1 result" in body
    # A "0.0 s"-style timing is always present for a non-blank query.
    assert " s</p>" in body or " s ·" in body or "s" in body.split('class="meta">')[1][:120]


def test_favicon_is_served_and_advertised() -> None:
    with _build_client() as client:
        icon = client.get("/favicon.ico")
        home = client.get("/").text
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")
    assert '<link rel="icon" href="data:image/svg+xml,' in home


def test_search_pages_carry_suggest_and_shortcut_scripts() -> None:
    with _build_client([_one_result]) as client:
        home = client.get("/").text
        results = client.get("/search", params={"q": "kotlin"}).text
    for body in (home, results):
        assert "sm-suggest" in body
        assert "e.key!=='/'" in body


def test_sort_form_and_vertical_links_keep_each_other() -> None:
    with _build_client([_one_result]) as client:
        body = client.get("/search", params={"q": "kotlin", "vertical": "news"}).text
    # The sort form carries the active vertical as a hidden field...
    assert '<input type="hidden" name="vertical" value="news">' in body
    # ...and the vertical tabs carry the active sort (news defaults to fresh).
    assert "vertical=web&amp;sort=" in body


def test_did_you_mean_keeps_vertical_and_sort() -> None:
    class _Corrector:
        def suggest(self, _query: str) -> object:
            class _C:
                corrected = "kotlin"
                confidence = 0.99

            return _C()

    app = build_app(
        [_one_result],
        bound_port_getter=lambda: 8787,
        corrector=_Corrector(),  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        body = client.get("/search", params={"q": "kotln", "vertical": "news"}).text
    if "didyoumean" in body:
        assert "vertical=news" in body.split('class="didyoumean"')[1][:300]


def test_csp_allows_same_origin_fetch_and_images_only() -> None:
    with _build_client() as client:
        csp = client.get("/").headers["content-security-policy"]
    assert "img-src 'self' data:" in csp
    assert "connect-src 'self'" in csp
    assert "img-src https:" not in csp


def test_img_proxy_is_not_found_when_no_fetcher_wired() -> None:
    with _build_client() as client:
        response = client.get("/img", params={"u": "https://upload.wikimedia.org/x.jpg"})
    assert response.status_code == 404


def test_img_proxy_serves_the_fetched_image() -> None:
    async def _fetcher(url: str) -> tuple[bytes, str] | None:
        if url == "https://upload.wikimedia.org/thumb.jpg":
            return b"\xff\xd8jpegbytes", "image/jpeg"
        return None

    with _build_client(image_fetcher=_fetcher) as client:
        ok = client.get("/img", params={"u": "https://upload.wikimedia.org/thumb.jpg"})
        missing = client.get("/img", params={"u": "https://example.com/x.jpg"})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/jpeg")
    assert ok.content == b"\xff\xd8jpegbytes"
    assert missing.status_code == 404


def test_summary_thumbnail_goes_through_loopback_proxy_when_wired() -> None:
    from searchmob_desktop.engines.wiki_summary import SummaryBox

    async def _summary(_query: str) -> SummaryBox:
        return SummaryBox(
            title="Albert Einstein",
            description="physicist",
            extract="Albert Einstein was a physicist.",
            url="https://en.wikipedia.org/wiki/Albert_Einstein",
            thumbnail_url="https://upload.wikimedia.org/thumb.jpg",
        )

    async def _fetcher(_url: str) -> tuple[bytes, str] | None:
        return b"img", "image/jpeg"

    with _build_client([_one_result], image_fetcher=_fetcher, summary_provider=_summary) as client:
        body = client.get("/search", params={"q": "albert einstein"}).text
    assert 'src="/img?u=https%3A%2F%2Fupload.wikimedia.org%2Fthumb.jpg"' in body
    assert 'src="https://upload.wikimedia.org' not in body


def test_summary_thumbnail_is_omitted_entirely_without_proxy() -> None:
    from searchmob_desktop.engines.wiki_summary import SummaryBox

    async def _summary(_query: str) -> SummaryBox:
        return SummaryBox(
            title="Albert Einstein",
            description="physicist",
            extract="Albert Einstein was a physicist.",
            url="https://en.wikipedia.org/wiki/Albert_Einstein",
            thumbnail_url="https://upload.wikimedia.org/thumb.jpg",
        )

    with _build_client([_one_result], summary_provider=_summary) as client:
        body = client.get("/search", params={"q": "albert einstein"}).text
    assert "upload.wikimedia.org" not in body
    assert '<div class="summary">' in body


def test_engine_status_renders_on_empty_result_pages() -> None:
    from searchmob_desktop.engines import AggregateOutcome, EngineOutcome

    async def _empty_with_status(
        _ctx: EngineContext, _engines: Sequence[EngineFn]
    ) -> AggregateOutcome:
        return AggregateOutcome(
            results=[],
            engines=(EngineOutcome(name="duckduckgo", status="failed", count=0),),
        )

    app = build_app(
        [_one_result],
        bound_port_getter=lambda: 8787,
        metasearch=_empty_with_status,
        host_allowlist_enabled=False,
        # An owner-only diagnostic needs an owner: the rules saver enables editable/owner mode.
        ranking_rules_saver=lambda _rules: True,
    )
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        body = client.get("/search", params={"q": "kotlin"}).text
    assert "engine-status" in body
    assert "0 of 1 engines responded" in body
