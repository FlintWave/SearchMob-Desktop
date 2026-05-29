"""In-memory `HistoryStore`. Default until the user opts in to persistent history.

Useful as the test reference for the off-by-default / clear / suggest semantics; the SQLCipher
backend mirrors this behaviour on disk.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from searchmob_desktop.data.history.history import HistoryEntry


class InMemoryHistoryStore:
    """Non-encrypted, in-process. Stores nothing while `enabled` is `False`.

    `ttl_ms` defaults to `None` (no expiry) so this stays a faithful test reference; the app wires
    the SQLCipher backend with a real TTL. When set, entries older than `ttl_ms` are swept on the
    next add/read.
    """

    def __init__(self, ttl_ms: int | None = None) -> None:
        self._enabled = False
        self._entries: list[HistoryEntry] = []
        self._ttl_ms = ttl_ms

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._entries.clear()

    def _sweep(self) -> None:
        """Drop entries older than the TTL. No-op when `ttl_ms` is `None`."""
        if self._ttl_ms is None:
            return
        cutoff = int(time.time() * 1000) - self._ttl_ms
        self._entries = [e for e in self._entries if e.timestamp_ms >= cutoff]

    def add(self, query: str, timestamp_ms: int | None = None) -> None:
        if not self._enabled:
            return
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        self._entries.append(HistoryEntry(query=query, timestamp_ms=ts))
        self._sweep()

    def recent(self, limit: int) -> list[HistoryEntry]:
        if not self._enabled or limit <= 0:
            return []
        self._sweep()
        # Newest first.
        return sorted(self._entries, key=lambda e: e.timestamp_ms, reverse=True)[:limit]

    def suggest(self, prefix: str, limit: int) -> list[str]:
        if not self._enabled or not prefix or limit <= 0:
            return []
        self._sweep()
        lower_prefix = prefix.lower()
        seen: dict[str, int] = {}
        # Distinct, case-insensitive prefix match, recent-first, capped.
        for entry in sorted(self._entries, key=lambda e: e.timestamp_ms, reverse=True):
            if entry.query.lower().startswith(lower_prefix):
                key = entry.query.lower()
                if key not in seen:
                    seen[key] = entry.timestamp_ms
                    if len(seen) >= limit:
                        break
        # Preserve the original casing of the most recent occurrence per distinct query.
        result: list[str] = []
        for entry in sorted(self._entries, key=lambda e: e.timestamp_ms, reverse=True):
            key = entry.query.lower()
            if key in seen and entry.query not in result:
                result.append(entry.query)
                if len(result) >= limit:
                    break
        return result[:limit]

    def export_entries(self) -> list[HistoryEntry]:
        if not self._enabled:
            return []
        self._sweep()
        return sorted(self._entries, key=lambda e: e.timestamp_ms, reverse=True)

    def import_entries(self, entries: Iterable[HistoryEntry]) -> int:
        if not self._enabled:
            return 0
        existing = {(e.query, e.timestamp_ms) for e in self._entries}
        added = 0
        for entry in entries:
            key = (entry.query, entry.timestamp_ms)
            if key in existing:
                continue
            existing.add(key)
            self._entries.append(entry)
            added += 1
        self._sweep()
        return added

    def delete(self, query: str, timestamp_ms: int) -> None:
        self._entries = [
            e for e in self._entries if not (e.query == query and e.timestamp_ms == timestamp_ms)
        ]

    def clear(self) -> None:
        self._entries.clear()

    def close_handle(self) -> None:
        # No on-disk handle; nothing to close. Method exists to satisfy the `HistoryStore` shape.
        return None
