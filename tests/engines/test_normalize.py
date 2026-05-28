"""Dedup-key behavior for `normalize_url`."""

from __future__ import annotations

from searchmob_desktop.engines.normalize import normalize_url


def test_drops_utm_and_known_tracking_params() -> None:
    raw = (
        "https://example.com/page"
        "?utm_source=newsletter&utm_medium=email&fbclid=abc&gclid=xyz"
        "&mc_cid=1&mc_eid=2&_hsenc=3&_hsmi=4&igshid=5&ref=6&ref_src=7&yclid=8&dclid=9"
        "&keep=yes"
    )
    assert normalize_url(raw) == "https://example.com/page?keep=yes"


def test_drops_all_tracking_leaves_no_query() -> None:
    raw = "https://example.com/page?utm_campaign=a&fbclid=b"
    assert normalize_url(raw) == "https://example.com/page"


def test_lowercases_scheme_and_host_keeps_path_case() -> None:
    raw = "HTTPS://Example.COM/Some/Path"
    assert normalize_url(raw) == "https://example.com/Some/Path"


def test_strips_trailing_slash_from_non_root_path() -> None:
    assert normalize_url("https://example.com/blog/") == "https://example.com/blog"


def test_keeps_root_slash() -> None:
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_preserves_non_tracking_query_params() -> None:
    raw = "https://example.com/?q=hello&page=2"
    assert normalize_url(raw) == "https://example.com/?q=hello&page=2"
