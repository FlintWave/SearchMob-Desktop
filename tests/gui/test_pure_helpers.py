"""Pure-helper tests that do not need a `QApplication` or a display."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


from searchmob_desktop.engines import EngineFn
from searchmob_desktop.gui.browser_setup_dialog import _setup_urls, choose_setup_host
from searchmob_desktop.gui.engines_catalog import (
    ENGINE_CATALOG,
    is_engine_enabled,
)
from searchmob_desktop.gui.server_controller import build_engines_from_prefs
from searchmob_desktop.gui.theme import (
    DARK,
    LIGHT,
    SYSTEM,
    resolve_theme,
    theme_stylesheet,
)
from searchmob_desktop.prefs import UserPreferences


def test_resolve_theme_accepts_known_names() -> None:
    assert resolve_theme("light") == LIGHT
    assert resolve_theme("DARK") == DARK
    assert resolve_theme("system") == SYSTEM


def test_resolve_theme_falls_back_to_system() -> None:
    assert resolve_theme(None) == SYSTEM
    assert resolve_theme("") == SYSTEM
    assert resolve_theme("solarized") == SYSTEM


def test_theme_stylesheet_returns_empty_for_system() -> None:
    assert theme_stylesheet(SYSTEM) == ""
    assert theme_stylesheet(LIGHT) != ""
    assert theme_stylesheet(DARK) != ""


def test_engine_catalog_default_on_for_unset_engine() -> None:
    assert is_engine_enabled("duckduckgo", None) is True
    assert is_engine_enabled("duckduckgo", {}) is True


def test_engine_catalog_respects_explicit_disable() -> None:
    assert is_engine_enabled("duckduckgo", {"duckduckgo": False}) is False
    assert is_engine_enabled("mwmbl", {"mwmbl": True}) is True


def test_engine_catalog_api_engines_default_off() -> None:
    # Key-requiring engines start off (they cannot run without a key); free engines start on.
    assert is_engine_enabled("brave", None) is False
    assert is_engine_enabled("mojeek-api", {}) is False
    assert is_engine_enabled("kagi-api", None) is False
    assert is_engine_enabled("wikipedia", None) is True
    # An explicit enable still wins for an API engine.
    assert is_engine_enabled("brave", {"brave": True}) is True


def test_engine_catalog_lists_expected_engines() -> None:
    ids = {e.id for e in ENGINE_CATALOG}
    # The five free engines + the two BYO-key ones must be in the catalog so the settings UI
    # shows them all.
    expected = {"duckduckgo", "wikipedia", "mojeek", "marginalia", "mwmbl", "brave", "mojeek-api"}
    assert expected <= ids


def test_build_engines_from_prefs_default_returns_all_free_engines() -> None:
    engines: list[EngineFn] = build_engines_from_prefs(UserPreferences())
    # Five free engines, no env keys set in this test context guaranteed-or-not; we just check
    # the floor: at least five engine functions appended.
    assert len(engines) >= 5


def test_build_engines_from_prefs_honors_disabled_engine() -> None:
    prefs = UserPreferences(engine_enabled={"duckduckgo": False})
    engines = build_engines_from_prefs(prefs)
    # We cannot easily identify each engine by callable identity, so check the count is one
    # lower than the baseline.
    baseline = build_engines_from_prefs(UserPreferences())
    assert len(engines) == len(baseline) - 1


def test_setup_urls_uses_percent_s_placeholder() -> None:
    # The wizard templates use %s, the placeholder Firefox-family and Chromium "add a search
    # engine" dialogs expect. ({searchTerms} is only for the server's OpenSearch descriptor.)
    visit, search, suggest = _setup_urls("127.0.0.1", 8787)
    assert visit == "http://127.0.0.1:8787/"
    assert search == "http://127.0.0.1:8787/search?q=%s"
    assert suggest == "http://127.0.0.1:8787/suggest?q=%s"


def test_choose_setup_host_loopback_uses_localhost() -> None:
    # Loopback (the common case): localhost, which browsers resolve and the allowlist accepts.
    assert choose_setup_host(network_enabled=False) == "localhost"
    # Configured names are ignored in loopback mode.
    assert choose_setup_host(network_enabled=False, configured_hostnames=("my-pc.local",)) == (
        "localhost"
    )


def test_choose_setup_host_network_prefers_configured_then_local_then_ip() -> None:
    # A configured hostname wins.
    assert (
        choose_setup_host(
            network_enabled=True,
            configured_hostnames=("my-pc.ts.net",),
            local_names=("avonlea.local",),
        )
        == "my-pc.ts.net"
    )
    # Else the machine's own detected name.
    assert (
        choose_setup_host(network_enabled=True, local_names=("avonlea.local",)) == "avonlea.local"
    )
    # Else fall back to the loopback IP (no regression from the old behavior).
    assert choose_setup_host(network_enabled=True) == "127.0.0.1"
    # Blank/whitespace entries are skipped.
    assert choose_setup_host(network_enabled=True, configured_hostnames=("  ", "")) == "127.0.0.1"
