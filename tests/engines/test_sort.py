"""Result sorting modes: relevance, strict date, and the freshness+relevance blend."""

from __future__ import annotations

from datetime import UTC, datetime

from searchmob_desktop.engines.sort import SortMode, query_freshness_weight, sort_results
from searchmob_desktop.engines.types import SearchResult

_NOW = int(datetime(2026, 5, 29, tzinfo=UTC).timestamp() * 1000)
_DAY = 86_400_000


def _r(title: str, published: int | None = None) -> SearchResult:
    return SearchResult(
        title=title, url=f"https://e/{title}", snippet="", engine="x", published=published
    )


def test_from_value_defaults_to_fresh() -> None:
    assert SortMode.from_value(None) is SortMode.FRESH_RELEVANT
    assert SortMode.from_value("date") is SortMode.DATE
    assert SortMode.from_value("relevance") is SortMode.RELEVANCE
    assert SortMode.from_value("garbage") is SortMode.FRESH_RELEVANT


def test_relevance_is_identity() -> None:
    items = [_r("a"), _r("b", _NOW), _r("c")]
    assert sort_results(items, SortMode.RELEVANCE, "anything", _NOW) == items


def test_date_mode_newest_first_then_undated() -> None:
    old = _r("old", _NOW - 100 * _DAY)
    new = _r("new", _NOW - 2 * _DAY)
    undated = _r("undated")
    out = sort_results([old, undated, new], SortMode.DATE, "q", _NOW)
    assert [r.title for r in out] == ["new", "old", "undated"]


def test_fresh_blend_all_undated_is_identity() -> None:
    # No dates and no time-sensitive query -> identical to relevance order.
    items = [_r("a"), _r("b"), _r("c")]
    assert sort_results(items, SortMode.FRESH_RELEVANT, "how to tie a tie", _NOW) == items


def test_fresh_blend_promotes_a_recent_dated_result() -> None:
    # A fresh result a few ranks down should rise above older/undated peers above it.
    items = [
        _r("undated_top"),
        _r("old", _NOW - 300 * _DAY),
        _r("fresh", _NOW - 1 * _DAY),
    ]
    out = sort_results(items, SortMode.FRESH_RELEVANT, "the matrix 5 release date", _NOW)
    assert out[0].title == "fresh"


def test_query_freshness_weight_boosts_time_sensitive() -> None:
    base = query_freshness_weight("best laptops", _NOW)
    assert query_freshness_weight("avatar 3 release date", _NOW) > base
    assert query_freshness_weight("lakers score", _NOW) > base
    assert query_freshness_weight("news about 2026 budget", _NOW) > base  # current year
