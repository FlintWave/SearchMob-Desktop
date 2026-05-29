"""Best-effort access to the encrypted vault for read/write of small settings blobs.

Several features (BYO API keys, result-ranking rules) keep a small value in the encrypted prefs.
This module centralizes opening the vault so callers do not each re-implement the bootstrap dance.
It is fully fail-soft: a missing vault, a locked zero-knowledge vault, or an unavailable keyring
yields `None`, and it never creates a vault (no `first_run()`), so merely reading never writes.
"""

from __future__ import annotations

from searchmob_desktop.data.bootstrap_metadata import WrapMode
from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
from searchmob_desktop.data.prefs import EncryptedPreferences
from searchmob_desktop.data.storage_bootstrap import StorageBootstrap

_ENCRYPTED_PREFS_FILENAME = "encrypted_prefs.bin"


def open_encrypted_prefs() -> EncryptedPreferences | None:
    """Return the encrypted prefs store if an OS-keyring vault exists and unlocks; else `None`.

    Only auto-unlocking OS-keyring vaults are opened; a zero-knowledge (passphrase) vault stays
    locked here and yields `None`. Any error is swallowed.
    """
    try:
        metadata_store = BootstrapMetadataStore()
        if not metadata_store.path.exists():
            return None
        fallback_path = metadata_store.path.parent / "keyring-fallback.kek"
        kek_store = KeyringKekStore(fallback_file_path=fallback_path)
        storage = StorageBootstrap(
            metadata_store=metadata_store,
            keyring_wrapper=KeyringDekWrapper(kek_store),
            keyring_clearer=kek_store.clear,
        )
        if storage.mode != WrapMode.OS:
            return None
        if not storage.is_unlocked and not storage.unlock_keyring():
            return None
        prefs_file = metadata_store.path.parent / _ENCRYPTED_PREFS_FILENAME
        return EncryptedPreferences(prefs_file, dek_provider=storage.dek_provider())
    except Exception:
        return None
