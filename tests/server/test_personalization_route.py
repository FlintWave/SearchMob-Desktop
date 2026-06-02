"""Served search: the learned click model reorders results only for the loopback owner.

A network visitor must get the un-personalized order (and never trains the model), so this drives
`/api/search` from both a loopback client and a remote client, with a personalization provider that
strongly prefers one domain, and asserts the reorder happens only for the owner.
"""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.rank import personalize as p
from searchmob_desktop.server.app import build_app

# The served route scores with the real wall clock, so train near "now" or time-decay erases it.
_NOW = int(time.time() * 1000)


def _results(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    # Three engine results in a fixed order; "liked.example" starts last.
    return [
        SearchResult(title="One", url="https://a.example/1", snippet="s", engine="e"),
        SearchResult(title="Two", url="https://b.example/2", snippet="s", engine="e"),
        SearchResult(title="Three", url="https://liked.example/3", snippet="s", engine="e"),
    ]


async def _metasearch(ctx: EngineContext, engines: object) -> list[SearchResult]:
    return _results(ctx, engines)


def _model_favoring_liked() -> p.PersonalizationModel:
    # epsilon=0 so the server's reorder is deterministic (no exploration bypass) under test.
    m = p.PersonalizationModel(config=p.PersonalizationConfig(epsilon=0.0))
    # Repeatedly "click" liked.example at the bottom, skipping the two above it.
    for _ in range(30):
        p.update_from_click(m, ["a.example", "b.example", "liked.example"], 2, [], _NOW)
    return m


def _app(*, provider) -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "0.0.0.0",
        personalization_provider=provider,
        metasearch=_metasearch,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _hosts(client: TestClient, **params: str) -> list[str]:
    body = client.get("/api/search", params={"q": "anything", **params}).json()
    return [r["url"] for r in body["results"]]


def test_owner_sees_personalized_order() -> None:
    app = _app(provider=_model_favoring_liked)
    client = TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]
    urls = _hosts(client)
    # The learned-preferred domain is lifted above at least one originally-higher result.
    assert urls[0] == "https://liked.example/3"


def test_network_visitor_gets_unpersonalized_order() -> None:
    # Remote client (network mode). Even with a strong model wired, results stay in engine order.
    app = _app(provider=_model_favoring_liked)
    remote = TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]
    urls = _hosts(remote)
    assert urls == [
        "https://a.example/1",
        "https://b.example/2",
        "https://liked.example/3",
    ]


def test_no_provider_leaves_order_untouched() -> None:
    app = _app(provider=lambda: None)
    client = TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]
    urls = _hosts(client)
    assert urls[-1] == "https://liked.example/3"
