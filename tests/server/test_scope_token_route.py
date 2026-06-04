"""The inline ``+name`` scope token on the served `/search` and `/api/search` endpoints.

A matched token filters that one request through the named scope and runs the engines on the cleaned
query, while the echoed `query` keeps the original text. An unmatched token changes nothing, and the
saved active scope is never written (the token is transient).
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.rank import Lens, RankingRules
from searchmob_desktop.server.app import build_app

_RULES = RankingRules(
    lenses=(Lens(name="Research mode", include_domains=("arxiv.org",)),),
)

_RESULTS = [
    SearchResult(title="Paper", url="https://arxiv.org/abs/1", snippet="s", engine="e"),
    SearchResult(title="Pin", url="https://pinterest.com/x", snippet="s", engine="e"),
]


class _Holder:
    def __init__(self) -> None:
        self.rules = _RULES
        self.seen_query: str | None = None

    def load(self) -> RankingRules:
        return self.rules

    def save(self, rules: RankingRules) -> bool:
        self.rules = rules
        return True


def _app(holder: _Holder) -> object:
    async def _metasearch(ctx: EngineContext, _engines: object) -> list[SearchResult]:
        holder.seen_query = ctx.query
        return list(_RESULTS)

    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "127.0.0.1",
        ranking_rules_provider=holder.load,
        ranking_rules_saver=holder.save,
        metasearch=_metasearch,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _client(holder: _Holder) -> TestClient:
    return TestClient(_app(holder), client=("127.0.0.1", 9))  # type: ignore[arg-type]


def test_matched_token_filters_and_runs_cleaned_query() -> None:
    holder = _Holder()
    with _client(holder) as client:
        resp = client.get("/api/search", params={"q": "neural nets +research"})
    body = resp.json()
    # Engines saw the cleaned query, the scope filtered to its host, and the echo kept the token.
    assert holder.seen_query == "neural nets"
    urls = [r["url"] for r in body["results"]]
    assert urls == ["https://arxiv.org/abs/1"]
    assert body["query"] == "neural nets +research"
    # The token is transient: the saved active scope is untouched.
    assert holder.rules.active_lens is None


def test_unmatched_token_passes_through_unchanged() -> None:
    holder = _Holder()
    with _client(holder) as client:
        resp = client.get("/api/search", params={"q": "rust +tokio"})
    body = resp.json()
    assert holder.seen_query == "rust +tokio"
    assert len(body["results"]) == 2  # no scope applied, both hosts kept
    assert body["query"] == "rust +tokio"


def test_html_search_echoes_original_and_filters() -> None:
    holder = _Holder()
    with _client(holder) as client:
        resp = client.get("/search", params={"q": "neural nets +research"})
    assert resp.status_code == 200
    assert holder.seen_query == "neural nets"
    assert "arxiv.org" in resp.text
    assert "pinterest.com" not in resp.text
    # The search box round-trips the original text (token included).
    assert "neural nets +research" in resp.text
    assert holder.rules.active_lens is None
