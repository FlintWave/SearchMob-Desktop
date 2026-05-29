"""Served-UI personalization: the loopback-only rules-mutation routes and the editable page.

Drives the Starlette app via `TestClient`. `TestClient(app, client=(host, port))` sets the ASGI
`scope["client"]`, which is how we simulate a loopback owner vs a network visitor for the
owner-only gate. The host allowlist is left off (TestClient sends `Host: testserver`); the gate
under test is the loopback + same-origin check on the mutation routes, not the DNS-rebind allowlist.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.rank import Lens, RankingRules, RankRule
from searchmob_desktop.server.app import build_app


class _Holder:
    """In-memory stand-in for the vault-backed rules store (provider + saver)."""

    def __init__(self, rules: RankingRules | None = None) -> None:
        self.rules = rules if rules is not None else RankingRules()

    def load(self) -> RankingRules:
        return self.rules

    def save(self, rules: RankingRules) -> bool:
        self.rules = rules
        return True


async def _one_result(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="A page", url="https://news.example/x", snippet="s", engine="e")]


def _app(holder: _Holder | None, *, host: str = "127.0.0.1") -> object:
    return build_app(
        [lambda _c, _ctx: []],  # one engine so _run_metasearch does not short-circuit on empty
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: host,
        ranking_rules_provider=holder.load if holder else None,
        ranking_rules_saver=holder.save if holder else None,
        metasearch=_one_result,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _loopback(app: object) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]


def _remote(app: object) -> TestClient:
    return TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]


def test_loopback_post_sets_and_resets_a_domain_rule() -> None:
    holder = _Holder()
    with _loopback(_app(holder)) as client:
        resp = client.post(
            "/rules/domain",
            data={"domain": "news.example", "action": "BLOCK"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
    assert holder.rules.domain_rules == {"news.example": RankRule.BLOCK}

    with _loopback(_app(holder)) as client:
        client.post("/rules/domain", data={"domain": "news.example", "action": "NORMAL"})
    assert "news.example" not in holder.rules.domain_rules


def test_remote_client_cannot_mutate_rules() -> None:
    holder = _Holder()
    with _remote(_app(holder)) as client:
        resp = client.post("/rules/domain", data={"domain": "news.example", "action": "BLOCK"})
        assert resp.status_code == 403
    assert holder.rules.domain_rules == {}


def test_foreign_origin_is_rejected_as_csrf() -> None:
    holder = _Holder()
    with _loopback(_app(holder)) as client:
        resp = client.post(
            "/rules/domain",
            data={"domain": "news.example", "action": "BLOCK"},
            headers={"Origin": "https://evil.example"},
        )
        assert resp.status_code == 403
    # A same-origin Origin header is accepted.
    with _loopback(_app(holder)) as client:
        resp = client.post(
            "/rules/domain",
            data={"domain": "news.example", "action": "BLOCK"},
            headers={"Origin": "http://localhost:8787"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
    assert holder.rules.domain_rules == {"news.example": RankRule.BLOCK}


def test_post_scope_sets_active_lens() -> None:
    holder = _Holder(RankingRules(lenses=(Lens(name="Docs"),)))
    with _loopback(_app(holder)) as client:
        client.post("/scope", data={"lens": "Docs"})
    assert holder.rules.active_lens == "Docs"
    # Empty clears the active scope.
    with _loopback(_app(holder)) as client:
        client.post("/scope", data={"lens": ""})
    assert holder.rules.active_lens is None


def test_endpoints_are_read_only_without_a_saver() -> None:
    with _loopback(_app(None)) as client:
        resp = client.post("/rules/domain", data={"domain": "x.example", "action": "BLOCK"})
        assert resp.status_code == 503


def test_results_page_shows_controls_for_owner_only() -> None:
    holder = _Holder(RankingRules(lenses=(Lens(name="Docs"),)))
    with _loopback(_app(holder)) as client:
        owner_html = client.get("/search", params={"q": "hi"}).text
    with _remote(_app(holder)) as client:
        visitor_html = client.get("/search", params={"q": "hi"}).text

    # Owner sees the per-result controls and the scope selector...
    assert 'action="/rules/domain"' in owner_html
    assert 'action="/scope"' in owner_html
    assert "news.example" in owner_html  # the result's domain label on the control row
    # ...the network visitor gets a read-only page.
    assert 'action="/rules/domain"' not in visitor_html
    assert 'action="/scope"' not in visitor_html
