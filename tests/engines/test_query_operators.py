"""Google-style operator parsing and local enforcement, ported from `QueryOperatorsTest.kt`.

Covers the parse split (clean_text vs engine_query vs structural filters), tokenizer robustness
against garbage input, and `matches` enforcing every locally-checked operator over a merged
result. Everything here is pure; no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

from searchmob_desktop.engines.query_operators import parse_query_operators


def _epoch_ms(year: int, month: int = 1, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)


# --- plain terms / phrases ---------------------------------------------------------------------


def test_plain_terms_pass_through_unchanged() -> None:
    p = parse_query_operators("wireless mouse")
    assert p.clean_text == "wireless mouse"
    assert p.engine_query == "wireless mouse"
    assert not p.has_filters
    assert not p.has_operators


def test_leading_plus_is_not_special() -> None:
    # The server's scope-token pass runs before this parser, so `+word` and `c++` are plain text.
    p = parse_query_operators("+word c++")
    assert p.clean_text == "+word c++"
    assert p.engine_query == "+word c++"


def test_quoted_phrase_feeds_phrases_clean_text_and_engine_query() -> None:
    p = parse_query_operators('mouse "gaming grade" wireless')
    assert p.phrases == ("gaming grade",)
    assert p.clean_text == "mouse gaming grade wireless"
    assert p.engine_query == 'mouse "gaming grade" wireless'


def test_negated_phrase_goes_to_excluded_phrases_only_and_is_hidden_from_clean_text() -> None:
    p = parse_query_operators('mouse -"black friday"')
    assert p.excluded_phrases == ("black friday",)
    assert p.phrases == ()
    assert p.clean_text == "mouse"
    assert p.engine_query == 'mouse -"black friday"'


def test_negated_term_goes_to_excluded_terms_and_is_hidden_from_clean_text() -> None:
    p = parse_query_operators("mouse -bluetooth")
    assert p.excluded_terms == ("bluetooth",)
    assert p.clean_text == "mouse"
    assert p.engine_query == "mouse -bluetooth"


def test_bare_dash_is_a_plain_term() -> None:
    p = parse_query_operators("mouse -")
    assert p.excluded_terms == ()
    assert p.clean_text == "mouse -"
    assert p.engine_query == "mouse -"


def test_unrecognized_colon_token_is_a_plain_term() -> None:
    # "10:30" and unknown pseudo-operators must not be mistaken for a recognized op.
    p = parse_query_operators("meet at 10:30 badop:xyz")
    assert p.clean_text == "meet at 10:30 badop:xyz"
    assert p.engine_query == "meet at 10:30 badop:xyz"
    assert not p.has_filters


# --- site: ---------------------------------------------------------------------------------------


def test_site_operator_parses_and_normalizes() -> None:
    p = parse_query_operators("foo site:*.Example.COM.")
    assert p.include_sites == ("example.com",)
    assert p.engine_query == "foo site:example.com"
    # site: is a pure operator; it never appears in clean_text.
    assert p.clean_text == "foo"
    assert p.has_filters


def test_negated_site_operator_parses() -> None:
    p = parse_query_operators("foo -site:aliexpress.com")
    assert p.exclude_sites == ("aliexpress.com",)
    assert p.engine_query == "foo -site:aliexpress.com"


def test_empty_site_operator_is_dropped_entirely() -> None:
    p = parse_query_operators("foo site: bar")
    assert p.include_sites == ()
    assert p.clean_text == "foo bar"
    assert p.engine_query == "foo bar"


# --- intitle: / inurl: ----------------------------------------------------------------------------


def test_intitle_and_inurl_become_bare_recall_hints_and_local_filters() -> None:
    p = parse_query_operators("intitle:review inurl:shop")
    assert p.in_title == ("review",)
    assert p.in_url == ("shop",)
    assert p.clean_text == "review shop"
    assert p.engine_query == "review shop"


def test_negated_intitle_and_inurl_are_local_only_and_dropped_from_engine_query() -> None:
    p = parse_query_operators("mouse -intitle:sponsored -inurl:ad")
    assert p.not_in_title == ("sponsored",)
    assert p.not_in_url == ("ad",)
    assert p.clean_text == "mouse"
    assert p.engine_query == "mouse"


def test_quoted_intitle_value_is_one_entry_with_spaces() -> None:
    p = parse_query_operators('intitle:"foo bar"')
    assert p.in_title == ("foo bar",)
    assert p.clean_text == "foo bar"
    assert p.engine_query == "foo bar"


# --- filetype: / ext: -----------------------------------------------------------------------------


def test_filetype_operator_parses_and_strips_leading_dot() -> None:
    p = parse_query_operators("manual filetype:.PDF")
    assert p.file_types == ("pdf",)
    assert p.engine_query == "manual filetype:pdf"
    assert p.clean_text == "manual"


def test_ext_is_an_alias_for_filetype() -> None:
    p = parse_query_operators("manual ext:DOC")
    assert p.file_types == ("doc",)
    assert p.engine_query == "manual filetype:doc"


def test_negated_filetype_has_no_defined_meaning_and_falls_back_to_excluded_term() -> None:
    p = parse_query_operators("-filetype:exe")
    assert p.file_types == ()
    assert p.excluded_terms == ("filetype:exe",)
    assert p.engine_query == "-filetype:exe"


# --- before: / after: -----------------------------------------------------------------------------


def test_date_forms_parse_to_utc_start_of_period() -> None:
    assert parse_query_operators("after:2023").after_ms == _epoch_ms(2023)
    assert parse_query_operators("after:2023-06").after_ms == _epoch_ms(2023, 6)
    assert parse_query_operators("after:2023-06-15").after_ms == _epoch_ms(2023, 6, 15)
    assert parse_query_operators("after:2023/06/15").after_ms == _epoch_ms(2023, 6, 15)
    assert parse_query_operators("before:2024").before_ms == _epoch_ms(2024)


def test_date_operators_are_dropped_from_clean_text_and_engine_query() -> None:
    p = parse_query_operators("news after:2023 before:2024")
    assert p.clean_text == "news"
    assert p.engine_query == "news"


def test_repeated_date_operator_last_one_wins() -> None:
    p = parse_query_operators("after:2020 after:2023")
    assert p.after_ms == _epoch_ms(2023)


def test_invalid_date_shape_is_kept_as_plain_term_never_dropped_silently() -> None:
    p = parse_query_operators("before:notadate")
    assert p.before_ms is None
    assert p.clean_text == "before:notadate"
    assert p.engine_query == "before:notadate"


def test_impossible_calendar_date_is_kept_as_plain_term() -> None:
    p = parse_query_operators("before:2023-13")
    assert p.before_ms is None
    assert p.clean_text == "before:2023-13"
    assert p.engine_query == "before:2023-13"


def test_negated_date_operator_has_no_defined_meaning_and_falls_back_to_excluded_term() -> None:
    p = parse_query_operators("-after:2023")
    assert p.after_ms is None
    assert p.excluded_terms == ("after:2023",)
    assert p.engine_query == "-after:2023"


# --- OR / | ---------------------------------------------------------------------------------------


def test_or_and_pipe_are_kept_in_engine_query_but_dropped_from_clean_text() -> None:
    p = parse_query_operators("cats OR dogs | birds")
    assert p.clean_text == "cats dogs birds"
    assert p.engine_query == "cats OR dogs | birds"


def test_lowercase_or_is_a_plain_term_not_the_operator() -> None:
    # Only the exact uppercase token "OR" is the operator.
    p = parse_query_operators("cats or dogs")
    assert p.clean_text == "cats or dogs"
    assert p.engine_query == "cats or dogs"


# --- tokenizer robustness -------------------------------------------------------------------------


def test_unterminated_quote_runs_to_end_of_string_without_crashing() -> None:
    p = parse_query_operators('foo "bar baz qux')
    assert p.phrases == ("bar baz qux",)
    assert p.clean_text == "foo bar baz qux"
    assert p.engine_query == 'foo "bar baz qux"'


def test_unterminated_quote_on_a_negated_operator_value_does_not_crash() -> None:
    p = parse_query_operators('intitle:"unterminated value')
    assert p.in_title == ("unterminated value",)


# --- engine_query order preservation & composite --------------------------------------------------


def test_engine_query_preserves_original_token_order_across_mixed_operators() -> None:
    p = parse_query_operators(
        'wireless mouse "gaming grade" -bluetooth site:amazon.com -site:aliexpress.com '
        "intitle:review -intitle:sponsored filetype:pdf before:2024 badtoken:xyz OR keyboards"
    )
    assert p.engine_query == (
        'wireless mouse "gaming grade" -bluetooth site:amazon.com -site:aliexpress.com '
        "review filetype:pdf badtoken:xyz OR keyboards"
    )
    assert p.clean_text == "wireless mouse gaming grade review badtoken:xyz keyboards"
    assert p.excluded_terms == ("bluetooth",)
    assert p.include_sites == ("amazon.com",)
    assert p.exclude_sites == ("aliexpress.com",)
    assert p.in_title == ("review",)
    assert p.not_in_title == ("sponsored",)
    assert p.file_types == ("pdf",)
    assert p.before_ms == _epoch_ms(2024)


# --- matches(): site: / -site: --------------------------------------------------------------------


def test_matches_enforces_site_as_a_suffix_on_the_host() -> None:
    p = parse_query_operators("foo site:example.com")
    assert p.matches("T", "https://docs.example.com/page", "", None)
    assert p.matches("T", "https://example.com/page", "", None)
    assert not p.matches("T", "https://notexample.com/page", "", None)


def test_matches_site_supports_bare_tld_entries() -> None:
    p = parse_query_operators("research site:.edu")
    assert p.matches("T", "https://mit.edu/x", "", None)
    assert not p.matches("T", "https://mit.com/x", "", None)


def test_matches_exclude_site_rejects_matching_hosts() -> None:
    p = parse_query_operators("foo -site:pinterest.com")
    assert not p.matches("T", "https://pinterest.com/x", "", None)
    assert not p.matches("T", "https://sub.pinterest.com/x", "", None)
    assert p.matches("T", "https://other.com/x", "", None)


def test_matches_include_site_rejects_an_unparsable_host() -> None:
    p = parse_query_operators("foo site:example.com")
    assert not p.matches("T", "not a url", "", None)


# --- matches(): intitle: / inurl: -----------------------------------------------------------------


def test_matches_enforces_intitle_and_not_in_title() -> None:
    p = parse_query_operators("intitle:review -intitle:sponsored")
    assert p.matches("Full Review of X", "https://x.com", "", None)
    assert not p.matches("Just a post", "https://x.com", "", None)
    assert not p.matches("Sponsored Review", "https://x.com", "", None)


def test_matches_enforces_inurl_and_not_in_url() -> None:
    p = parse_query_operators("inurl:shop -inurl:ad")
    assert p.matches("T", "https://example.com/shop/item", "", None)
    assert not p.matches("T", "https://example.com/other", "", None)
    assert not p.matches("T", "https://example.com/shop/ad/item", "", None)


# --- matches(): filetype: -------------------------------------------------------------------------


def test_matches_extracts_extension_ignoring_query_string() -> None:
    p = parse_query_operators("filetype:pdf")
    assert p.matches("T", "https://x.y/file.pdf?dl=1", "", None)
    assert not p.matches("T", "https://x.y/file.docx?dl=1", "", None)


def test_matches_filetype_rejects_a_url_with_no_extension() -> None:
    p = parse_query_operators("filetype:pdf")
    assert not p.matches("T", "https://example.com/", "", None)
    # A dot in the host (its TLD) must not be misread as a file extension.
    assert not p.matches("T", "https://example.com", "", None)


# --- matches(): before: / after: ------------------------------------------------------------------


def test_matches_enforces_date_window_inclusive_lower_exclusive_upper() -> None:
    p = parse_query_operators("after:2023 before:2024")
    lower = _epoch_ms(2023)
    upper = _epoch_ms(2024)
    assert p.matches("T", "https://x.com", "", lower)  # inclusive lower bound
    assert p.matches("T", "https://x.com", "", upper - 1)
    assert not p.matches("T", "https://x.com", "", upper)  # exclusive upper bound
    assert not p.matches("T", "https://x.com", "", lower - 1)


def test_matches_excludes_an_undated_result_when_a_date_bound_is_set() -> None:
    p = parse_query_operators("after:2023")
    assert not p.matches("T", "https://x.com", "", None)


# --- matches(): -term / -"phrase" -----------------------------------------------------------------


def test_matches_enforces_excluded_term_as_a_whole_word() -> None:
    p = parse_query_operators("-cat")
    assert p.matches("Category page", "https://x.com", "listing categories", None)
    assert not p.matches("I love cat food", "https://x.com", "", None)
    # The host is also checked (excluding a term that only appears as the domain name).
    assert not p.matches("T", "https://cat.example.com", "", None)


def test_matches_enforces_excluded_phrase_as_a_substring() -> None:
    p = parse_query_operators('-"black friday"')
    assert not p.matches("Black Friday Deals", "https://x.com", "", None)
    assert p.matches("Regular Deals", "https://x.com", "", None)


# --- matches(): positive terms/phrases are NOT locally enforced -----------------------------------


def test_matches_does_not_enforce_positive_terms_or_phrases() -> None:
    p = parse_query_operators('mouse "gaming grade"')
    assert not p.has_filters
    assert p.matches("Totally unrelated title", "https://x.com", "no overlap here either", None)


# --- has_filters ----------------------------------------------------------------------------------


def test_has_filters_is_false_for_plain_terms_phrases_and_or() -> None:
    assert not parse_query_operators("just plain words").has_filters
    assert not parse_query_operators('"a phrase" OR term').has_filters


def test_has_filters_is_true_for_every_locally_enforced_operator() -> None:
    for query in (
        "-excluded",
        '-"excluded phrase"',
        "site:example.com",
        "-site:example.com",
        "intitle:x",
        "-intitle:x",
        "inurl:x",
        "-inurl:x",
        "filetype:pdf",
        "after:2023",
        "before:2023",
    ):
        assert parse_query_operators(query).has_filters, query


def test_has_operators_is_true_for_forwarded_only_syntax() -> None:
    # A quoted phrase or OR changes engine_query without setting a structural filter; the
    # corrector-skip check must still see it as operator syntax.
    assert parse_query_operators('mouse "gaming grade"').has_operators
    assert parse_query_operators("cats OR dogs").has_operators
    assert not parse_query_operators("plain words").has_operators


# --- degenerate quotes ----------------------------------------------------------------------------


def test_blank_phrase_is_dropped_instead_of_excluding_everything() -> None:
    # A stray `-"` used to add an empty excluded phrase, and `"" in text` is always True, so a
    # single stray character filtered out every result. A stray `"` likewise polluted clean_text.
    negated = parse_query_operators('mouse -"')
    assert negated.excluded_phrases == ()
    assert negated.clean_text == "mouse"
    assert negated.matches("Any title", "https://example.com/a", "any snippet", None)
    positive = parse_query_operators('mouse "')
    assert positive.phrases == ()
    assert positive.clean_text == "mouse"
