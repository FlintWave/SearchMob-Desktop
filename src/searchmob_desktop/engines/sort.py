"""Result sorting: relevance, strict date, or a freshness+relevance blend.

The blend (the default) follows the "query deserves freshness" idea: a recency multiplier scales the
relevance score and is floored at 1.0, so a *dated* recent result is promoted while an *undated* one
keeps its full relevance standing (never demoted for lacking a date). Evergreen queries with no
dated results therefore look identical to plain relevance order. A small heuristic raises freshness
weight for time-sensitive queries ("release date", "latest", "score", "vs", a current/next year),
which is exactly the case where stale results are most annoying.

Pure and deterministic: identical inputs sort identically. Input is assumed already in relevance
order (the RRF order the aggregator returns), so a result's index is its relevance rank.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from enum import Enum

from searchmob_desktop.engines.types import SearchResult

_RRF_K = 60
_DAY_MS = 86_400_000
_HALF_LIFE_DAYS = 30.0
_FRESH_WEIGHT = 0.6
_QDF_BOOST = 1.8  # multiplier on the freshness weight for time-sensitive queries

# Word-boundary keywords that mark a query as wanting fresh results.
_FRESH_KEYWORDS = re.compile(
    r"\b(release dates?|releases?|latest|today|tonight|this week|breaking|news|updates?|"
    r"scores?|results?|vs\.?|schedule|when is|when does|prices?|stock|weather|live|now|current)\b",
    re.IGNORECASE,
)


class SortMode(Enum):
    """How to order results. `FRESH_RELEVANT` is the default."""

    RELEVANCE = "relevance"
    DATE = "date"
    FRESH_RELEVANT = "fresh"

    @classmethod
    def from_value(cls, value: str | None) -> SortMode:
        """Parse a stored/query value; default to the freshness blend on anything unrecognized."""
        if value:
            for mode in cls:
                if mode.value == value:
                    return mode
        return cls.FRESH_RELEVANT


def query_freshness_weight(query: str, now_ms: int) -> float:
    """Freshness weight for `query`: the baseline, boosted for time-sensitive queries."""
    if _FRESH_KEYWORDS.search(query):
        return _FRESH_WEIGHT * _QDF_BOOST
    year = datetime.fromtimestamp(now_ms / 1000, tz=UTC).year
    if str(year) in query or str(year + 1) in query:
        return _FRESH_WEIGHT * _QDF_BOOST
    return _FRESH_WEIGHT


def _recency(published: int | None, now_ms: int, weight: float) -> float:
    """A multiplier >= 1.0: 1.0 for undated, larger for fresher dated results (exp decay)."""
    if published is None:
        return 1.0
    age_days = max(0.0, (now_ms - published) / _DAY_MS)
    return 1.0 + weight * math.exp(-age_days / _HALF_LIFE_DAYS)


def sort_results(
    results: list[SearchResult],
    mode: SortMode,
    query: str,
    now_ms: int,
) -> list[SearchResult]:
    """Return `results` reordered per `mode`. Assumes input is in relevance (RRF) order."""
    if mode is SortMode.RELEVANCE or len(results) < 2:
        return list(results)

    if mode is SortMode.DATE:
        # Dated newest-first; undated keep their relevance order, after the dated ones.
        dated = [(i, r) for i, r in enumerate(results) if r.published is not None]
        undated = [r for r in results if r.published is None]
        dated.sort(key=lambda pair: (-(pair[1].published or 0), pair[0]))
        return [r for _, r in dated] + undated

    # FRESH_RELEVANT: blend a recency boost into the relevance SCORE, floored at 1.0 for undated.
    # The boost multiplies the aggregator's actual score (`relevance`), which carries the lexical
    # blend and the navigational boost, so a strong match (the official site a navigational query
    # named) keeps its lead and freshness only reorders results of comparable relevance. Earlier
    # this multiplied a positional `1/(60+index)` proxy, which flattened every rank gap to a hair
    # and let a single dated result leapfrog an undated #1 (a news/wiki page over the queried site
    # itself). When no result is scored (raw engine rows or a test fake), fall back to that proxy.
    weight = query_freshness_weight(query, now_ms)
    has_scores = any(r.relevance > 0.0 for r in results)
    scored = [
        (
            (r.relevance if has_scores else 1.0 / (_RRF_K + index))
            * _recency(r.published, now_ms, weight),
            index,
            r,
        )
        for index, r in enumerate(results)
    ]
    # Sort by blended score desc; ties fall back to relevance rank for determinism.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [r for _, _, r in scored]
