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
    corrector: object = None,
    ranking_rules: object = None,
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
        corrector=corrector,  # type: ignore[arg-type]
        ranking_rules=ranking_rules,  # type: ignore[arg-type]
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


async def _engine_two_domains(
    _client: httpx.AsyncClient, _ctx: EngineContext
) -> list[SearchResult]:
    return [
        SearchResult(title="Good", url="https://good.example/p", snippet="", engine="x"),
        SearchResult(title="Spam", url="https://spam.example/p", snippet="", engine="x"),
        SearchResult(title="Other", url="https://other.example/p", snippet="", engine="x"),
    ]


def test_ranking_rules_block_and_pin_apply_to_served_results() -> None:
    from searchmob_desktop.engines.rank import RankingRules, RankRule

    rules = RankingRules(
        domain_rules={"spam.example": RankRule.BLOCK, "other.example": RankRule.PIN}
    )
    with _build_client(engines=[_engine_two_domains], ranking_rules=rules) as client:
        payload = client.get("/api/search", params={"q": "x"}).json()
    urls = [r["url"] for r in payload["results"]]
    # spam.example is dropped; other.example is pinned to the top.
    assert "https://spam.example/p" not in urls
    assert urls[0] == "https://other.example/p"
    assert "https://good.example/p" in urls


def test_no_ranking_rules_leaves_results_untouched() -> None:
    with _build_client(engines=[_engine_two_domains]) as client:
        payload = client.get("/api/search", params={"q": "x"}).json()
    urls = [r["url"] for r in payload["results"]]
    assert urls == [
        "https://good.example/p",
        "https://spam.example/p",
        "https://other.example/p",
    ]


class _StubCorrector:
    """Suggests a fixed correction for one trigger query; returns None otherwise."""

    def __init__(self, trigger: str, corrected: str) -> None:
        self._trigger = trigger
        self._corrected = corrected

    def suggest(self, query: str):  # type: ignore[no-untyped-def]
        from searchmob_desktop.engines.correct import Correction

        if query.strip().lower() == self._trigger:
            return Correction(corrected=self._corrected, confidence=0.9)
        return None


def test_search_html_shows_did_you_mean_link() -> None:
    corrector = _StubCorrector("arnld swartzeneger", "arnold schwarzenegger")
    with _build_client(corrector=corrector) as client:
        response = client.get("/search", params={"q": "arnld swartzeneger"})
    body = response.text
    assert "Did you mean" in body
    # Links to a re-run of the search with the corrected query (url-encoded).
    assert "/search?q=arnold+schwarzenegger" in body
    assert "arnold schwarzenegger" in body


def test_search_json_includes_correction_field() -> None:
    corrector = _StubCorrector("teh", "the")
    with _build_client(corrector=corrector) as client:
        hit = client.get("/api/search", params={"q": "teh"})
        miss = client.get("/api/search", params={"q": "the"})
    assert json.loads(hit.text)["correction"] == "the"
    # No correction for a query the corrector leaves alone; the field is still present (None).
    assert json.loads(miss.text)["correction"] is None


def test_no_correction_without_a_corrector() -> None:
    with _build_client() as client:
        response = client.get("/api/search", params={"q": "anything"})
    assert json.loads(response.text)["correction"] is None


def test_is_loopback_host_classifies_addresses() -> None:
    from searchmob_desktop.server import is_loopback_host

    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("127.5.5.5")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert is_loopback_host(" LocalHost ")
    # Network-reachable binds are not loopback -> the history-suggestion guard engages.
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.10")
    assert not is_loopback_host("::")


def test_security_headers_present_on_responses() -> None:
    with _build_client() as client:
        r = client.get("/healthz")
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_result_anchors_carry_noreferrer() -> None:
    with _build_client(engines=[_engine_alpha]) as client:
        body = client.get("/search", params={"q": "x"}).text
    # External result links must not leak the query via Referer.
    assert 'rel="noopener noreferrer"' in body
