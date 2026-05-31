"""Accessibility markup on the served pages: lang, accessible names, labels, aria-current."""

from __future__ import annotations

from searchmob_desktop.engines.rank import Lens, RankingRules
from searchmob_desktop.server.templates import (
    render_home_page,
    render_results_page,
)


def _is_safe(_url: str) -> bool:
    return True


def test_pages_declare_a_language() -> None:
    assert "<html lang='en'>" in render_home_page()
    assert "<html lang='en'>" in render_results_page("hi", [], _is_safe)


def test_search_input_has_an_accessible_name() -> None:
    assert 'aria-label="Search"' in render_home_page()
    assert 'aria-label="Search"' in render_results_page("hi", [], _is_safe)


def test_sort_and_scope_labels_are_associated_with_their_selects() -> None:
    from searchmob_desktop.engines import SearchResult

    results = [SearchResult(title="A", url="https://a.example/x", snippet="s", engine="e")]
    html = render_results_page(
        "hi",
        results,
        _is_safe,
        rules=RankingRules(lenses=(Lens(name="Docs"),)),
        editable=True,
    )
    assert '<label for="sm-sort">' in html and 'id="sm-sort"' in html
    assert '<label for="sm-scope">' in html and 'id="sm-scope"' in html


def test_active_vertical_tab_is_marked_for_assistive_tech() -> None:
    from searchmob_desktop.engines import SearchResult

    results = [SearchResult(title="A", url="https://a.example/x", snippet="s", engine="e")]
    html = render_results_page("hi", results, _is_safe, vertical="news")
    assert 'aria-label="Search categories"' in html  # the nav landmark
    assert 'aria-current="page"' in html  # the active tab, not color-only
