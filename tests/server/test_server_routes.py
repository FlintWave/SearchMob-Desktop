"""Route surface contract for the local HTTP server.

Each test exercises one observable behaviour from the spec: the routes, the OpenSearch
advertisement, the JSON shape and query echo, the length cap, the http/https anchor allowlist,
the HTML escaping, and the OpenSearch Suggestions endpoint (default + provider). Drives the
Starlette app via `TestClient`; we never spin uvicorn here because uvicorn is only relevant to
runtime networking, not routing.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Sequence

import httpx
from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, EngineFn, SearchResult
from searchmob_desktop.server.app import MAX_QUERY_LENGTH, build_app

_OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"


def _build_client(
    engines: Sequence[EngineFn] | None = None,
    *,
    port: int = 8787,
    host: str = "127.0.0.1",
    suggestions_provider: object = None,
) -> TestClient:
    """Wire a TestClient over the Starlette app with a fake metasearch.

    The default `metasearch` does not run the real aggregator (which would open httpx sockets);
    instead it calls each `engines` entry directly with a dummy client and concatenates the
    returned lists in order. That keeps these tests hermetic while still exercising the route's
    handoff to the engine functions.
    """

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
        bound_port_getter=lambda: port,
        bound_host_getter=lambda: host,
        suggestions_provider=suggestions_provider,  # type: ignore[arg-type]
        metasearch=_metasearch,
    )
    return TestClient(app)


def test_healthz_returns_ok_plain_text() -> None:
    with _build_client() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["content-type"].startswith("text/plain")


def test_home_advertises_opensearch_descriptor_link() -> None:
    with _build_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.text
    # The browser auto-discovery hook: rel="search", the OpenSearch MIME, the descriptor href.
    assert 'rel="search"' in body
    assert 'type="application/opensearchdescription+xml"' in body
    assert 'href="/opensearch.xml"' in body
    assert 'title="SearchMob"' in body


def test_opensearch_descriptor_advertises_both_search_and_suggestions() -> None:
    with _build_client(port=9999, host="127.0.0.1") as client:
        response = client.get("/opensearch.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/opensearchdescription+xml")

    root = ET.fromstring(response.text)
    urls = root.findall(f"{{{_OPENSEARCH_NS}}}Url")
    types_to_templates = {url.attrib["type"]: url.attrib["template"] for url in urls}
    assert "text/html" in types_to_templates
    assert "application/x-suggestions+json" in types_to_templates
    # The templates must point at the live origin and carry the OpenSearch {searchTerms} token.
    assert types_to_templates["text/html"] == "http://127.0.0.1:9999/search?q={searchTerms}"
    assert (
        types_to_templates["application/x-suggestions+json"]
        == "http://127.0.0.1:9999/suggest?q={searchTerms}"
    )
    # And the descriptor advertises the SearchMob identity.
    assert root.find(f"{{{_OPENSEARCH_NS}}}ShortName").text == "SearchMob"  # type: ignore[union-attr]


async def _engine_alpha(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(
            title="Alpha one",
            url="https://example.com/a1",
            snippet="from alpha",
            engine="alpha",
        ),
        SearchResult(
            title="Alpha two",
            url="https://example.com/a2",
            snippet="",
            engine="alpha",
        ),
    ]


async def _engine_beta(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(
            title="Beta one",
            url="https://example.com/b1",
            snippet="from beta",
            engine="beta",
        ),
    ]


def test_search_json_returns_aggregated_results_and_echoes_query() -> None:
    with _build_client(engines=[_engine_alpha, _engine_beta]) as client:
        response = client.get("/api/search", params={"q": "hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    payload = response.json()
    assert payload["query"] == "hello"
    # The fake metasearch concatenates engines in input order; we assert the route hands them
    # through unchanged (no extra rewriting between the aggregator and the response).
    urls = [item["url"] for item in payload["results"]]
    assert urls == [
        "https://example.com/a1",
        "https://example.com/a2",
        "https://example.com/b1",
    ]
    # Every result dict carries the four keys the contract documents.
    for item in payload["results"]:
        assert set(item.keys()) == {"title", "url", "snippet", "engine"}


def test_search_json_caps_query_length() -> None:
    long_q = "x" * (MAX_QUERY_LENGTH + 100)
    with _build_client() as client:
        response = client.get("/api/search", params={"q": long_q})
    assert response.status_code == 200
    payload = response.json()
    # The echoed query is the clamped value, not the original. No more than MAX_QUERY_LENGTH chars.
    assert payload["query"] == "x" * MAX_QUERY_LENGTH
    assert len(payload["query"]) == MAX_QUERY_LENGTH


async def _engine_mixed_scheme(
    _client: httpx.AsyncClient, _ctx: EngineContext
) -> list[SearchResult]:
    return [
        SearchResult(
            title="Safe link",
            url="https://example.com/safe",
            snippet="",
            engine="x",
        ),
        SearchResult(
            title="Hostile link",
            url="javascript:alert(1)",
            snippet="",
            engine="x",
        ),
    ]


def test_search_html_only_renders_http_https_anchors() -> None:
    with _build_client(engines=[_engine_mixed_scheme]) as client:
        response = client.get("/search", params={"q": "scheme test"})
    assert response.status_code == 200
    body = response.text
    # https URL gets a clickable anchor pointing at itself.
    assert '<a href="https://example.com/safe"' in body
    # The hostile javascript: URL must NEVER appear inside an href attribute.
    assert 'href="javascript:' not in body
    # The hostile title is still rendered, but as inert text (a span, not an anchor).
    assert "Hostile link" in body


def test_search_html_escapes_query_and_titles() -> None:
    async def _engine_evil_title(
        _client: httpx.AsyncClient, _ctx: EngineContext
    ) -> list[SearchResult]:
        return [
            SearchResult(
                title="<script>x()</script>",
                url="https://example.com/evil",
                snippet="<img onerror=1>",
                engine="evil",
            ),
        ]

    with _build_client(engines=[_engine_evil_title]) as client:
        response = client.get("/search", params={"q": "<script>"})
    assert response.status_code == 200
    body = response.text
    # The query echoed in the title and in the results metadata is escaped.
    assert "<title>&lt;script&gt; · SearchMob</title>" in body
    # The result title is escaped wherever it's rendered.
    assert "&lt;script&gt;x()&lt;/script&gt;" in body
    # No raw <script> tags from user/upstream content (the embedded theme scripts the page emits
    # are static and live in templates.py, so a literal `<script>` from the query would be a bug).
    assert "<script>x()</script>" not in body


def test_search_html_blank_query_uses_searchmob_title() -> None:
    with _build_client() as client:
        # No `q` at all; the page must still render and the title must be the bare brand.
        response = client.get("/search")
    assert response.status_code == 200
    assert "<title>SearchMob</title>" in response.text


def test_suggest_returns_two_element_array_with_correct_content_type() -> None:
    with _build_client() as client:
        response = client.get("/suggest", params={"q": "python"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-suggestions+json")
    payload = json.loads(response.text)
    # Two-element array: [echoed query, suggestions list]. No suggestions provider wired -> [].
    assert payload == ["python", []]


def test_suggest_blank_query_echoes_empty_string() -> None:
    with _build_client() as client:
        response = client.get("/suggest", params={"q": "   "})
    assert response.status_code == 200
    assert json.loads(response.text) == ["", []]

    # And with no q at all.
    with _build_client() as client:
        response = client.get("/suggest")
    assert json.loads(response.text) == ["", []]


def test_suggest_caps_query_length() -> None:
    long_q = "y" * (MAX_QUERY_LENGTH + 50)
    with _build_client() as client:
        response = client.get("/suggest", params={"q": long_q})
    payload = json.loads(response.text)
    assert payload[0] == "y" * MAX_QUERY_LENGTH


def test_suggest_uses_provided_provider() -> None:
    def _stub(query: str, _limit: int) -> list[str]:
        return ["alpha", "beta"] if query else []

    with _build_client(suggestions_provider=_stub) as client:
        response = client.get("/suggest", params={"q": "a"})
    payload = json.loads(response.text)
    assert payload == ["a", ["alpha", "beta"]]

    # Default provider (no stub) returns an empty list for the same input.
    with _build_client() as client:
        response = client.get("/suggest", params={"q": "a"})
    assert json.loads(response.text) == ["a", []]
