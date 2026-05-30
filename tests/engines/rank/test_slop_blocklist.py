"""Tests for the bundled AI-slop blocklist loader and host matcher, and the ranker slop branch."""

from __future__ import annotations

from searchmob_desktop.engines.rank.model import RankingRules, RankRule
from searchmob_desktop.engines.rank.ranker import apply_ranking
from searchmob_desktop.engines.rank.slop_blocklist import (
    load_slop_domains,
    matches_blocklist,
)


def test_load_slop_domains_non_empty_and_cached() -> None:
    domains = load_slop_domains()
    assert domains
    # Bundled asset is a few hundred to a few thousand entries; lower-bound guards an empty/corrupt
    # asset slipping through.
    assert len(domains) > 100
    # Cached: a second call returns the identical frozenset object.
    assert load_slop_domains() is domains


def test_matches_blocklist_host_parent_and_miss() -> None:
    domains = frozenset({"slopfarm.example", "junk.test"})
    assert matches_blocklist("slopfarm.example", domains)
    # Subdomain matches via the parent suffix.
    assert matches_blocklist("www.slopfarm.example", domains)
    assert matches_blocklist("a.b.junk.test", domains)
    # Non-listed host does not match.
    assert matches_blocklist("en.wikipedia.org", domains) is False
    # A bare TLD shared with a listed domain must not match.
    assert matches_blocklist("other.example", domains) is False


def test_matches_blocklist_empty_domains_never_matches() -> None:
    assert matches_blocklist("anything.test", frozenset()) is False


def _hosts(items: list[str]) -> list[str]:
    return items


def test_ranker_slop_downrank_sinks_listed_domain() -> None:
    domains = frozenset({"slopfarm.example"})
    items = ["clean.test", "slopfarm.example", "other.test"]
    out = apply_ranking(
        items,
        RankingRules(),
        host_of=lambda h: h,
        slop_domains=domains,
        slop_mode="downrank",
    )
    # Listed domain is kept but pushed to the bottom (lowered bucket).
    assert out == ["clean.test", "other.test", "slopfarm.example"]


def test_ranker_slop_hide_drops_listed_domain() -> None:
    domains = frozenset({"slopfarm.example"})
    items = ["clean.test", "slopfarm.example", "other.test"]
    out = apply_ranking(
        items,
        RankingRules(),
        host_of=lambda h: h,
        slop_domains=domains,
        slop_mode="hide",
    )
    assert out == ["clean.test", "other.test"]


def test_ranker_slop_off_leaves_order_untouched() -> None:
    domains = frozenset({"slopfarm.example"})
    items = ["clean.test", "slopfarm.example", "other.test"]
    out = apply_ranking(
        items,
        RankingRules(),
        host_of=lambda h: h,
        slop_domains=domains,
        slop_mode="off",
    )
    assert out == items


def test_user_rule_overrides_slop_blocklist() -> None:
    domains = frozenset({"slopfarm.example"})
    # The user explicitly RAISES a domain the blocklist would have downranked: user rule wins.
    rules = RankingRules(domain_rules={"slopfarm.example": RankRule.RAISE})
    items = ["clean.test", "slopfarm.example", "other.test"]
    out = apply_ranking(
        items,
        rules,
        host_of=lambda h: h,
        slop_domains=domains,
        slop_mode="hide",
    )
    # Raised to the top, not hidden.
    assert out[0] == "slopfarm.example"
    assert "slopfarm.example" in out
