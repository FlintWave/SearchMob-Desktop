"""Cross-layer parity fixes ported from Android PR #103.

Dedup-key folding (http/https, mobile subdomains), title backfill across engines,
most-specific-first domain rules, day-first slash dates, and single-digit `after:`/`before:`
month/day parts.
"""

from __future__ import annotations

import httpx
import pytest

from searchmob_desktop.engines.aggregator import aggregate
from searchmob_desktop.engines.normalize import normalize_url
from searchmob_desktop.engines.query_operators import parse_query_operators
from searchmob_desktop.engines.rank.model import RankingRules, RankRule
from searchmob_desktop.engines.rank.ranker import apply_ranking
from searchmob_desktop.engines.snippet_date import parse_date
from searchmob_desktop.engines.types import EngineContext, SearchResult

_NOW_MS = 1_780_000_000_000  # 2026-06-08, safely after every date these tests parse


# --- dedup key -------------------------------------------------------------


def test_dedup_key_folds_http_into_https() -> None:
    assert normalize_url("http://example.com/page") == normalize_url("https://example.com/page")


def test_dedup_key_folds_mobile_hosts() -> None:
    assert normalize_url("https://en.m.wikipedia.org/wiki/Kotlin") == normalize_url(
        "https://en.wikipedia.org/wiki/Kotlin"
    )
    assert normalize_url("https://m.example.com/a") == normalize_url("https://example.com/a")


def test_dedup_key_keeps_distinct_pages_distinct() -> None:
    assert normalize_url("https://example.com/a") != normalize_url("https://example.com/b")
    assert normalize_url("https://mail.example.com/") != normalize_url("https://example.com/")


# --- title backfill --------------------------------------------------------


async def _fake_blank_title(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [SearchResult(title="", url="https://example.com/page", snippet="", engine="a")]


async def _fake_titled(_client: httpx.AsyncClient, _ctx: EngineContext) -> list[SearchResult]:
    return [
        SearchResult(
            title="The actual title", url="https://example.com/page", snippet="s", engine="b"
        )
    ]


@pytest.mark.asyncio
async def test_blank_title_is_backfilled_from_a_later_engine() -> None:
    ctx = EngineContext(query="example page")
    results = await aggregate(ctx, [_fake_blank_title, _fake_titled])
    assert len(results) == 1
    assert results[0].title == "The actual title"


# --- domain rule specificity -----------------------------------------------


def test_most_specific_domain_rule_wins() -> None:
    rules = RankingRules(
        domain_rules={"example.com": RankRule.LOWER, "docs.example.com": RankRule.PIN}
    )
    items = ["https://docs.example.com/guide", "https://other.test/"]
    ranked = apply_ranking(items, rules, host_of=lambda u: u.split("/")[2])
    # Under insertion-order matching the parent's LOWER would demote the docs page; the deeper
    # docs.example.com rule must win and pin it first.
    assert ranked[0] == "https://docs.example.com/guide"


# --- slash date parsing ----------------------------------------------------


def test_slash_date_with_day_over_twelve_parses_day_first() -> None:
    parsed = parse_date("31/12/2024 - year in review", _NOW_MS)
    assert parsed is not None
    # 31 December 2024 00:00 UTC.
    assert parsed.epoch_ms == 1_735_603_200_000


def test_slash_date_defaults_to_month_first() -> None:
    parsed = parse_date("5/6/2024 - release notes", _NOW_MS)
    assert parsed is not None
    # May 6, not June 5.
    assert parsed.epoch_ms == 1_714_953_600_000


# --- single-digit before:/after: dates --------------------------------------


def test_after_accepts_single_digit_month_and_day() -> None:
    parsed = parse_query_operators("news after:2024-3-1")
    assert parsed.after_ms is not None
    # 2024-03-01 00:00 UTC.
    assert parsed.after_ms == 1_709_251_200_000
    # The date token must not survive as literal query text.
    assert "after:" not in parsed.engine_query


def test_before_accepts_single_digit_month() -> None:
    parsed = parse_query_operators("history before:2020-7")
    assert parsed.before_ms is not None
    assert "before:" not in parsed.engine_query


# --- operator-blind engines get the unscoped query ---------------------------


@pytest.mark.asyncio
async def test_wikipedia_queries_with_unscoped_text() -> None:
    import respx

    from searchmob_desktop.engines.proxy import make_privacy_client
    from searchmob_desktop.engines.wikipedia import fetch_wikipedia

    with respx.mock:
        route = respx.get(url__startswith="https://en.wikipedia.org/w/api.php").mock(
            return_value=httpx.Response(200, json=["q", [], [], []])
        )
        ctx = EngineContext(
            query="kotlin (site:reddit.com OR site:news.ycombinator.com)",
            unscoped_query="kotlin",
        )
        async with make_privacy_client() as client:
            await fetch_wikipedia(client, ctx)
        assert route.called
        sent = str(route.calls.last.request.url)
        assert "site%3A" not in sent
        assert "search=kotlin" in sent
