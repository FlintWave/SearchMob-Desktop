"""Apply a `RankingRules` profile to a list of search results.

Port of the Android ranking pass. Given items already ordered by relevance, this re-buckets them
according to the user's profile: blocked hosts are dropped, pinned hosts float to the top, raised
hosts come next, normal hosts keep their place, and lowered hosts sink to the bottom. Each bucket
preserves the input (relevance) order. An optional active lens filters items out before bucketing.

The function is generic over the item type via a `host_of` accessor (and an optional `text_of` for
lens keyword matching), so it works for `SearchResult` or any other row. It is total and fail-soft:
empty rules return the input unchanged, and any unexpected error also returns the input unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlsplit

from searchmob_desktop.engines.rank import goggles
from searchmob_desktop.engines.rank.model import Lens, RankingRules, RankRule
from searchmob_desktop.engines.rank.slop_blocklist import matches_blocklist

T = TypeVar("T")


def host_of_url(url: str) -> str | None:
    """Return the lowercased host of `url` with a leading ``www.`` stripped, or None on failure."""
    try:
        netloc = urlsplit(url.strip()).netloc
    except ValueError:
        return None
    host = netloc.split("@")[-1].split(":")[0].lower().removeprefix("www.")
    return host or None


def domain_match(rule_domain: str, host: str) -> bool:
    """Return True if `host` is `rule_domain` or a subdomain of it (www- and case-insensitive)."""
    d = rule_domain.lower().removeprefix("www.")
    return host == d or host.endswith("." + d)


def _passes_lens(lens: Lens, host: str | None, text: str) -> bool:
    if host is not None:
        if lens.include_domains and not any(domain_match(d, host) for d in lens.include_domains):
            return False
        if any(domain_match(d, host) for d in lens.exclude_domains):
            return False
    lower = text.lower()
    if lens.include_keywords and not any(kw.lower() in lower for kw in lens.include_keywords):
        return False
    if any(kw.lower() in lower for kw in lens.exclude_keywords):
        return False
    return True


def _effective_rule(
    host: str | None,
    rules: RankingRules,
    slop_domains: frozenset[str],
    slop_mode: str,
) -> RankRule:
    if host is None:
        return RankRule.NORMAL
    for key, rule in rules.domain_rules.items():
        if domain_match(key, host):
            return rule
    actions = {g.action for g in rules.goggles if goggles.matches(g.site, host)}
    if RankRule.BLOCK in actions:
        return RankRule.BLOCK
    if RankRule.RAISE in actions:
        return RankRule.RAISE
    if RankRule.LOWER in actions:
        return RankRule.LOWER
    # AI-slop blocklist last, so an explicit user rule or goggle above always wins (and a user can
    # rescue a false positive by setting that domain to NORMAL/RAISE).
    if slop_mode in ("downrank", "hide") and matches_blocklist(host, slop_domains):
        return RankRule.BLOCK if slop_mode == "hide" else RankRule.LOWER
    return RankRule.NORMAL


def apply_ranking(  # noqa: UP047
    items: list[T],
    rules: RankingRules,
    host_of: Callable[[T], str | None],
    text_of: Callable[[T], str] = lambda _: "",
    slop_domains: frozenset[str] = frozenset(),
    slop_mode: str = "off",
) -> list[T]:
    """Re-rank `items` per `rules`, preserving relevance order within each bucket.

    Empty rules + no slop filter return `items` unchanged. The active lens, if any, filters items
    before bucketing. Blocked items are dropped; the result is pinned + raised + normal + lowered.
    `slop_mode` ("off"/"downrank"/"hide") applies the bundled AI-slop blocklist after user rules.
    """
    slop_active = slop_mode in ("downrank", "hide") and bool(slop_domains)
    if rules == RankingRules() and not slop_active:
        return items
    try:
        lens = rules.active
        pinned: list[T] = []
        raised: list[T] = []
        normal: list[T] = []
        lowered: list[T] = []
        for item in items:
            host = host_of(item)
            if lens is not None and not _passes_lens(lens, host, text_of(item)):
                continue
            rule = _effective_rule(host, rules, slop_domains, slop_mode)
            if rule is RankRule.BLOCK:
                continue
            if rule is RankRule.PIN:
                pinned.append(item)
            elif rule is RankRule.RAISE:
                raised.append(item)
            elif rule is RankRule.LOWER:
                lowered.append(item)
            else:
                normal.append(item)
        return pinned + raised + normal + lowered
    except Exception:
        return items
