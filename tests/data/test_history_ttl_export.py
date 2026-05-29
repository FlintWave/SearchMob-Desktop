"""TTL sweep + export/import/delete, exercised against both history backends.

The in-memory and SQLCipher stores share the `HistoryStore` contract, so the behavioral tests run
against both via a parametrized factory. The SQLCipher backend is skipped without the storage extra.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path

import pytest

from searchmob_desktop.data.history import (
    HistoryEntry,
    HistoryStore,
    InMemoryHistoryStore,
)

StoreFactory = Callable[[int | None], HistoryStore]


@pytest.fixture(params=["memory", "sqlcipher"])
def make_store(request: pytest.FixtureRequest, tmp_path: Path) -> StoreFactory:
    if request.param == "memory":

        def _factory(ttl_ms: int | None) -> HistoryStore:
            return InMemoryHistoryStore(ttl_ms=ttl_ms)

        return _factory

    pytest.importorskip("sqlcipher3")
    from searchmob_desktop.data.history.sqlcipher_store import SqlCipherHistoryStore

    dek = secrets.token_bytes(32)

    def _factory(ttl_ms: int | None) -> HistoryStore:
        return SqlCipherHistoryStore(tmp_path / "history.db", lambda: dek, ttl_ms=ttl_ms)

    return _factory


def test_ttl_sweeps_old_entries_on_read(make_store: StoreFactory) -> None:
    store = make_store(60_000)  # 60-second TTL
    store.set_enabled(True)
    store.add("ancient", timestamp_ms=1)  # epoch+1ms, far older than the TTL
    store.add("fresh")  # now
    recent = store.recent(10)
    assert [e.query for e in recent] == ["fresh"]


def test_no_ttl_keeps_everything(make_store: StoreFactory) -> None:
    store = make_store(None)
    store.set_enabled(True)
    store.add("old", timestamp_ms=1)
    store.add("new", timestamp_ms=2)
    assert {e.query for e in store.recent(10)} == {"old", "new"}


def test_export_is_newest_first_and_empty_when_disabled(make_store: StoreFactory) -> None:
    store = make_store(None)
    assert store.export_entries() == []  # disabled
    store.set_enabled(True)
    store.add("a", timestamp_ms=1000)
    store.add("b", timestamp_ms=3000)
    store.add("c", timestamp_ms=2000)
    assert [e.query for e in store.export_entries()] == ["b", "c", "a"]


def test_import_merges_and_is_idempotent(make_store: StoreFactory) -> None:
    store = make_store(None)
    store.set_enabled(True)
    store.add("existing", timestamp_ms=1000)
    entries = [
        HistoryEntry(query="existing", timestamp_ms=1000),  # duplicate, skipped
        HistoryEntry(query="imported-1", timestamp_ms=2000),
        HistoryEntry(query="imported-2", timestamp_ms=3000),
    ]
    added = store.import_entries(entries)
    assert added == 2
    # Re-importing the same set adds nothing.
    assert store.import_entries(entries) == 0
    assert {e.query for e in store.export_entries()} == {"existing", "imported-1", "imported-2"}


def test_import_is_noop_when_disabled(make_store: StoreFactory) -> None:
    store = make_store(None)
    assert store.import_entries([HistoryEntry(query="x", timestamp_ms=1)]) == 0


def test_delete_removes_exact_entry(make_store: StoreFactory) -> None:
    store = make_store(None)
    store.set_enabled(True)
    store.add("keep", timestamp_ms=1000)
    store.add("drop", timestamp_ms=2000)
    store.delete("drop", 2000)
    assert [e.query for e in store.export_entries()] == ["keep"]
    # Deleting a non-existent pair is a harmless no-op.
    store.delete("drop", 9999)
    assert [e.query for e in store.export_entries()] == ["keep"]
