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


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One result row from one engine, in the order that engine returned it."""

    title: str
    url: str
    snippet: str
    engine: str


@dataclass(frozen=True, slots=True)
class EngineContext:
    """Shared per-search budget handed to every engine.

    `max_results` is the cap each engine is asked to return; the aggregator may return fewer or more
    distinct rows after dedup. `timeout_seconds` is the httpx client timeout, applied uniformly.
    """

    query: str
    max_results: int = 10
    timeout_seconds: float = 5.0
