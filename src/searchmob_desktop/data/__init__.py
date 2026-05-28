"""Encrypted-storage layer (Phase 3).

Mirrors the contract from the Android `org.searchmob.data` package: AES-256-GCM with a 12-byte
random nonce, Argon2id KDF for zero-knowledge mode, a bootstrap-metadata file recording the
wrapped DEK + KDF params, an in-memory `Vault` for the unwrapped DEK, encrypted prefs, and an
OFF-by-default SQLCipher history store.

The KEK story differs from Android: no Keystore equivalent on desktop, so the default is an OS
keyring entry (macOS Keychain / Windows Credential Manager / Linux Secret Service or kwallet)
with a 0600 file as a last-resort fallback. Zero-knowledge mode (Argon2id over a user passphrase)
is the same on both platforms.
"""

from searchmob_desktop.data.bootstrap_metadata import (
    LEGACY_KDF_ALGORITHM,
    LEGACY_KDF_ITERATIONS,
    LEGACY_KDF_MEMORY_KIB,
    LEGACY_KDF_PARALLELISM,
    BootstrapMetadata,
    WrapMode,
)
from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore
from searchmob_desktop.data.history import (
    HistoryEntry,
    HistoryStore,
    InMemoryHistoryStore,
    SqlCipherHistoryStore,
)
from searchmob_desktop.data.prefs import EncryptedPreferences
from searchmob_desktop.data.storage_bootstrap import (
    ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING,
    StorageBootstrap,
)
from searchmob_desktop.data.vault import Vault

__all__ = [
    "LEGACY_KDF_ALGORITHM",
    "LEGACY_KDF_ITERATIONS",
    "LEGACY_KDF_MEMORY_KIB",
    "LEGACY_KDF_PARALLELISM",
    "ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING",
    "BootstrapMetadata",
    "BootstrapMetadataStore",
    "EncryptedPreferences",
    "HistoryEntry",
    "HistoryStore",
    "InMemoryHistoryStore",
    "SqlCipherHistoryStore",
    "StorageBootstrap",
    "Vault",
    "WrapMode",
]
