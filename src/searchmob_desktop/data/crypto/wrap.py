"""DEK wrappers.

A `DekWrapper` encrypts a DEK with a key-encryption key (KEK) it controls. Implementations:
- `KeyringDekWrapper`: KEK comes from the OS keyring; recoverable without a user prompt.
- `PassphraseDekWrapper`: KEK is derived from a user passphrase via Argon2id; zero-knowledge,
  unrecoverable if the passphrase is lost (by design).
- `SecretKeyDekWrapper`: KEK is a caller-supplied raw AES key; the testable reference.

`unwrap` returns `None` on auth failure (wrong key / tampered blob), never raises.
"""

from __future__ import annotations

from typing import Protocol

from searchmob_desktop.data.crypto.aes_gcm import decrypt, encrypt
from searchmob_desktop.data.crypto.argon2_kdf import Argon2idKdf
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore


class DekWrapper(Protocol):
    """The wrap/unwrap contract used by `StorageBootstrap`."""

    def wrap(self, dek: bytes) -> bytes: ...

    def unwrap(self, blob: bytes) -> bytes | None: ...


class SecretKeyDekWrapper:
    """Wraps the DEK with a caller-supplied raw 32-byte AES key. Used by tests."""

    def __init__(self, kek: bytes) -> None:
        self._kek = kek

    def wrap(self, dek: bytes) -> bytes:
        return encrypt(self._kek, dek)

    def unwrap(self, blob: bytes) -> bytes | None:
        return decrypt(self._kek, blob)


class KeyringDekWrapper:
    """Wraps the DEK with a KEK pulled from the OS keyring (`KeyringKekStore`).

    The KEK never leaves this process unencrypted (it lives in the OS keyring's secure storage
    until `load()`, and is held briefly in memory while wrapping/unwrapping).
    """

    def __init__(self, kek_store: KeyringKekStore) -> None:
        self._kek_store = kek_store

    def wrap(self, dek: bytes) -> bytes:
        return encrypt(self._kek_store.load(), dek)

    def unwrap(self, blob: bytes) -> bytes | None:
        # Try every KEK the store still holds (the keyring entry and/or the fallback file). load()
        # prefers one source, but the DEK may have been wrapped with the other if the keyring's
        # availability changed between wrap and unwrap; trying both makes unlock robust to that.
        candidates = self._kek_store.candidate_keks()
        if not candidates:
            # No KEK is readable yet (fresh process, nothing generated). Fall back to load(), which
            # creates/returns one, so a first wrap-then-unwrap in the same run still works.
            candidates = [self._kek_store.load()]
        for kek in candidates:
            dek = decrypt(kek, blob)
            if dek is not None:
                return dek
        return None


class PassphraseDekWrapper:
    """Zero-knowledge wrapper: derives the KEK from a passphrase + salt via Argon2id.

    A wrong passphrase yields a different KEK and so a failed GCM auth (`None`). Data is
    unrecoverable without the exact passphrase. The passphrase is held only as long as this object
    lives; callers should construct a wrapper per-operation and zero their passphrase buffer
    afterwards.
    """

    def __init__(self, kdf: Argon2idKdf, passphrase: bytes, salt: bytes) -> None:
        self._kdf = kdf
        self._passphrase = passphrase
        self._salt = salt

    def wrap(self, dek: bytes) -> bytes:
        kek = self._kdf.derive(self._passphrase, self._salt, length=32)
        return encrypt(kek, dek)

    def unwrap(self, blob: bytes) -> bytes | None:
        kek = self._kdf.derive(self._passphrase, self._salt, length=32)
        return decrypt(kek, blob)
