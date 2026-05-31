"""Served Settings page: Goggles import/clear and the search-history view/clear.

Builds the app with prefs + ranking-rules + history wiring. Loopback vs remote is simulated with
`TestClient(app, client=(host, port))`. The history store is a tiny stub exposing recent()/clear().
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.data.history import HistoryEntry
from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.engines.rank import GoggleRule, RankingRules, RankRule
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


class _History:
    def __init__(self, entries: list[HistoryEntry] | None = None) -> None:
        self.entries = entries if entries is not None else []
        self.cleared = False

    def recent(self) -> list[HistoryEntry]:
        return self.entries

    def clear(self) -> bool:
        self.entries = []
        self.cleared = True
        return True


async def _one_result(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="A", url="https://news.example/x", snippet="s", engine="e")]


def _app(
    *,
    rules: _Rules | None = None,
    history: _History | None = None,
    with_history: bool = True,
    host: str = "127.0.0.1",
) -> object:
    rules = rules if rules is not None else _Rules()
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: host,
        prefs_provider=_Prefs().load,
        prefs_saver=_Prefs().save,
        ranking_rules_provider=rules.load,
        ranking_rules_saver=rules.save,
        history_provider=(history or _History()).recent if with_history else None,
        history_clearer=(history or _History()).clear if with_history else None,
        metasearch=_one_result,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _loopback(app: object) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]


def _remote(app: object) -> TestClient:
    return TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]


def test_settings_shows_goggles_and_history() -> None:
    rules = _Rules(RankingRules(goggles=(GoggleRule(site="spam.example", action=RankRule.BLOCK),)))
    history = _History([HistoryEntry(query="rust borrow checker", timestamp_ms=1)])
    with _loopback(_app(rules=rules, history=history)) as client:
        html = client.get("/settings").text
    assert "Goggles" in html
    assert "spam.example" in html
    assert "Search history" in html
    assert "rust borrow checker" in html


def test_import_goggles_appends() -> None:
    rules = _Rules(RankingRules(goggles=(GoggleRule(site="keep.example", action=RankRule.RAISE),)))
    with _loopback(_app(rules=rules)) as client:
        resp = client.post(
            "/settings/goggles",
            data={"goggles": "$discard,site=ads.example"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings?saved=1"
    sites = {g.site for g in rules.rules.goggles}
    assert "keep.example" in sites  # existing kept
    assert "ads.example" in sites  # new appended


def test_import_empty_goggles_is_noop() -> None:
    rules = _Rules()
    with _loopback(_app(rules=rules)) as client:
        client.post("/settings/goggles", data={"goggles": "   \n  "})
    assert rules.rules.goggles == ()


def test_clear_goggles() -> None:
    rules = _Rules(RankingRules(goggles=(GoggleRule(site="x.example", action=RankRule.BLOCK),)))
    with _loopback(_app(rules=rules)) as client:
        resp = client.post("/settings/goggles/clear", follow_redirects=False)
        assert resp.status_code == 303
    assert rules.rules.goggles == ()


def test_clear_history_calls_clearer() -> None:
    history = _History([HistoryEntry(query="a", timestamp_ms=1)])
    with _loopback(_app(history=history)) as client:
        resp = client.post("/settings/history/clear", follow_redirects=False)
        assert resp.status_code == 303
    assert history.cleared is True


def test_remote_cannot_touch_goggles_or_history() -> None:
    rules = _Rules()
    with _remote(_app(rules=rules)) as client:
        assert (
            client.post(
                "/settings/goggles", data={"goggles": "$discard,site=x.example"}
            ).status_code
            == 403
        )
        assert client.post("/settings/goggles/clear").status_code == 403
        assert client.post("/settings/history/clear").status_code == 403
    assert rules.rules.goggles == ()


def test_history_card_omitted_without_provider() -> None:
    with _loopback(_app(with_history=False)) as client:
        html = client.get("/settings").text
    assert "Search history" not in html
