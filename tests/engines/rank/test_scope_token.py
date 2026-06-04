"""The inline ``+name`` scope token parser: first-word match, fallback, and pass-through."""

from __future__ import annotations

from searchmob_desktop.engines.rank import Lens, RankingRules, parse_scope_token

_RULES = RankingRules(
    lenses=(
        Lens(name="Research mode", include_domains=("arxiv.org",)),
        Lens(name="Less clutter (no Pinterest/Quora)", exclude_domains=("pinterest.com",)),
        Lens(name="Developer docs", include_domains=("docs.python.org",)),
    )
)


def test_first_word_match_strips_token_and_returns_name() -> None:
    cleaned, name = parse_scope_token("mechanical keyboards +research", _RULES)
    assert cleaned == "mechanical keyboards"
    assert name == "Research mode"


def test_match_is_case_insensitive() -> None:
    cleaned, name = parse_scope_token("rust +DEVELOPER", _RULES)
    assert cleaned == "rust"
    assert name == "Developer docs"


def test_first_word_match_on_a_parenthesised_name() -> None:
    cleaned, name = parse_scope_token("cake recipe +less", _RULES)
    assert cleaned == "cake recipe"
    assert name == "Less clutter (no Pinterest/Quora)"


def test_normalized_full_name_fallback() -> None:
    # No scope's first word is "developerdocs", but the normalized whole name matches.
    cleaned, name = parse_scope_token("flask +developerdocs", _RULES)
    assert cleaned == "flask"
    assert name == "Developer docs"


def test_unmatched_token_stays_in_query() -> None:
    cleaned, name = parse_scope_token("rust +tokio async", _RULES)
    assert cleaned == "rust +tokio async"
    assert name is None


def test_first_matching_token_wins_and_only_it_is_stripped() -> None:
    cleaned, name = parse_scope_token("+research neural nets +developer", _RULES)
    assert cleaned == "neural nets +developer"
    assert name == "Research mode"


def test_token_mid_query_is_removed_in_place() -> None:
    cleaned, name = parse_scope_token("quantum +research computing", _RULES)
    assert cleaned == "quantum computing"
    assert name == "Research mode"


def test_query_without_plus_is_returned_unchanged() -> None:
    cleaned, name = parse_scope_token("plain query", _RULES)
    assert cleaned == "plain query"
    assert name is None


def test_bare_plus_is_not_a_token() -> None:
    cleaned, name = parse_scope_token("a + b", _RULES)
    assert cleaned == "a + b"
    assert name is None


def test_no_lenses_means_no_match() -> None:
    cleaned, name = parse_scope_token("foo +research", RankingRules())
    assert cleaned == "foo +research"
    assert name is None


def test_token_only_query_collapses_to_empty() -> None:
    cleaned, name = parse_scope_token("+research", _RULES)
    assert cleaned == ""
    assert name == "Research mode"
