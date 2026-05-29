"""Exactness checks for the ported string metrics."""

from __future__ import annotations

from searchmob_desktop.engines.correct.string_metrics import jaro_winkler, osa_distance


def test_osa_identity_is_zero() -> None:
    assert osa_distance("hello", "hello") == 0
    assert osa_distance("", "") == 0


def test_osa_empty_against_nonempty() -> None:
    assert osa_distance("", "abc") == 3
    assert osa_distance("abc", "") == 3


def test_osa_insertions_and_substitutions() -> None:
    assert osa_distance("ca", "abc", 10) == 3
    assert osa_distance("kitten", "sitting", 10) == 3


def test_osa_adjacent_transposition_counts_as_one() -> None:
    assert osa_distance("ac", "ca", 10) == 1
    assert osa_distance("converse", "convesre", 10) == 1


def test_osa_early_cutoff_returns_max_plus_one() -> None:
    # Length difference alone exceeds the cap.
    assert osa_distance("a", "abcdef", 2) == 3
    # Row-min cutoff during the DP.
    assert osa_distance("abcdef", "uvwxyz", 2) == 3


def test_osa_none_cap_is_unbounded() -> None:
    assert osa_distance("abcdef", "uvwxyz") == 6


def test_jaro_winkler_known_value() -> None:
    assert abs(jaro_winkler("martha", "marhta") - 0.961) < 0.001


def test_jaro_winkler_bounds() -> None:
    assert jaro_winkler("", "") == 1.0
    assert jaro_winkler("abc", "abc") == 1.0
    assert jaro_winkler("", "abc") == 0.0
    assert jaro_winkler("abc", "") == 0.0


def test_jaro_winkler_no_matches_is_zero() -> None:
    assert jaro_winkler("abc", "xyz") == 0.0


def test_jaro_winkler_in_unit_range() -> None:
    value = jaro_winkler("dwayne", "duane")
    assert 0.0 <= value <= 1.0
    assert value > 0.8
