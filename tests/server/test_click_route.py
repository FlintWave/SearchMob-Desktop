"""Owner-only `/click` redirector: it learns from owner clicks on the served page and is safe.

Drives `/search` to populate the render cache, then `/click` to exercise: owner click records the
skip-above update and redirects to the recorded URL; a network visitor is refused and gets no
tracking links; a forged or stale `rid`/`pos` fails safe without redirecting off-site.
"""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.rank import personalize as p
from searchmob_desktop.server.app import build_app

_NOW = int(time.time() * 1000)


class _Model:
    """A live model holder so the provider and saver share one instance across requests."""

    def __init__(self) -> None:
        self.model = p.PersonalizationModel(config=p.PersonalizationConfig(epsilon=0.0))

    def provide(self) -> p.PersonalizationModel:
        return self.model

    def save(self, model: p.PersonalizationModel) -> bool:
        self.model = model
        return True


async def _metasearch(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [
        SearchResult(title="One", url="https://a.example/1", snippet="s", engine="e"),
        SearchResult(title="Two", url="https://b.example/2", snippet="s", engine="e"),
        SearchResult(title="Three", url="https://liked.example/3", snippet="s", engine="e"),
    ]


def _app(holder: _Model | None) -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "0.0.0.0",
        personalization_provider=holder.provide if holder else None,
        personalization_saver=holder.save if holder else None,
        metasearch=_metasearch,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _loopback(app: object) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]


def _remote(app: object) -> TestClient:
    return TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]


def _rid_from_search(client: TestClient) -> str:
    html = client.get("/search", params={"q": "python list"}).text
    # The owner page routes result links through /click?rid=..&pos=..
    start = html.index("/click?rid=") + len("/click?rid=")
    return html[start : html.index("&", start)]


def test_owner_page_uses_click_links_and_records_then_redirects() -> None:
    holder = _Model()
    client = _loopback(_app(holder))
    rid = _rid_from_search(client)

    # Click the third result (the skipped-above ones are a.example and b.example).
    resp = client.get(f"/click?rid={rid}&pos=2", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://liked.example/3"
    # The model learned: clicked host got a click, the two above it got skips.
    assert holder.model.domains["liked.example"].alpha == holder.model.config.alpha_prior + 1
    assert holder.model.domains["a.example"].beta == holder.model.config.beta_prior + 1
    assert "c.example" not in holder.model.domains  # nothing below the click was touched


def test_network_visitor_gets_no_click_links_and_cannot_use_click() -> None:
    holder = _Model()
    app = _app(holder)
    # The remote page renders bare destination links, not /click.
    html = _remote(app).get("/search", params={"q": "python list"}).text
    assert "/click?rid=" not in html
    assert 'href="https://liked.example/3"' in html
    # And the /click endpoint itself refuses a non-owner (404), so it cannot be used to train.
    resp = _remote(app).get("/click?rid=anything&pos=0", follow_redirects=False)
    assert resp.status_code == 404


def test_owner_cannot_be_redirected_with_a_forged_or_stale_rid() -> None:
    holder = _Model()
    client = _loopback(_app(holder))
    # An unknown rid never redirects off-site; it falls back to home (303), and nothing is learned.
    resp = client.get("/click?rid=forged&pos=0", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert holder.model.is_empty()


def test_bad_position_fails_safe() -> None:
    holder = _Model()
    client = _loopback(_app(holder))
    rid = _rid_from_search(client)
    for pos in ("99", "-1", "notanint"):
        resp = client.get(f"/click?rid={rid}&pos={pos}", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
    assert holder.model.is_empty()


def test_disabled_personalization_renders_plain_links() -> None:
    # No provider/saver wired (feature off): the owner page has no /click links.
    html = _loopback(_app(None)).get("/search", params={"q": "python list"}).text
    assert "/click?rid=" not in html
    assert 'href="https://liked.example/3"' in html
