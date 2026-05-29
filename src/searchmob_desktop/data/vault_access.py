"""Best-effort access to the encrypted vault for the small per-feature blobs and the history DB.

Several features (BYO API keys, result-ranking rules, encrypted history) keep state in the vault.
This module centralizes opening the vault so callers do not each re-implement the bootstrap dance.

It is fail-soft: a missing vault, a locked zero-knowledge vault, or an unavailable keyring yields
`None`. `open_os_vault()` defaults to NEVER creating a vault (no `first_run()`), so merely reading
never writes; pass `create=True` only from an explicit opt-in (e.g. enabling encrypted history) to
bootstrap an OS-keyring vault on first use.
"""

from __future__ import annotations

from searchmob_desktop.data.bootstrap_metadata import WrapMode
from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
from searchmob_desktop.data.prefs import EncryptedPreferences
from searchmob_desktop.data.storage_bootstrap import StorageBootstrap

_ENCRYPTED_PREFS_FILENAME = "encrypted_prefs.bin"


def open_os_vault(*, create: bool = False) -> StorageBootstrap | None:
    """Return an unlocked OS-keyring `StorageBootstrap`, or `None`.

    Only auto-unlocking OS-keyring vaults are returned; a zero-knowledge (passphrase) vault stays
    locked here and yields `None` (the GUI cannot prompt for the passphrase; the CLI unlocks it).
    With `create=True` and no existing vault, an OS-keyring vault is initialized (`first_run`).
    Any error is swallowed and yields `None`.
    """
    try:
        metadata_store = BootstrapMetadataStore()
        fallback_path = metadata_store.path.parent / "keyring-fallback.kek"
        kek_store = KeyringKekStore(fallback_file_path=fallback_path)
        storage = StorageBootstrap(
            metadata_store=metadata_store,
            keyring_wrapper=KeyringDekWrapper(kek_store),
            keyring_clearer=kek_store.clear,
        )
        if storage.mode is None:
            if not create:
                return None
            storage.first_run()  # initializes OS-keyring mode and unlocks
        if storage.mode != WrapMode.OS:
            return None
        if not storage.is_unlocked and not storage.unlock_keyring():
            return None
        return storage
    except Exception:
        return None


def open_encrypted_prefs() -> EncryptedPreferences | None:
    """Return the encrypted prefs store if an OS-keyring vault exists and unlocks; else `None`."""
    storage = open_os_vault()
    if storage is None:
        return None
    prefs_file = storage.metadata_store.path.parent / _ENCRYPTED_PREFS_FILENAME
    return EncryptedPreferences(prefs_file, dek_provider=storage.dek_provider())
