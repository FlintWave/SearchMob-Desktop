"""Tests for the search-verticals query scoping and defaults."""

from __future__ import annotations

from searchmob_desktop.engines.sort import SortMode
from searchmob_desktop.engines.verticals import (
    Vertical,
    default_sort,
    transform_query,
)


def test_from_value_defaults_to_web() -> None:
    assert Vertical.from_value(None) is Vertical.WEB
    assert Vertical.from_value("") is Vertical.WEB
    assert Vertical.from_value("nonsense") is Vertical.WEB
    assert Vertical.from_value("NEWS") is Vertical.NEWS
    assert Vertical.from_value(" forums ") is Vertical.FORUMS


def test_web_leaves_query_unchanged() -> None:
    assert transform_query("python tutorial", Vertical.WEB) == "python tutorial"


def test_blank_query_unchanged_even_for_scoped_vertical() -> None:
    assert transform_query("   ", Vertical.FORUMS) == "   "


def test_forums_appends_site_or_group_with_terms_first() -> None:
    out = transform_query("rust async", Vertical.FORUMS)
    assert out.startswith("rust async (")
    assert out.endswith(")")
    assert "site:reddit.com" in out
    assert "site:news.ycombinator.com" in out
    assert " OR " in out


def test_academic_includes_edu_tld_filter() -> None:
    out = transform_query("graph neural networks", Vertical.ACADEMIC)
    assert "site:arxiv.org" in out
    assert "site:.edu" in out


def test_news_scopes_to_outlets() -> None:
    out = transform_query("election results", Vertical.NEWS)
    assert "site:reuters.com" in out
    assert "site:apnews.com" in out


def test_default_sort_per_vertical() -> None:
    assert default_sort(Vertical.WEB) is SortMode.FRESH_RELEVANT
    assert default_sort(Vertical.NEWS) is SortMode.FRESH_RELEVANT
    assert default_sort(Vertical.FORUMS) is SortMode.RELEVANCE
    assert default_sort(Vertical.ACADEMIC) is SortMode.RELEVANCE
