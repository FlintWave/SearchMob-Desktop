"""Bucketing, filtering, and host parsing for the ranking pass."""

from __future__ import annotations

from searchmob_desktop.engines.rank.model import GoggleRule, Lens, RankingRules, RankRule
from searchmob_desktop.engines.rank.ranker import apply_ranking, host_of_url
from searchmob_desktop.engines.types import SearchResult


def _result(url: str, title: str = "", snippet: str = "") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet, engine="test")


def _hosts(items: list[SearchResult]) -> list[str | None]:
    return [host_of_url(r.url) for r in items]


_HOST_OF = lambda r: host_of_url(r.url)  # noqa: E731
_TEXT_OF = lambda r: r.title + " " + r.snippet  # noqa: E731


def test_empty_rules_returns_input_unchanged() -> None:
    items = [_result("https://a.com"), _result("https://b.com")]
    out = apply_ranking(items, RankingRules(), _HOST_OF)
    assert out is items


def test_bucketing_preserves_relevance_order() -> None:
    items = [
        _result("https://lower.com"),
        _result("https://pin.com"),
        _result("https://normal1.com"),
        _result("https://raise.com"),
        _result("https://normal2.com"),
    ]
    rules = RankingRules(
        domain_rules={
            "pin.com": RankRule.PIN,
            "raise.com": RankRule.RAISE,
            "lower.com": RankRule.LOWER,
        }
    )
    out = apply_ranking(items, rules, _HOST_OF)
    assert _hosts(out) == ["pin.com", "raise.com", "normal1.com", "normal2.com", "lower.com"]


def test_block_dropped() -> None:
    items = [_result("https://keep.com"), _result("https://drop.com")]
    rules = RankingRules(domain_rules={"drop.com": RankRule.BLOCK})
    out = apply_ranking(items, rules, _HOST_OF)
    assert _hosts(out) == ["keep.com"]


def test_domain_rule_beats_goggle() -> None:
    items = [_result("https://x.com")]
    rules = RankingRules(
        domain_rules={"x.com": RankRule.PIN},
        goggles=(GoggleRule(site="x.com", action=RankRule.BLOCK),),
    )
    out = apply_ranking(items, rules, _HOST_OF)
    assert _hosts(out) == ["x.com"]


def test_goggle_action_priority_block_over_raise_over_lower() -> None:
    items = [_result("https://x.com")]
    rules = RankingRules(
        goggles=(
            GoggleRule(site="x.com", action=RankRule.LOWER),
            GoggleRule(site="x.com", action=RankRule.RAISE),
            GoggleRule(site="x.com", action=RankRule.BLOCK),
        )
    )
    assert apply_ranking(items, rules, _HOST_OF) == []


def test_goggle_raise_over_lower_when_no_block() -> None:
    items = [_result("https://x.com"), _result("https://y.com")]
    rules = RankingRules(
        goggles=(
            GoggleRule(site="x.com", action=RankRule.LOWER),
            GoggleRule(site="x.com", action=RankRule.RAISE),
        )
    )
    out = apply_ranking(items, rules, _HOST_OF)
    assert _hosts(out) == ["x.com", "y.com"]


def test_parent_domain_rule_covers_subdomain() -> None:
    items = [_result("https://blog.example.com")]
    rules = RankingRules(domain_rules={"example.com": RankRule.PIN})
    out = apply_ranking(items, rules, _HOST_OF)
    assert _hosts(out) == ["blog.example.com"]


def test_lens_include_domains_filters() -> None:
    items = [_result("https://keep.com"), _result("https://other.com")]
    rules = RankingRules(
        lenses=(Lens(name="l", include_domains=("keep.com",)),),
        active_lens="l",
    )
    out = apply_ranking(items, rules, _HOST_OF, _TEXT_OF)
    assert _hosts(out) == ["keep.com"]


def test_lens_exclude_domains_filters() -> None:
    items = [_result("https://keep.com"), _result("https://block.com")]
    rules = RankingRules(
        lenses=(Lens(name="l", exclude_domains=("block.com",)),),
        active_lens="l",
    )
    out = apply_ranking(items, rules, _HOST_OF, _TEXT_OF)
    assert _hosts(out) == ["keep.com"]


def test_lens_include_keywords_filters() -> None:
    items = [
        _result("https://a.com", title="Python tutorial"),
        _result("https://b.com", title="Java guide"),
    ]
    rules = RankingRules(
        lenses=(Lens(name="l", include_keywords=("python",)),),
        active_lens="l",
    )
    out = apply_ranking(items, rules, _HOST_OF, _TEXT_OF)
    assert _hosts(out) == ["a.com"]


def test_lens_exclude_keywords_filters() -> None:
    items = [
        _result("https://a.com", snippet="clean content"),
        _result("https://b.com", snippet="this is SPAM here"),
    ]
    rules = RankingRules(
        lenses=(Lens(name="l", exclude_keywords=("spam",)),),
        active_lens="l",
    )
    out = apply_ranking(items, rules, _HOST_OF, _TEXT_OF)
    assert _hosts(out) == ["a.com"]


def test_host_of_url_basic() -> None:
    assert host_of_url("https://www.Example.com/path?q=1") == "example.com"
    assert host_of_url("http://blog.example.com") == "blog.example.com"
    assert host_of_url("https://example.com:8080/x") == "example.com"


def test_host_of_url_junk_returns_none() -> None:
    assert host_of_url("not a url") is None
    assert host_of_url("") is None
    assert host_of_url("   ") is None
