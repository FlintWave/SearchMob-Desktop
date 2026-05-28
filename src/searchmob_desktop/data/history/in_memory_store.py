"""In-memory `HistoryStore`. Default until the user opts in to persistent history.

Useful as the test reference for the off-by-default / clear / suggest semantics; the SQLCipher
backend mirrors this behaviour on disk.
"""

from __future__ import annotations

import time

from searchmob_desktop.data.history.history import HistoryEntry


class InMemoryHistoryStore:
    """Non-encrypted, in-process. Stores nothing while `enabled` is `False`."""

    def __init__(self) -> None:
        self._enabled = False
        self._entries: list[HistoryEntry] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self._entries.clear()

    def add(self, query: str, timestamp_ms: int | None = None) -> None:
        if not self._enabled:
            return
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        self._entries.append(HistoryEntry(query=query, timestamp_ms=ts))

    def recent(self, limit: int) -> list[HistoryEntry]:
        if not self._enabled or limit <= 0:
            return []
        # Newest first.
        return sorted(self._entries, key=lambda e: e.timestamp_ms, reverse=True)[:limit]

    def suggest(self, prefix: str, limit: int) -> list[str]:
        if not self._enabled or not prefix or limit <= 0:
            return []
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

    def clear(self) -> None:
        self._entries.clear()

    def close_handle(self) -> None:
        # No on-disk handle; nothing to close. Method exists to satisfy the `HistoryStore` shape.
        return None
