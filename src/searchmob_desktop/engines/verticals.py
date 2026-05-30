"""Search verticals (categories) implemented as scoped searches over the existing engines.

A vertical never adds a new upstream endpoint or an API key: it reuses the same metasearch engines
and privacy proxy as the default web search, and simply scopes the query with `site:` operators the
engines already understand, plus a sensible default sort. This keeps the privacy guarantee intact
(no new third party sees the query) while giving the user category tabs (Web / News / Forums /
Academic). Image and video verticals are intentionally absent: they would require a dedicated media
API, i.e. a new third party, which the project does not accept.

The transform is total and fail-soft: an unknown value resolves to `WEB` (no scoping), and a blank
query is returned unchanged so the route's own empty-query handling still applies.
"""

from __future__ import annotations

from enum import Enum

from searchmob_desktop.engines.sort import SortMode

# Curated, deliberately small site sets. They bias the engines that honor `site:` (DuckDuckGo,
# Mojeek) toward on-topic sources; engines that ignore the operator still contribute their normal
# results. `site:.edu` is a TLD filter the major engines accept inside an OR group.
_FORUM_SITES: tuple[str, ...] = (
    "reddit.com",
    "news.ycombinator.com",
    "stackexchange.com",
    "stackoverflow.com",
    "lemmy.world",
    "lobste.rs",
)
_ACADEMIC_SITES: tuple[str, ...] = (
    "arxiv.org",
    "semanticscholar.org",
    "ncbi.nlm.nih.gov",
    "jstor.org",
    "researchgate.net",
    "core.ac.uk",
    ".edu",
)
_NEWS_SITES: tuple[str, ...] = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "npr.org",
    "theguardian.com",
    "aljazeera.com",
    "pbs.org",
)


class Vertical(str, Enum):  # noqa: UP042
    """A search category. `WEB` is the default, unscoped metasearch.

    The value equals the lowercase name and is what the server `?vertical=` param and the GUI store.
    """

    WEB = "web"
    NEWS = "news"
    FORUMS = "forums"
    ACADEMIC = "academic"

    @classmethod
    def from_value(cls, value: str | None) -> Vertical:
        """Parse a stored/query value, defaulting to `WEB` for None or anything unrecognized."""
        if not value:
            return cls.WEB
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.WEB


_SITES: dict[Vertical, tuple[str, ...]] = {
    Vertical.NEWS: _NEWS_SITES,
    Vertical.FORUMS: _FORUM_SITES,
    Vertical.ACADEMIC: _ACADEMIC_SITES,
}


def transform_query(query: str, vertical: Vertical) -> str:
    """Return the query scoped for `vertical`: the original plus an OR group of `site:` operators.

    `WEB` and a blank query are returned unchanged. The scoping clause is appended (not prepended)
    so the user's terms stay first, which the engines weight most heavily.
    """
    sites = _SITES.get(vertical)
    if not sites or not query.strip():
        return query
    clause = " OR ".join(f"site:{site}" for site in sites)
    return f"{query} ({clause})"


def default_sort(vertical: Vertical) -> SortMode:
    """The sort to use when the user has not explicitly chosen one.

    News is time-sensitive, so it defaults to the freshness+relevance blend; forums and academic
    favor relevance (an old, highly-relevant thread or paper is usually what is wanted). Web keeps
    the global default blend.
    """
    if vertical in (Vertical.WEB, Vertical.NEWS):
        return SortMode.FRESH_RELEVANT
    return SortMode.RELEVANCE
