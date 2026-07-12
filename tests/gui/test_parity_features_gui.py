"""GUI-side parity features: instant answer card, bang redirects, stale-search guarding.

Constructed with a tmp `JsonPreferencesStore` + an in-memory history store so nothing touches the
user's real config; the browser open is monkeypatched so a bang never leaves the test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import searchmob_desktop.gui.main_window as main_window
from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.engines import AggregateOutcome, SearchResult
from searchmob_desktop.gui.main_window import MainWindow
from searchmob_desktop.prefs import JsonPreferencesStore


def _window(tmp_path: Path) -> MainWindow:
    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    return MainWindow(prefs_store=store, history_store=InMemoryHistoryStore())


@pytest.fixture(autouse=True)
def _no_real_search_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep `_on_submit` hermetic: everything up to the worker launch runs, no thread starts."""
    monkeypatch.setattr(main_window.AsyncWorker, "start", lambda self, pool: None)


def test_bang_query_opens_the_browser_and_never_searches(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        main_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    window._query_input.setText("!gh ktor")
    generation_before = window._search_generation
    window._on_submit()
    assert opened == ["https://github.com/search?q=ktor"]
    # No search was started: the generation did not advance and the button stayed enabled.
    assert window._search_generation == generation_before
    assert window._search_btn.isEnabled()


def test_unknown_bang_is_a_normal_search(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        main_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    window._query_input.setText("!important css")
    window._on_submit()
    assert opened == []
    assert window._search_generation == 1


def test_instant_answer_card_shows_for_math_and_hides_for_plain_queries(
    qapp: object, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window._query_input.setText("15% of 80")
    window._on_submit()
    assert not window._instant_card.isHidden()
    assert window._instant_value.text() == "12"

    window._query_input.setText("kotlin coroutines")
    window._on_submit()
    assert window._instant_card.isHidden()


def test_stale_results_and_failures_are_ignored(qapp: object, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window._query_input.setText("first query")
    window._on_submit()
    stale_generation = window._search_generation
    window._query_input.setText("second query")
    window._on_submit()

    fresh = [SearchResult(title="Fresh", url="https://a.example/x", snippet="", engine="ddg")]
    window._on_results_ready((fresh, None, AggregateOutcome(fresh, ())), window._search_generation)
    assert window._results.result_count == 1

    # A stale payload must not replace the fresh results...
    stale = [SearchResult(title="Stale", url="https://b.example/y", snippet="", engine="ddg")]
    window._on_results_ready((stale, None, AggregateOutcome(stale, ())), stale_generation)
    assert window._results.result_count == 1
    # ...and a stale failure must not flash an error over them.
    window._on_search_failed("boom", stale_generation)
    assert "Search failed" not in window._status_label.text()
    assert window._body.currentWidget() is window._results
