"""MainWindow interactions: result handling, the did-you-mean banner, ranking, tray, closeEvent.

Constructed with a tmp `JsonPreferencesStore` + an in-memory history store so nothing touches the
user's real config. Tray-dependent assertions are guarded because the offscreen Qt platform may or
may not expose a system tray; `save_ranking_rules` is monkeypatched to a no-op so ranking changes
never write to disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QCloseEvent

import searchmob_desktop.gui.main_window as main_window
from searchmob_desktop.data.history import InMemoryHistoryStore
from searchmob_desktop.engines import AggregateOutcome, SearchResult
from searchmob_desktop.engines.correct.corrector import Correction
from searchmob_desktop.engines.rank import RankRule
from searchmob_desktop.gui.main_window import MainWindow
from searchmob_desktop.prefs import JsonPreferencesStore


def _window(tmp_path: Path) -> MainWindow:
    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    return MainWindow(prefs_store=store, history_store=InMemoryHistoryStore())


class _StubCorrector:
    """A corrector that always offers a fixed correction."""

    def __init__(self, corrected: str) -> None:
        self._corrected = corrected

    def suggest(self, _query: str) -> Correction:
        return Correction(self._corrected, 0.9)


def test_results_ready_empty_shows_empty_state(qapp: object, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window._on_results_ready([])
    assert window._body.currentWidget() is window._empty_state
    assert "No results" in window._status_label.text()


def test_results_ready_with_items_shows_results_and_count(qapp: object, tmp_path: Path) -> None:
    window = _window(tmp_path)
    results = [
        SearchResult(title="One", url="https://a.example/x", snippet="", engine="ddg"),
        SearchResult(title="Two", url="https://b.example/y", snippet="", engine="wiki"),
    ]
    window._on_results_ready(results)
    assert window._body.currentWidget() is window._results
    assert window._results.result_count == 2
    assert "2 results" in window._status_label.text()


def test_summary_card_shown_for_summary_then_hidden(qapp: object, tmp_path: Path) -> None:
    from searchmob_desktop.engines.wiki_summary import SummaryBox

    window = _window(tmp_path)
    box = SummaryBox(
        title="Mount Everest",
        description="Earth's highest mountain",
        extract="Mount Everest is Earth's highest mountain.",
        url="https://en.wikipedia.org/wiki/Mount_Everest",
    )
    results = [SearchResult(title="One", url="https://a.example/x", snippet="", engine="ddg")]
    window._on_results_ready((results, box, AggregateOutcome(results, ())))
    assert not window._summary_card.isHidden()
    assert "Mount Everest" in window._summary_title.text()
    assert "en.wikipedia.org/wiki/Mount_Everest" in window._summary_title.text()
    assert window._summary_extract.text() == box.extract

    # A subsequent search with no summary hides the card again.
    window._on_results_ready((results, None, AggregateOutcome(results, ())))
    assert window._summary_card.isHidden()


def test_search_failed_shows_empty_state_and_status(qapp: object, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window._on_search_failed("boom")
    assert window._body.currentWidget() is window._empty_state
    assert "Search failed" in window._status_label.text()
    assert "boom" in window._status_label.text()


def test_didyoumean_banner_shows_and_resubmits(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(tmp_path)
    window._corrector = _StubCorrector("corrected query")
    window._last_query = "corrcted query"

    window._maybe_show_correction()
    # `isVisible()` is False while the (unshown) window has no visible ancestor chain; the banner's
    # own shown/hidden state is what the handler controls, so assert it is not hidden.
    assert not window._didyoumean.isHidden()
    assert "corrected query" in window._didyoumean.text()

    # Clicking the banner sets the query input to the correction and re-submits.
    submitted: list[bool] = []
    monkeypatch.setattr(window, "_on_submit", lambda: submitted.append(True))
    window._on_didyoumean_clicked("#correct")
    assert window._query_input.text() == "corrected query"
    assert submitted == [True]


def test_rule_block_hides_domain_and_normal_clears(
    qapp: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main_window, "save_ranking_rules", lambda _rules: True)
    window = _window(tmp_path)
    window._raw_results = [
        SearchResult(title="Good", url="https://good.example/p", snippet="", engine="ddg"),
        SearchResult(title="Spam", url="https://spam.example/p", snippet="", engine="ddg"),
    ]
    window._body.setCurrentWidget(window._results)

    window._on_rule_requested("spam.example", RankRule.BLOCK)
    assert window._results.result_count == 1
    assert "hidden by your rules" in window._status_label.text()

    window._on_rule_requested("spam.example", RankRule.NORMAL)
    assert window._results.result_count == 2
    assert "hidden by your rules" not in window._status_label.text()


def test_tray_quit_and_show(qapp: object, tmp_path: Path) -> None:
    window = _window(tmp_path)
    if window._tray is None:
        pytest.skip("no system tray under this Qt platform")

    window._show_from_tray()
    assert window.isVisible()

    window._quit_from_tray()
    assert window._really_quit is True


def test_close_event_hides_to_tray_then_really_quits(qapp: object, tmp_path: Path) -> None:
    window = _window(tmp_path)

    if window._tray is not None:
        window._really_quit = False
        window.show()
        event = QCloseEvent()
        window.closeEvent(event)
        assert not event.isAccepted()
        assert not window.isVisible()

        # A real quit proceeds: the event is accepted and the server stop is attempted.
        window._really_quit = True
        event2 = QCloseEvent()
        window.closeEvent(event2)
        assert event2.isAccepted()
    else:
        # No tray: closing should proceed straight to shutdown and accept the event.
        event = QCloseEvent()
        window.closeEvent(event)
        assert event.isAccepted()
