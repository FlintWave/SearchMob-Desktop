"""Served Settings page: domain-rule listing and the scope (lens) create/update/delete routes.

Builds the app with both a prefs store (for the owner gate / page render) and a ranking-rules store
(provider + saver). Loopback vs remote is simulated with `TestClient(app, client=(host, port))`.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.rank import Lens, RankingRules, RankRule
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.app import build_app


class _Prefs:
    def __init__(self) -> None:
        self.prefs = UserPreferences()

    def load(self) -> UserPreferences:
        return self.prefs

    def save(self, prefs: UserPreferences) -> bool:
        self.prefs = prefs
        return True


class _Rules:
    def __init__(self, rules: RankingRules | None = None) -> None:
        self.rules = rules if rules is not None else RankingRules()

    def load(self) -> RankingRules:
        return self.rules

    def save(self, rules: RankingRules) -> bool:
        self.rules = rules
        return True


async def _one_result(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="A", url="https://news.example/x", snippet="s", engine="e")]


def _app(prefs: _Prefs, rules: _Rules | None, *, host: str = "127.0.0.1") -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: host,
        prefs_provider=prefs.load,
        prefs_saver=prefs.save,
        ranking_rules_provider=rules.load if rules else None,
        ranking_rules_saver=rules.save if rules else None,
        metasearch=_one_result,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _loopback(app: object) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]


def _remote(app: object) -> TestClient:
    return TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]


def test_settings_lists_existing_domain_rules_and_lenses() -> None:
    rules = _Rules(
        RankingRules(
            domain_rules={"spam.example": RankRule.BLOCK},
            lenses=(Lens(name="Docs", include_domains=("docs.rs",)),),
        )
    )
    with _loopback(_app(_Prefs(), rules)) as client:
        html = client.get("/settings").text
    assert "Domain rules" in html
    assert "spam.example" in html
    assert "Scopes" in html
    assert 'value="Docs"' in html
    assert "docs.rs" in html  # the lens's include-domains field is prefilled


def test_create_lens_via_post() -> None:
    rules = _Rules()
    with _loopback(_app(_Prefs(), rules)) as client:
        resp = client.post(
            "/settings/lens",
            data={
                "name": "Research",
                "include_domains": "Arxiv.org, ncbi.nlm.nih.gov\n.edu",
                "exclude_keywords": "press release",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings?saved=1"
    saved = rules.rules.lenses
    assert len(saved) == 1
    lens = saved[0]
    assert lens.name == "Research"
    # CSV/newline split, lowercased, de-duplicated, order preserved.
    assert lens.include_domains == ("arxiv.org", "ncbi.nlm.nih.gov", ".edu")
    assert lens.exclude_keywords == ("press release",)


def test_update_lens_replaces_same_name() -> None:
    rules = _Rules(RankingRules(lenses=(Lens(name="Docs", include_domains=("old.example",)),)))
    with _loopback(_app(_Prefs(), rules)) as client:
        client.post("/settings/lens", data={"name": "Docs", "include_domains": "new.example"})
    assert len(rules.rules.lenses) == 1
    assert rules.rules.lenses[0].include_domains == ("new.example",)


def test_blank_lens_name_is_ignored() -> None:
    rules = _Rules()
    with _loopback(_app(_Prefs(), rules)) as client:
        client.post("/settings/lens", data={"name": "   ", "include_domains": "x.example"})
    assert rules.rules.lenses == ()


def test_delete_lens_via_post() -> None:
    rules = _Rules(RankingRules(lenses=(Lens(name="Docs"), Lens(name="News")), active_lens="Docs"))
    with _loopback(_app(_Prefs(), rules)) as client:
        resp = client.post("/settings/lens/delete", data={"name": "Docs"}, follow_redirects=False)
        assert resp.status_code == 303
    assert [lens.name for lens in rules.rules.lenses] == ["News"]
    assert rules.rules.active_lens is None  # active pointed at the removed lens


def test_remote_cannot_manage_lenses() -> None:
    rules = _Rules()
    with _remote(_app(_Prefs(), rules)) as client:
        assert client.post("/settings/lens", data={"name": "X"}).status_code == 403
        assert client.post("/settings/lens/delete", data={"name": "X"}).status_code == 403
    assert rules.rules.lenses == ()


def test_lens_routes_503_without_a_rules_saver() -> None:
    with _loopback(_app(_Prefs(), None)) as client:
        assert client.post("/settings/lens", data={"name": "X"}).status_code == 503
        assert client.post("/settings/lens/delete", data={"name": "X"}).status_code == 503
