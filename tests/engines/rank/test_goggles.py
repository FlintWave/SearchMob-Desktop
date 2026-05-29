"""Parsing and host matching for Brave-style goggles."""

from __future__ import annotations

from searchmob_desktop.engines.rank.goggles import matches, parse
from searchmob_desktop.engines.rank.model import GoggleRule, RankRule


def test_boost_site() -> None:
    assert parse("$boost,site=dev.to") == [GoggleRule(site="dev.to", action=RankRule.RAISE)]


def test_downrank_site() -> None:
    assert parse("$downrank,site=a.com") == [GoggleRule(site="a.com", action=RankRule.LOWER)]


def test_discard_site() -> None:
    assert parse("$discard,site=b.com") == [GoggleRule(site="b.com", action=RankRule.BLOCK)]


def test_reversed_part_order() -> None:
    assert parse("site=x.com,$boost") == [GoggleRule(site="x.com", action=RankRule.RAISE)]


def test_bare_pattern_with_action() -> None:
    assert parse("example.com,$downrank") == [GoggleRule(site="example.com", action=RankRule.LOWER)]


def test_comment_metadata_and_blank_lines_skipped() -> None:
    text = "\n".join(
        [
            "! this is a comment",
            "name: My Goggle",
            "Description: ignore me",
            "PUBLIC: true",
            "",
            "   ",
            "$boost,site=keep.com",
        ]
    )
    assert parse(text) == [GoggleRule(site="keep.com", action=RankRule.RAISE)]


def test_malformed_line_skipped() -> None:
    text = "\n".join(
        [
            "site=onlysite.com",  # no action -> skipped
            "$boost",  # no site -> skipped
            "$boost,site=ok.com",
        ]
    )
    assert parse(text) == [GoggleRule(site="ok.com", action=RankRule.RAISE)]


def test_matches_exact() -> None:
    assert matches("example.com", "example.com")


def test_matches_parent_domain() -> None:
    assert matches("example.com", "blog.example.com")


def test_no_false_partial_match() -> None:
    assert not matches("example.com", "notexample.com")
    assert not matches("example.com", "example.org")


def test_matches_www_insensitive() -> None:
    assert matches("www.example.com", "example.com")
    assert matches("example.com", "www.example.com")


def test_wildcard_subdomain() -> None:
    assert matches("*.example.com", "spam.example.com")
    assert not matches("*.example.com", "example.com")


def test_wildcard_prefix() -> None:
    assert matches("spam*", "spammers")
    assert not matches("spam*", "ham")


def test_matches_case_insensitive() -> None:
    assert matches("Example.COM", "EXAMPLE.com")
