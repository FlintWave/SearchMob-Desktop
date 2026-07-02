"""Google-style operators on the served `/search` and `/api/search` endpoints.

The routes parse the operators once: the engine query (operators the engines understand) goes
upstream, the structural filters are enforced locally over the merged results, the echoed `query`
keeps the original text, and the on-device corrector is skipped for operator-laden queries. The
fake metasearch records the `EngineContext` so the forwarded query and the operator-free
`ranking_terms` are both observable.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.correct import Correction
from searchmob_desktop.server.app import build_app

_RESULTS = [
    SearchResult(title="Guide", url="https://docs.example/guide.html", snippet="s", engine="e"),
    SearchResult(title="Thread", url="https://forum.example/t/1", snippet="s", engine="e"),
    SearchResult(title="Manual", url="https://docs.example/manual.pdf", snippet="s", engine="e"),
]


class _Recorder:
    """Remembers the context the route handed to the metasearch runner."""

    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.ctx: EngineContext | None = None
        self.results = results if results is not None else list(_RESULTS)


def _client(recorder: _Recorder, corrector: object = None) -> TestClient:
    async def _metasearch(ctx: EngineContext, _engines: object) -> list[SearchResult]:
        recorder.ctx = ctx
        return list(recorder.results)

    app = build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "127.0.0.1",
        corrector=corrector,  # type: ignore[arg-type]
        metasearch=_metasearch,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )
    return TestClient(app, client=("127.0.0.1", 9))


def test_engine_query_is_forwarded_and_local_filters_are_enforced() -> None:
    recorder = _Recorder()
    with _client(recorder) as client:
        resp = client.get("/api/search", params={"q": "rust tutorial -site:forum.example"})
    body = resp.json()
    # The engines see the operators they understand; the exclusion is also enforced locally.
    assert recorder.ctx is not None
    assert recorder.ctx.query == "rust tutorial -site:forum.example"
    urls = [r["url"] for r in body["results"]]
    assert "https://forum.example/t/1" not in urls
    assert "https://docs.example/guide.html" in urls
    # The echo keeps the original text.
    assert body["query"] == "rust tutorial -site:forum.example"


def test_ranking_terms_carry_the_operator_free_text() -> None:
    recorder = _Recorder()
    with _client(recorder) as client:
        client.get("/api/search", params={"q": "rust tutorial site:docs.example filetype:pdf"})
    assert recorder.ctx is not None
    # The lexical scorer reasons about the clean text, never the scoping clauses.
    assert recorder.ctx.ranking_terms == "rust tutorial"
    assert recorder.ctx.query == "rust tutorial site:docs.example filetype:pdf"


def test_local_only_operators_are_stripped_from_the_engine_query() -> None:
    recorder = _Recorder()
    with _client(recorder) as client:
        resp = client.get(
            "/api/search", params={"q": "rust intitle:tutorial -inurl:forum after:2023"}
        )
    assert recorder.ctx is not None
    # intitle: becomes a bare recall hint; -inurl:/after: are dropped from the upstream query.
    assert recorder.ctx.query == "rust tutorial"
    # after:2023 excludes every undated fake result, so the filters demonstrably ran locally.
    assert resp.json()["results"] == []


def test_filetype_filter_applies_over_merged_results() -> None:
    recorder = _Recorder()
    with _client(recorder) as client:
        body = client.get("/api/search", params={"q": "manual filetype:pdf"}).json()
    urls = [r["url"] for r in body["results"]]
    assert urls == ["https://docs.example/manual.pdf"]


def test_html_route_enforces_filters_and_echoes_the_original_query() -> None:
    recorder = _Recorder()
    with _client(recorder) as client:
        resp = client.get("/search", params={"q": "rust tutorial -site:forum.example"})
    assert resp.status_code == 200
    assert "docs.example" in resp.text
    assert "forum.example/t/1" not in resp.text
    # The search box round-trips the original operator-laden text.
    assert "rust tutorial -site:forum.example" in resp.text


class _AlwaysCorrector:
    """Suggests a fixed rewrite for anything, to prove the operator skip."""

    def suggest(self, _query: str) -> Correction:
        return Correction(corrected="rust tutorial", confidence=0.9)


def test_corrector_is_skipped_for_operator_laden_queries() -> None:
    with _client(_Recorder(), corrector=_AlwaysCorrector()) as client:
        with_ops = client.get("/api/search", params={"q": "rust tutoriall site:docs.example"})
        plain = client.get("/api/search", params={"q": "rust tutoriall"})
    # The operator query gets no on-device suggestion; the plain one still does.
    assert with_ops.json()["correction"] is None
    assert plain.json()["correction"] == "rust tutorial"
