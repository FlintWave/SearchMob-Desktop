"""SQLCipher-backed `HistoryStore`.

The whole database file (table, indices, and WAL/SHM sidecars) is encrypted at rest by SQLCipher
using the shared DEK as a raw-bytes key. We pass the key as `PRAGMA key = "x'<hex>'"` so the DEK
goes straight in as 32 bytes of entropy and SQLCipher skips its own internal PBKDF2 (the DEK is
already random; running another KDF over it would just be expensive without adding strength).

`dek_provider` is invoked lazily on first DB access; a locked vault makes it raise, which
`suggest`/`recent` catch and turn into an empty list (fail-soft: typing must never break because
the vault is locked).

Schema:
    CREATE TABLE history(
        id INTEGER PRIMARY KEY,
        query TEXT NOT NULL,
        timestamp_ms INTEGER NOT NULL
    )

Compromise vs the Android contract: pysqlcipher3 does not build on modern Python, so the desktop
port uses `sqlcipher3-binary` (the same `sqlcipher3` C binding, just shipped as a wheel). The
import surface is identical.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from searchmob_desktop.data.history.history import HistoryEntry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

_log = logging.getLogger(__name__)


def _try_import_sqlcipher() -> object | None:
    """Return the `sqlcipher3` module if available, else `None`.

    The `storage` extra installs `sqlcipher3-binary`, but we don't want a missing wheel to crash
    the whole CLI on import; history simply stays unavailable until the user installs the extra.
    """
    try:
        import sqlcipher3  # type: ignore[import-untyped]
    except ImportError:
        return None
    return sqlcipher3  # type: ignore[no-any-return]


class SqlCipherHistoryStore:
    """Encrypted on-disk history. OFF by default.

    The DB file is created lazily on the first `add` after `set_enabled(True)`; disabling the
    store deletes the DB file (and its WAL/SHM sidecars). Locking the vault closes the live
    handle but preserves the encrypted file on disk for the next unlock.
    """

    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS history ("
        "  id INTEGER PRIMARY KEY,"
        "  query TEXT NOT NULL,"
        "  timestamp_ms INTEGER NOT NULL"
        ")"
    )

    def __init__(
        self,
        db_path: Path,
        dek_provider: Callable[[], bytes],
        sqlcipher_module: object | None = None,
        ttl_ms: int | None = None,
    ) -> None:
        self._db_path = db_path
        self._dek_provider = dek_provider
        self._sqlcipher = (
            sqlcipher_module if sqlcipher_module is not None else _try_import_sqlcipher()
        )
        self._enabled = False
        self._conn: object | None = None  # sqlcipher3.Connection
        # When set, entries older than this are deleted opportunistically on add/read. Default
        # `None` (no expiry) keeps the test reference simple; the app wires the real TTL.
        self._ttl_ms = ttl_ms

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled = True
            # DB file is created lazily on first `add`; nothing on disk just from enabling.
        else:
            self._enabled = False
            self._close()
            self._delete_db_files()

    def add(self, query: str, timestamp_ms: int | None = None) -> None:
        if not self._enabled:
            return
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
        try:
            conn = self._connect()
            conn.execute(  # type: ignore[attr-defined]
                "INSERT INTO history(query, timestamp_ms) VALUES(?, ?)", (query, ts)
            )
            self._sweep(conn)
            conn.commit()  # type: ignore[attr-defined]
        except Exception as exc:
            _log.warning("history add failed: %s", exc)

    def recent(self, limit: int) -> list[HistoryEntry]:
        if not self._enabled or limit <= 0:
            return []
        try:
            conn = self._connect()
            self._sweep(conn)
            rows = conn.execute(  # type: ignore[attr-defined]
                "SELECT query, timestamp_ms FROM history ORDER BY timestamp_ms DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except Exception:
            return []
        return [HistoryEntry(query=q, timestamp_ms=ts) for (q, ts) in rows]

    def suggest(self, prefix: str, limit: int) -> list[str]:
        if not self._enabled or not prefix or limit <= 0:
            return []
        try:
            conn = self._connect()
            self._sweep(conn)
            rows = conn.execute(  # type: ignore[attr-defined]
                "SELECT query FROM history "
                "WHERE query LIKE ? || '%' COLLATE NOCASE "
                "GROUP BY query COLLATE NOCASE "
                "ORDER BY MAX(timestamp_ms) DESC "
                "LIMIT ?",
                (prefix, limit),
            ).fetchall()
        except Exception:
            # schema mismatch must never break the typing path.
            return []
        return [row[0] for row in rows]

    def export_entries(self) -> list[HistoryEntry]:
        if not self._enabled:
            return []
        try:
            conn = self._connect()
            self._sweep(conn)
            rows = conn.execute(  # type: ignore[attr-defined]
                "SELECT query, timestamp_ms FROM history ORDER BY timestamp_ms DESC"
            ).fetchall()
        except Exception:
            return []
        return [HistoryEntry(query=q, timestamp_ms=ts) for (q, ts) in rows]

    def import_entries(self, entries: Iterable[HistoryEntry]) -> int:
        if not self._enabled:
            return 0
        added = 0
        try:
            conn = self._connect()
            for entry in entries:
                # Skip an exact duplicate so a re-import is idempotent.
                exists = conn.execute(  # type: ignore[attr-defined]
                    "SELECT 1 FROM history WHERE query = ? AND timestamp_ms = ? LIMIT 1",
                    (entry.query, entry.timestamp_ms),
                ).fetchone()
                if exists:
                    continue
                conn.execute(  # type: ignore[attr-defined]
                    "INSERT INTO history(query, timestamp_ms) VALUES(?, ?)",
                    (entry.query, entry.timestamp_ms),
                )
                added += 1
            self._sweep(conn)
            conn.commit()  # type: ignore[attr-defined]
        except Exception as exc:
            _log.warning("history import failed: %s", exc)
            return 0
        return added

    def delete(self, query: str, timestamp_ms: int) -> None:
        if not self._db_path.exists() and self._conn is None:
            return
        try:
            conn = self._connect()
            conn.execute(  # type: ignore[attr-defined]
                "DELETE FROM history WHERE query = ? AND timestamp_ms = ?", (query, timestamp_ms)
            )
            conn.commit()  # type: ignore[attr-defined]
        except Exception as exc:
            _log.warning("history delete failed: %s", exc)

    def clear(self) -> None:
        if not self._db_path.exists() and self._conn is None:
            return
        try:
            conn = self._connect()
            conn.execute("DELETE FROM history")  # type: ignore[attr-defined]
            conn.commit()  # type: ignore[attr-defined]
        except Exception as exc:
            _log.warning("history clear failed: %s", exc)

    def close_handle(self) -> None:
        """Close the live DEK-keyed handle but keep the encrypted file on disk.

        Used on vault lock (passphrase mode) so a locked session has no open DB handle, while the
        encrypted file survives until the user unlocks again or explicitly clears.
        """
        self._close()

    # ------------------------------------------------------------------ internal --

    def _sweep(self, conn: object) -> None:
        """Delete entries older than the TTL. No-op when `ttl_ms` is `None`. Caller commits."""
        if self._ttl_ms is None:
            return
        cutoff = int(time.time() * 1000) - self._ttl_ms
        conn.execute("DELETE FROM history WHERE timestamp_ms < ?", (cutoff,))  # type: ignore[attr-defined]

    def _connect(self) -> object:
        if self._conn is not None:
            return self._conn
        if self._sqlcipher is None:
            raise RuntimeError(
                "sqlcipher3 is not installed. "
                "Install with `pip install 'searchmob-desktop[storage]'`."
            )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._sqlcipher.connect(str(self._db_path))  # type: ignore[attr-defined]
        # Pass the DEK as raw bytes via `PRAGMA key = "x'<hex>'"`. SQLCipher then skips its own
        # PBKDF2 and uses the 32 bytes directly as the file key (key_derivation_method = 0). The
        # DEK is already a random 32-byte value, so re-running a KDF over it adds cost without
        # adding entropy.
        hex_key = self._dek_provider().hex()
        conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        # Smoke-test the key by issuing a trivial query; a wrong key surfaces here as an exception
        # before we hand the connection to the caller.
        conn.execute(self.SCHEMA)
        self._conn = conn
        return conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._conn = None

    def _delete_db_files(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = Path(str(self._db_path) + suffix)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
