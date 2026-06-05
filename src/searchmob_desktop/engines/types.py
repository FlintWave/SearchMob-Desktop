"""Public engine types: the inputs and outputs every adapter agrees on.

Mirrors the contract in the Android `EngineAdapter.kt`: a `SearchResult` is the normalized item one
adapter returns, and `EngineContext` is the per-search budget (query string, result cap, timeout).

Adapters here are plain `async` callables, not classes (see `engines/__init__.py`), so we do not
need the Kotlin `EngineAdapter` interface or the `EngineResult.Success/Failure` sum type. Adapters
are fail-soft and return `[]` on any error, which is the same observable behavior as the Kotlin
`EngineResult.Failure` branch from the aggregator's perspective.
"""

from __future__ import annotations

from dataclasses import dataclass

from searchmob_desktop.engines.region import LanguageRegion

# The ranked POOL size a search holds, distinct from the REVEAL window the UI shows first. The
# aggregator ranks and returns up to this many merged results; the GUI, served page, and Android
# list reveal a smaller window and grow it on scroll (infinite scroll) without re-querying. Kept
# modest so the per-engine fan-out stays bounded; a short first page just contributes less.
DEFAULT_POOL_SIZE = 40


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One result row from one engine, in the order that engine returned it.

    `published` is the result's best-known publication time in epoch milliseconds, or `None` when
    no date could be determined (the common case for general web results). It drives freshness
    sorting; `None` means "unknown", treated as neither old nor new.
    """

    title: str
    url: str
    snippet: str
    engine: str
    published: int | None = None


@dataclass(frozen=True, slots=True)
class EngineContext:
    """Shared per-search budget handed to every engine.

    `max_results` is the cap each engine is asked to return; the aggregator may return fewer or more
    distinct rows after dedup. `timeout_seconds` is the httpx client timeout, applied uniformly.
    `language_region`, when set, carries per-engine language/region parameters that tailor results
    to the UI language (DuckDuckGo `kl`, Brave `country`/`search_lang`/`ui_lang`); None is neutral.
    """

    query: str
    max_results: int = 10
    timeout_seconds: float = 5.0
    language_region: LanguageRegion | None = None
