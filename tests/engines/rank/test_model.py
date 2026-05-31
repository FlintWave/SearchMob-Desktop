"""Round-trip, fail-soft parsing, and immutable-update behavior for the rank model."""

from __future__ import annotations

from searchmob_desktop.engines.rank.model import (
    GoggleRule,
    Lens,
    RankingRules,
    RankRule,
)


def _sample() -> RankingRules:
    return RankingRules(
        domain_rules={"spam.example": RankRule.BLOCK, "fav.example": RankRule.PIN},
        lenses=(
            Lens(
                name="news",
                include_domains=("nytimes.com",),
                exclude_domains=("tabloid.example",),
                include_keywords=("politics",),
                exclude_keywords=("gossip",),
            ),
        ),
        active_lens="news",
        goggles=(GoggleRule(site="dev.to", action=RankRule.RAISE),),
    )


def test_round_trip_through_json() -> None:
    original = _sample()
    restored = RankingRules.from_json(original.to_json())
    assert restored == original


def test_json_uses_camelcase_and_rule_names() -> None:
    text = _sample().to_json()
    assert '"domainRules"' in text
    assert '"activeLens"' in text
    assert '"includeKeywords"' in text
    assert '"BLOCK"' in text
    assert '"RAISE"' in text


def test_rank_rule_value_equals_name() -> None:
    assert RankRule.BLOCK.value == "BLOCK"
    assert RankRule.PIN.value == "PIN"


def test_from_json_garbage_returns_empty() -> None:
    assert RankingRules.from_json("not json at all {{{") == RankingRules()


def test_from_json_empty_object_returns_empty() -> None:
    assert RankingRules.from_json("{}") == RankingRules()


def test_from_json_array_returns_empty() -> None:
    assert RankingRules.from_json("[]") == RankingRules()


def test_from_json_unknown_rule_skipped() -> None:
    text = '{"domainRules": {"a.com": "BLOCK", "b.com": "BOGUS"}}'
    rules = RankingRules.from_json(text)
    assert rules.domain_rules == {"a.com": RankRule.BLOCK}


def test_from_json_unknown_goggle_action_skipped() -> None:
    text = (
        '{"goggles": [{"site": "a.com", "action": "BOGUS"}, {"site": "b.com", "action": "RAISE"}]}'
    )
    rules = RankingRules.from_json(text)
    assert rules.goggles == (GoggleRule(site="b.com", action=RankRule.RAISE),)


def test_from_json_tolerates_missing_keys() -> None:
    rules = RankingRules.from_json('{"activeLens": "x"}')
    assert rules.active_lens == "x"
    assert rules.domain_rules == {}
    assert rules.lenses == ()
    assert rules.goggles == ()


def test_from_json_accepts_lists_for_lens_fields() -> None:
    text = (
        '{"lenses": [{"name": "l", "includeDomains": ["a.com", "b.com"],'
        ' "excludeKeywords": ["spam"]}]}'
    )
    rules = RankingRules.from_json(text)
    assert rules.lenses[0].include_domains == ("a.com", "b.com")
    assert rules.lenses[0].exclude_keywords == ("spam",)
    assert rules.lenses[0].exclude_domains == ()


def test_active_returns_matching_lens() -> None:
    rules = _sample()
    assert rules.active is not None
    assert rules.active.name == "news"


def test_active_none_when_no_active_lens() -> None:
    rules = RankingRules(lenses=(Lens(name="x"),))
    assert rules.active is None


def test_active_none_when_name_not_found() -> None:
    rules = RankingRules(lenses=(Lens(name="x"),), active_lens="missing")
    assert rules.active is None


def test_empty_sentinel_equals_default() -> None:
    assert RankingRules.EMPTY == RankingRules()


def test_with_domain_rule_is_immutable() -> None:
    base = RankingRules()
    updated = base.with_domain_rule("a.com", RankRule.RAISE)
    assert base.domain_rules == {}
    assert updated.domain_rules == {"a.com": RankRule.RAISE}


def test_with_domain_rule_normal_removes_entry() -> None:
    base = RankingRules(domain_rules={"a.com": RankRule.RAISE})
    updated = base.with_domain_rule("a.com", RankRule.NORMAL)
    assert updated.domain_rules == {}
    assert base.domain_rules == {"a.com": RankRule.RAISE}


def test_without_domain_rule_is_immutable() -> None:
    base = RankingRules(domain_rules={"a.com": RankRule.RAISE, "b.com": RankRule.PIN})
    updated = base.without_domain_rule("a.com")
    assert updated.domain_rules == {"b.com": RankRule.PIN}
    assert base.domain_rules == {"a.com": RankRule.RAISE, "b.com": RankRule.PIN}


def test_without_domain_rule_missing_is_noop() -> None:
    base = RankingRules(domain_rules={"a.com": RankRule.RAISE})
    assert base.without_domain_rule("missing.com") is base


def test_with_lens_appends_a_new_lens() -> None:
    base = RankingRules(lenses=(Lens(name="news"),))
    updated = base.with_lens(Lens(name="docs", include_domains=("docs.rs",)))
    assert [lens.name for lens in updated.lenses] == ["news", "docs"]
    # Original is untouched (immutable update).
    assert [lens.name for lens in base.lenses] == ["news"]


def test_with_lens_replaces_same_name_in_place() -> None:
    base = RankingRules(lenses=(Lens(name="news"), Lens(name="docs")))
    updated = base.with_lens(Lens(name="news", include_keywords=("politics",)))
    # Still two lenses, "news" overwritten (not duplicated), order keeps the survivors first.
    assert [lens.name for lens in updated.lenses] == ["docs", "news"]
    news = next(lens for lens in updated.lenses if lens.name == "news")
    assert news.include_keywords == ("politics",)


def test_without_lens_removes_and_clears_active() -> None:
    base = RankingRules(lenses=(Lens(name="news"), Lens(name="docs")), active_lens="news")
    updated = base.without_lens("news")
    assert [lens.name for lens in updated.lenses] == ["docs"]
    # The active lens pointed at the removed one, so it is cleared.
    assert updated.active_lens is None


def test_without_lens_keeps_active_when_other_removed() -> None:
    base = RankingRules(lenses=(Lens(name="news"), Lens(name="docs")), active_lens="news")
    updated = base.without_lens("docs")
    assert updated.active_lens == "news"


def test_without_lens_missing_is_noop() -> None:
    base = RankingRules(lenses=(Lens(name="news"),))
    assert base.without_lens("missing") is base
