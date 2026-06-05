"""Served-page UI language: the picker, the `POST /language` write, and locale resolution.

Same harness as the other served-UI tests. Translations are authored offline, so these assert on the
structural behaviour (the `lang`/`dir` attributes, the picker state, the persisted pref, and the
resolution order) rather than on translated text.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import EngineContext, SearchResult
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.app import build_app


class _Prefs:
    def __init__(self, prefs: UserPreferences | None = None) -> None:
        self.prefs = prefs if prefs is not None else UserPreferences()

    def load(self) -> UserPreferences:
        return self.prefs

    def save(self, prefs: UserPreferences) -> bool:
        self.prefs = prefs
        return True


async def _one_result(_ctx: EngineContext, _engines: object) -> list[SearchResult]:
    return [SearchResult(title="A page", url="https://news.example/x", snippet="s", engine="e")]


def _app(prefs: _Prefs | None, *, host: str = "127.0.0.1") -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: host,
        prefs_provider=prefs.load if prefs else None,
        prefs_saver=prefs.save if prefs else None,
        metasearch=_one_result,  # type: ignore[arg-type]
        host_allowlist_enabled=False,
    )


def _loopback(app: object) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 9))  # type: ignore[arg-type]


def _remote(app: object) -> TestClient:
    return TestClient(app, client=("192.168.1.20", 9))  # type: ignore[arg-type]


def test_home_has_a_language_picker_with_every_locale() -> None:
    prefs = _Prefs(UserPreferences(language="es"))
    with _loopback(_app(prefs)) as client:
        resp = client.get("/", headers={"accept-language": "en"})
    # Picker present, all ten locales by endonym, current one selected, and the page in Spanish.
    assert 'name="lang"' in resp.text
    assert "Español" in resp.text and "العربية" in resp.text and "简体中文" in resp.text
    assert '<option value="es" selected>' in resp.text
    assert '<html lang="es">' in resp.text


def test_pinned_language_beats_accept_language() -> None:
    prefs = _Prefs(UserPreferences(language="fr"))
    with _loopback(_app(prefs)) as client:
        resp = client.get("/", headers={"accept-language": "ar,en;q=0.8"})
    assert '<html lang="fr">' in resp.text
    assert 'dir="rtl"' not in resp.text


def test_accept_language_used_when_no_pinned_language() -> None:
    prefs = _Prefs(UserPreferences(language=""))
    with _loopback(_app(prefs)) as client:
        resp = client.get("/", headers={"accept-language": "ar-EG,ar;q=0.9,en;q=0.5"})
    # Arabic is RTL, so the page mirrors via dir="rtl".
    assert '<html lang="ar" dir="rtl">' in resp.text


def test_post_language_persists_the_choice() -> None:
    prefs = _Prefs()
    with _loopback(_app(prefs)) as client:
        resp = client.post("/language", data={"lang": "pt"}, follow_redirects=False)
    assert resp.status_code == 303
    assert prefs.prefs.language == "pt"


def test_post_empty_language_clears_to_follow_os() -> None:
    prefs = _Prefs(UserPreferences(language="pt"))
    with _loopback(_app(prefs)) as client:
        client.post("/language", data={"lang": ""}, follow_redirects=False)
    assert prefs.prefs.language == ""


def test_post_unknown_language_is_ignored() -> None:
    prefs = _Prefs(UserPreferences(language="es"))
    with _loopback(_app(prefs)) as client:
        client.post("/language", data={"lang": "xx"}, follow_redirects=False)
    assert prefs.prefs.language == "es"  # unchanged


def test_remote_visitor_cannot_set_language() -> None:
    prefs = _Prefs(UserPreferences(language="es"))
    with _remote(_app(prefs)) as client:
        resp = client.post("/language", data={"lang": "fr"}, follow_redirects=False)
    assert resp.status_code in (403, 503)
    assert prefs.prefs.language == "es"  # unchanged
