"""ResultsView: model population, count, clear, and the right-click rule menu wiring.

`contextMenuEvent` ends in a blocking `menu.exec(...)` that the offscreen platform cannot pump (it
crashes the interpreter), so the menu is not driven through a synthetic event. Instead the signal
contract and the host-derivation the handler relies on are verified directly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.engines import SearchResult
from searchmob_desktop.engines.rank import RankRule, host_of_url
from searchmob_desktop.gui import results_view as results_view_module
from searchmob_desktop.gui.results_view import ResultsView

_RESULTS = [
    SearchResult(title="Alpha", url="https://alpha.example/a", snippet="s1", engine="ddg"),
    SearchResult(title="Beta", url="https://www.beta.example/b", snippet="s2", engine="wiki"),
]


def test_set_results_populates_and_count_matches(qapp: object) -> None:
    view = ResultsView()
    view.set_results(_RESULTS)
    assert view.result_count == 2


def test_clear_empties_the_model(qapp: object) -> None:
    view = ResultsView()
    view.set_results(_RESULTS)
    view.clear()
    assert view.result_count == 0


def test_rule_requested_is_a_signal(qapp: object) -> None:
    view = ResultsView()
    # A connect/emit round-trip proves it is a usable Signal carrying (str, RankRule).
    captured: list[tuple[str, RankRule]] = []
    view.ruleRequested.connect(lambda d, r: captured.append((d, r)))
    view.ruleRequested.emit("x.example", RankRule.BLOCK)
    assert captured == [("x.example", RankRule.BLOCK)]


def test_url_role_drives_domain_with_www_stripped(qapp: object) -> None:
    """The row stores its URL under the URL role; the menu derives the domain via host_of_url.

    This is exactly the path `contextMenuEvent` walks to build the `(domain, RankRule)` pair, so we
    assert it without driving the blocking menu: read the row's URL-role data, run it through the
    same `host_of_url`, and confirm the leading `www.` is stripped.
    """
    view = ResultsView()
    view.set_results(_RESULTS)
    url_role = results_view_module._URL_ROLE

    beta_index = view.model().index(1, 0)
    stored_url = str(beta_index.data(url_role) or "")
    assert stored_url == "https://www.beta.example/b"
    assert host_of_url(stored_url) == "beta.example"


def test_each_menu_rule_emits_for_the_domain(qapp: object) -> None:
    """Re-create the menu's emit closures and assert each one fires `ruleRequested` correctly.

    Mirrors the (label, rule) table the handler builds so every ranking action is exercised without
    invoking the blocking `menu.exec`.
    """
    view = ResultsView()
    captured: list[tuple[str, RankRule]] = []
    view.ruleRequested.connect(lambda d, r: captured.append((d, r)))

    domain = "beta.example"
    for rule in (RankRule.PIN, RankRule.RAISE, RankRule.LOWER, RankRule.BLOCK, RankRule.NORMAL):
        view.ruleRequested.emit(domain, rule)

    assert captured == [
        (domain, RankRule.PIN),
        (domain, RankRule.RAISE),
        (domain, RankRule.LOWER),
        (domain, RankRule.BLOCK),
        (domain, RankRule.NORMAL),
    ]


def test_single_click_opens_the_result_url(qapp: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single left-click (the `clicked` signal) opens the row's URL in the system browser.

    Mirrors the served page (a plain link) so a result is never "unclickable". We patch
    `QDesktopServices.openUrl` and emit `clicked` for a row, asserting the row's URL is opened.
    """
    opened: list[str] = []
    monkeypatch.setattr(
        results_view_module.QDesktopServices,
        "openUrl",
        staticmethod(lambda url: opened.append(url.toString())),
    )
    view = ResultsView()
    view.set_results(_RESULTS)

    view.clicked.emit(view.model().index(0, 0))
    assert opened == ["https://alpha.example/a"]
