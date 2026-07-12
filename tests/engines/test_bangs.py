"""!bang resolution: exact tags only, leading or trailing, terms never hijacked."""

from __future__ import annotations

from searchmob_desktop.engines.bangs import ALL_BANGS, resolve_bang


def test_resolves_leading_bang() -> None:
    redirect = resolve_bang("!w privacy")
    assert redirect is not None
    assert redirect.url == "https://en.wikipedia.org/wiki/Special:Search?search=privacy"
    assert redirect.bang.tag == "w"
    assert redirect.terms == "privacy"


def test_resolves_trailing_bang() -> None:
    redirect = resolve_bang("ktor websockets !gh")
    assert redirect is not None
    assert redirect.url == "https://github.com/search?q=ktor%20websockets"


def test_encodes_terms_safely() -> None:
    redirect = resolve_bang("!ddg a&b=c")
    assert redirect is not None
    assert "a%26b%3Dc" in redirect.url


def test_uses_percent_twenty_in_path_templates() -> None:
    # Merriam-Webster's template puts the terms in the URL path, where '+' is not a space.
    redirect = resolve_bang("!dict free software")
    assert redirect is not None
    assert redirect.url == "https://www.merriam-webster.com/dictionary/free%20software"


def test_bare_bang_goes_home() -> None:
    redirect = resolve_bang("!hn")
    assert redirect is not None
    assert redirect.url == "https://news.ycombinator.com"


def test_case_insensitive_and_aliases() -> None:
    assert resolve_bang("!W kotlin") is not None
    wiki = resolve_bang("!wikipedia kotlin")
    assert wiki is not None
    assert wiki.bang.tag == "w"


def test_unknown_tags_and_mid_query_bangs_fall_through() -> None:
    assert resolve_bang("!important css") is None
    assert resolve_bang("css !important rules") is None  # mid-query, not first or last
    assert resolve_bang("plain query") is None
    assert resolve_bang("!") is None
    assert resolve_bang("") is None


def test_every_bang_template_has_placeholder_and_https_home() -> None:
    for bang in ALL_BANGS:
        assert "{q}" in bang.search_url, bang.tag
        assert bang.search_url.startswith("https://"), bang.tag
        assert bang.home_url.startswith("https://"), bang.tag
