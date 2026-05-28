"""InMemoryHistoryStore: off-by-default, toggle, recent + suggest semantics."""

from __future__ import annotations

from searchmob_desktop.data.history.in_memory_store import InMemoryHistoryStore


def test_off_by_default_add_is_noop() -> None:
    store = InMemoryHistoryStore()
    assert not store.enabled
    store.add("python", timestamp_ms=1000)
    assert store.recent(10) == []
    assert store.suggest("py", 10) == []


def test_enable_then_add_recent() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    store.add("python", timestamp_ms=1000)
    store.add("rust", timestamp_ms=2000)
    store.add("kotlin", timestamp_ms=3000)
    rec = store.recent(2)
    assert [e.query for e in rec] == ["kotlin", "rust"]


def test_suggest_prefix_case_insensitive_recent_first() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    store.add("Python tutorial", timestamp_ms=1000)
    store.add("python tricks", timestamp_ms=2000)
    store.add("PYTHON cookbook", timestamp_ms=3000)
    store.add("rust", timestamp_ms=4000)
    # Distinct queries, case-insensitive, newest first.
    out = store.suggest("py", 10)
    assert out == ["PYTHON cookbook", "python tricks", "Python tutorial"]


def test_suggest_limit() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    for i in range(5):
        store.add(f"query {i}", timestamp_ms=i)
    assert len(store.suggest("query", 3)) == 3


def test_disable_clears_entries() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    store.add("foo", timestamp_ms=1)
    store.set_enabled(False)
    assert store.recent(10) == []
    assert store.suggest("f", 10) == []


def test_blank_prefix_returns_empty() -> None:
    store = InMemoryHistoryStore()
    store.set_enabled(True)
    store.add("foo", timestamp_ms=1)
    assert store.suggest("", 10) == []
