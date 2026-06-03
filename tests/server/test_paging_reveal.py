"""Served-page infinite scroll: the whole ranked pool is rendered, but results past the first
window start collapsed and a reveal script + sentinel are emitted to unhide them on scroll. A small
result set renders no reveal machinery at all, and with JS off every result is still in the markup.
"""

from __future__ import annotations

from searchmob_desktop.engines import SearchResult
from searchmob_desktop.server.templates import (
    _REVEAL_SIZE,
    render_results_page,
)


def _is_safe(_url: str) -> bool:
    return True


def _many(n: int) -> list[SearchResult]:
    return [
        SearchResult(title=f"Result {i}", url=f"https://e.example/{i}", snippet="s", engine="ddg")
        for i in range(n)
    ]


def test_large_pool_collapses_results_past_the_window() -> None:
    results = _many(_REVEAL_SIZE + 8)
    html = render_results_page("hi", results, _is_safe)
    visible = html.count('<div class="result">')
    collapsed = html.count('<div class="result is-collapsed">')
    # Every pool result is in the DOM (nothing dropped), so JS-off users still see them all.
    assert visible + collapsed == len(results)
    # Exactly the first window is visible; the rest start collapsed.
    assert visible == _REVEAL_SIZE
    assert collapsed == len(results) - _REVEAL_SIZE
    # The sentinel and reveal script are present so scrolling unhides the rest.
    assert '<div class="reveal-sentinel"' in html
    assert "IntersectionObserver" in html


def test_small_pool_has_no_reveal_machinery() -> None:
    html = render_results_page("hi", _many(_REVEAL_SIZE), _is_safe)
    assert '<div class="result is-collapsed">' not in html
    assert '<div class="reveal-sentinel"' not in html
    assert "IntersectionObserver" not in html


def test_empty_results_have_no_reveal_machinery() -> None:
    html = render_results_page("hi", [], _is_safe)
    assert '<div class="reveal-sentinel"' not in html
