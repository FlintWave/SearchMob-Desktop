"""Search-history protocol.

OFF by default. When enabled, entries are local-only and encrypted at rest (SQLCipher backend).
`suggest` is fail-soft: any failure (locked vault, schema mismatch, missing native lib) yields an
empty list rather than raising, so the typing path never breaks because of history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HistoryEntry:
    """A stored search-history entry."""

    query: str
    timestamp_ms: int


class HistoryStore(Protocol):
    """The history surface used by the server / CLI.

    `enabled` is the persistent toggle. When `False`, `add` is a no-op and `recent`/`suggest`
    return empty results without touching disk.
    """

    @property
    def enabled(self) -> bool: ...

    def set_enabled(self, enabled: bool) -> None: ...

    def add(self, query: str, timestamp_ms: int | None = None) -> None: ...

    def recent(self, limit: int) -> list[HistoryEntry]: ...

    def suggest(self, prefix: str, limit: int) -> list[str]: ...

    def clear(self) -> None: ...

    def close_handle(self) -> None: ...
