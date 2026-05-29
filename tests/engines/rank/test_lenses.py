"""The built-in sample lenses are well-formed and actually filter results."""

from __future__ import annotations

from searchmob_desktop.engines import SearchResult
from searchmob_desktop.engines.rank import (
    DEFAULT_SAMPLE_LENSES,
    RankingRules,
    apply_ranking,
    host_of_url,
)


def test_sample_lenses_present_and_uniquely_named() -> None:
    assert len(DEFAULT_SAMPLE_LENSES) >= 3
    names = [lens.name for lens in DEFAULT_SAMPLE_LENSES]
    assert len(names) == len(set(names))  # no duplicate names
    for lens in DEFAULT_SAMPLE_LENSES:
        # Every lens must do something (include or exclude).
        assert (
            lens.include_domains
            or lens.exclude_domains
            or lens.include_keywords
            or lens.exclude_keywords
        )


def _rank(results: list[SearchResult], rules: RankingRules) -> list[str]:
    ranked = apply_ranking(
        results,
        rules,
        host_of=lambda r: host_of_url(r.url),
        text_of=lambda r: f"{r.title} {r.snippet}",
    )
    return [r.url for r in ranked]


def test_academic_lens_keeps_edu_and_arxiv_drops_others() -> None:
    lens = next(lens for lens in DEFAULT_SAMPLE_LENSES if lens.name == "Academic & research")
    rules = RankingRules(lenses=(lens,), active_lens=lens.name)
    results = [
        SearchResult("MIT", "https://web.mit.edu/page", "", "x"),  # .edu parent match
        SearchResult("arXiv", "https://arxiv.org/abs/1", "", "x"),
        SearchResult("Random blog", "https://example.com/post", "", "x"),
    ]
    kept = _rank(results, rules)
    assert "https://web.mit.edu/page" in kept
    assert "https://arxiv.org/abs/1" in kept
    assert "https://example.com/post" not in kept


def test_less_clutter_lens_excludes_pinterest_quora() -> None:
    lens = next(lens for lens in DEFAULT_SAMPLE_LENSES if "clutter" in lens.name.lower())
    rules = RankingRules(lenses=(lens,), active_lens=lens.name)
    results = [
        SearchResult("Good", "https://good.example/p", "", "x"),
        SearchResult("Pin", "https://www.pinterest.com/p", "", "x"),
        SearchResult("Q", "https://quora.com/q", "", "x"),
    ]
    kept = _rank(results, rules)
    assert kept == ["https://good.example/p"]


def test_sample_lenses_round_trip_through_json() -> None:
    rules = RankingRules(lenses=DEFAULT_SAMPLE_LENSES)
    restored = RankingRules.from_json(rules.to_json())
    assert [lens.name for lens in restored.lenses] == [lens.name for lens in DEFAULT_SAMPLE_LENSES]
