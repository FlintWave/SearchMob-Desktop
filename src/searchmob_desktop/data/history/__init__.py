"""On-device search history.

OFF by default (store-nothing default; nothing persists unless the user opts in). Two backends:
- `InMemoryHistoryStore`: non-encrypted, in-process; the default + the test reference.
- `SqlCipherHistoryStore`: SQLCipher-encrypted file under the user data dir; opt-in.
"""

from searchmob_desktop.data.history.history import (
    DEFAULT_HISTORY_TTL_MS,
    HistoryEntry,
    HistoryStore,
)
from searchmob_desktop.data.history.in_memory_store import InMemoryHistoryStore
from searchmob_desktop.data.history.sqlcipher_store import SqlCipherHistoryStore

__all__ = [
    "DEFAULT_HISTORY_TTL_MS",
    "HistoryEntry",
    "HistoryStore",
    "InMemoryHistoryStore",
    "SqlCipherHistoryStore",
]
