"""SqlCipherHistoryStore: same `HistoryStore` contract as in-memory, but encrypted on disk."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

# The whole module is skipped when the storage extra isn't installed. CI runs with it.
sqlcipher3 = pytest.importorskip("sqlcipher3")

from searchmob_desktop.data.history.sqlcipher_store import SqlCipherHistoryStore  # noqa: E402


def _store(tmp_path: Path, dek: bytes) -> SqlCipherHistoryStore:
    return SqlCipherHistoryStore(tmp_path / "history.db", lambda: dek)


def test_off_by_default_no_disk_writes(tmp_path: Path) -> None:
    store = _store(tmp_path, secrets.token_bytes(32))
    store.add("python", timestamp_ms=1000)
    # OFF by default: nothing was persisted.
    assert not (tmp_path / "history.db").exists()


def test_enable_then_add_creates_db_file(tmp_path: Path) -> None:
    store = _store(tmp_path, secrets.token_bytes(32))
    store.set_enabled(True)
    # Still nothing on disk until the first `add` touches the DB.
    assert not (tmp_path / "history.db").exists()
    store.add("python", timestamp_ms=1000)
    assert (tmp_path / "history.db").exists()


def test_recent_and_suggest(tmp_path: Path) -> None:
    store = _store(tmp_path, secrets.token_bytes(32))
    store.set_enabled(True)
    store.add("Python tutorial", timestamp_ms=1000)
    store.add("python tricks", timestamp_ms=2000)
    store.add("PYTHON cookbook", timestamp_ms=3000)
    store.add("rust", timestamp_ms=4000)

    rec = store.recent(2)
    assert [e.query for e in rec] == ["rust", "PYTHON cookbook"]

    out = store.suggest("py", 10)
    # Distinct, case-insensitive, recent-first.
    assert out[0] == "PYTHON cookbook"
    assert "rust" not in out
    assert len(out) == 3


def test_clear(tmp_path: Path) -> None:
    store = _store(tmp_path, secrets.token_bytes(32))
    store.set_enabled(True)
    store.add("foo", timestamp_ms=1)
    store.clear()
    assert store.recent(10) == []


def test_disable_deletes_db_file(tmp_path: Path) -> None:
    store = _store(tmp_path, secrets.token_bytes(32))
    store.set_enabled(True)
    store.add("foo", timestamp_ms=1)
    db = tmp_path / "history.db"
    assert db.exists()
    store.set_enabled(False)
    assert not db.exists()


def test_wrong_key_makes_suggest_return_empty(tmp_path: Path) -> None:
    # Write history with one DEK, then try to read with another. The wrong-key open must fail
    # internally and `suggest` must degrade to an empty list (fail-soft contract).
    dek_a = secrets.token_bytes(32)
    store_a = _store(tmp_path, dek_a)
    store_a.set_enabled(True)
    store_a.add("python", timestamp_ms=1000)
    store_a.close_handle()

    dek_b = secrets.token_bytes(32)  # different DEK
    store_b = SqlCipherHistoryStore(tmp_path / "history.db", lambda: dek_b)
    store_b.set_enabled(True)
    # Locked vault / wrong key => empty results, no exception.
    assert store_b.suggest("py", 10) == []
    assert store_b.recent(10) == []


def test_close_handle_keeps_file(tmp_path: Path) -> None:
    dek = secrets.token_bytes(32)
    store = _store(tmp_path, dek)
    store.set_enabled(True)
    store.add("foo", timestamp_ms=1)
    store.close_handle()
    assert (tmp_path / "history.db").exists()
    # Reopening with the same DEK keeps reading the same data.
    store2 = SqlCipherHistoryStore(tmp_path / "history.db", lambda: dek)
    store2.set_enabled(True)
    assert [e.query for e in store2.recent(10)] == ["foo"]
