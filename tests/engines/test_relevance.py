"""Unit tests for the lexical + language relevance signal blended into the aggregator."""

from __future__ import annotations

from searchmob_desktop.engines.relevance import (
    NAVIGATIONAL_BOOST,
    RELEVANCE_BASE,
    blended_score,
    content_terms,
    language_affinity,
    lexical_score,
    navigational_factor,
    registrable_label,
    squished_query,
)

# --- content_terms ----------------------------------------------------------------------------


def test_content_terms_strips_stopwords_keeps_subject() -> None:
    assert content_terms("best mechanical keyboard 2026") == ["mechanical", "keyboard", "2026"]


def test_content_terms_distinct_and_lowercased() -> None:
    assert content_terms("Tie a TIE knot tie") == ["tie", "knot"]


def test_content_terms_falls_back_when_all_stopwords() -> None:
    # "how to" is all stopwords; rather than score everything zero, keep the tokens.
    assert content_terms("how to") == ["how", "to"]


# --- lexical_score ----------------------------------------------------------------------------


def test_full_match_scores_high() -> None:
    terms = content_terms("mechanical keyboard")
    assert lexical_score("Best Mechanical Keyboard Guide", "review", terms) >= 0.9


def test_stemming_matches_plural() -> None:
    # "keyboard" should match a title that says "keyboards" (light stemming).
    terms = ["keyboard"]
    assert lexical_score("The Best Keyboards", "", terms) >= 0.9


def test_missing_subject_is_penalized() -> None:
    terms = content_terms("ai news today")  # subject/head term is "ai"
    has_subject = lexical_score("AI News Today", "latest ai coverage", terms)
    no_subject = lexical_score("Viral News Today", "trending news today", terms)
    assert no_subject < has_subject
    # The head penalty halves a result that never mentions the subject anywhere.
    assert no_subject <= 0.5 * has_subject + 0.01


def test_no_terms_scores_zero() -> None:
    assert lexical_score("anything", "anything", []) == 0.0


def test_non_ascii_terms_not_mangled_by_english_stemmer() -> None:
    # A Cyrillic term must still match itself (the English stemmer is gated to ASCII).
    terms = ["новости"]
    assert lexical_score("Новости сегодня", "", terms) >= 0.9


# --- language_affinity (script-relative, multilingual) ----------------------------------------


def test_same_script_query_and_result_is_kept() -> None:
    assert language_affinity("ai news", "AI News Today", "latest") == 1.0
    assert language_affinity("новости ии", "Новости ИИ", "статья") == 1.0


def test_cross_script_result_is_demoted_either_direction() -> None:
    assert language_affinity("ai news", "Новости искусственного интеллекта", "сегодня") == 0.4
    assert language_affinity("新闻 人工智能", "AI News Today", "english article") == 0.4


def test_letterless_query_is_never_penalized() -> None:
    assert language_affinity("2026 / 1080", "Любой результат", "текст") == 1.0


# --- blended_score (demotion-only) ------------------------------------------------------------


def test_blend_is_demotion_only_capped_at_one() -> None:
    # A strong and a perfect match both keep full RRF weight (keyword stuffing is not promoted).
    assert blended_score(1.0, 1.0) == 1.0
    assert blended_score(1.0, 0.6) == 1.0


def test_blend_sinks_weak_match_toward_base() -> None:
    assert blended_score(1.0, 0.0) == RELEVANCE_BASE
    assert blended_score(1.0, 0.0) < blended_score(1.0, 0.3) < 1.0


def test_affinity_multiplies_on_top() -> None:
    # A perfect lexical match in the wrong script is still demoted by the affinity factor.
    assert blended_score(1.0, 1.0, affinity=0.4) == 0.4


# --- separator bridging (threejs <-> three.js) ------------------------------------------------


def test_separator_split_brand_name_matches_squished_query() -> None:
    # The query "threejs" must match the official "three.js" title, which tokenizes to three + js.
    # Without bridging the head term is absent and the result is demoted; with it, it scores high.
    terms = content_terms("threejs")
    bridged = lexical_score("Three.js - JavaScript 3D Library", "A 3D library", terms)
    assert bridged >= 0.8


def test_bridging_does_not_match_unrelated_title() -> None:
    terms = content_terms("threejs")
    assert lexical_score("A cooking blog about pies", "recipes and more", terms) == 0.0


# --- navigational promotion -------------------------------------------------------------------


def test_squished_query_joins_terms_without_separators() -> None:
    assert squished_query(content_terms("three js")) == "threejs"
    assert squished_query(content_terms("node js")) == "nodejs"


def test_registrable_label_strips_suffix_and_subdomains() -> None:
    assert registrable_label("threejs.org") == "threejs"
    assert registrable_label("docs.python.org") == "python"
    assert registrable_label("www.nodejs.org") == "nodejs"
    assert registrable_label("example.co.uk") == "example"


def test_navigational_factor_promotes_exact_domain_match() -> None:
    assert navigational_factor(content_terms("threejs"), "threejs.org") == NAVIGATIONAL_BOOST
    # Squished multi-word query also names the site.
    assert navigational_factor(content_terms("three js"), "threejs.org") == NAVIGATIONAL_BOOST


def test_navigational_factor_neutral_for_non_matches() -> None:
    # A forum that merely contains the word is not the site itself.
    assert navigational_factor(content_terms("threejs"), "gamedev.net") == 1.0
    # A long descriptive query is not navigational.
    long_query = content_terms("how to rotate a cube in threejs")
    assert navigational_factor(long_query, "threejs.org") == 1.0
    # Too-short squished query never fires.
    assert navigational_factor(content_terms("go"), "go.dev") == 1.0
