"""Search-history protocol.

OFF by default. When enabled, entries are local-only and encrypted at rest (SQLCipher backend).
`suggest` is fail-soft: any failure (locked vault, schema mismatch, missing native lib) yields an
empty list rather than raising, so the typing path never breaks because of history.

Entries older than the store's TTL are swept opportunistically (on add / read), matching the
Android store's expiry. The TTL is configurable per store; the app wires `DEFAULT_HISTORY_TTL_MS`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

# Entries older than this are dropped on the next add/read. Mirrors the Android `DEFAULT_TTL_MS`.
DEFAULT_HISTORY_TTL_MS = 30 * 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class HistoryEntry:
    """A stored search-history entry."""

    query: str
    timestamp_ms: int


class HistoryStore(Protocol):
    """The history surface used by the server / CLI / GUI.

    `enabled` is the persistent toggle. When `False`, `add`/`import_entries` are no-ops and
    `recent`/`suggest`/`export_entries` return empty results without touching disk.
    """

    @property
    def enabled(self) -> bool: ...

    def set_enabled(self, enabled: bool) -> None: ...

    def add(self, query: str, timestamp_ms: int | None = None) -> None: ...

    def recent(self, limit: int) -> list[HistoryEntry]: ...

    def suggest(self, prefix: str, limit: int) -> list[str]: ...

    def export_entries(self) -> list[HistoryEntry]:
        """All live (un-expired) entries, newest first. `[]` when disabled."""
        ...

    def import_entries(self, entries: Iterable[HistoryEntry]) -> int:
        """Merge entries in; returns the count actually added. No-op (0) when disabled."""
        ...

    def delete(self, query: str, timestamp_ms: int) -> None:
        """Remove the entry matching this exact (query, timestamp_ms) pair."""
        ...

    def clear(self) -> None: ...

    def close_handle(self) -> None: ...
