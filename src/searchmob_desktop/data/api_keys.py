"""Resolve bring-your-own search API keys from the encrypted vault, with env-var fallback.

The settings dialog stores BYO keys in the encrypted vault (`EncryptedPreferences`), but the engine
builders historically only read environment variables, so a key saved through the GUI never reached
the engines. This module is the single place that resolves keys for the CLI and the GUI alike:

  1. the encrypted vault, if it exists and can be unlocked without a passphrase (OS-keyring mode);
  2. otherwise the matching environment variable.

Reading the vault is best-effort and fully fail-soft: a missing vault, a locked zero-knowledge
vault, an unavailable keyring, or any decode error simply yields no key from that source, and the
env-var fallback still applies. We never call `first_run()` here, so merely resolving keys never
creates a vault.
"""

from __future__ import annotations

import os

from searchmob_desktop.data.bootstrap_metadata import WrapMode
from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
from searchmob_desktop.data.prefs import EncryptedPreferences
from searchmob_desktop.data.storage_bootstrap import StorageBootstrap

# Canonical encrypted-prefs keys for the BYO API keys. The settings dialog imports these so the
# write side and the read side never drift.
BRAVE_KEY = "brave_api_key"
MOJEEK_KEY = "mojeek_api_key"
KAGI_KEY = "kagi_api_key"

# Environment-variable fallbacks (documented in the README and the settings dialog).
BRAVE_KEY_ENV = "SEARCHMOB_BRAVE_API_KEY"
MOJEEK_KEY_ENV = "SEARCHMOB_MOJEEK_API_KEY"
KAGI_KEY_ENV = "SEARCHMOB_KAGI_API_KEY"

# (encrypted-prefs key, env-var name) for each BYO engine.
_KEY_SOURCES: dict[str, tuple[str, str]] = {
    "brave": (BRAVE_KEY, BRAVE_KEY_ENV),
    "mojeek-api": (MOJEEK_KEY, MOJEEK_KEY_ENV),
    "kagi-api": (KAGI_KEY, KAGI_KEY_ENV),
}

_ENCRYPTED_PREFS_FILENAME = "encrypted_prefs.bin"


def read_vault_api_keys() -> dict[str, str]:
    """Best-effort read of the BYO key map from the encrypted vault. Returns `{}` on any failure.

    Only OS-keyring vaults that auto-unlock are read; a zero-knowledge (passphrase) vault stays
    locked here and yields `{}` so callers fall back to the environment.
    """
    try:
        metadata_store = BootstrapMetadataStore()
        if not metadata_store.path.exists():
            return {}
        fallback_path = metadata_store.path.parent / "keyring-fallback.kek"
        kek_store = KeyringKekStore(fallback_file_path=fallback_path)
        storage = StorageBootstrap(
            metadata_store=metadata_store,
            keyring_wrapper=KeyringDekWrapper(kek_store),
            keyring_clearer=kek_store.clear,
        )
        if storage.mode != WrapMode.OS:
            return {}
        if not storage.is_unlocked and not storage.unlock_keyring():
            return {}
        prefs_file = metadata_store.path.parent / _ENCRYPTED_PREFS_FILENAME
        if not prefs_file.exists():
            return {}
        prefs = EncryptedPreferences(prefs_file, dek_provider=storage.dek_provider())
        return prefs.read()
    except Exception:
        return {}


def resolve_api_key(engine_id: str, vault_keys: dict[str, str] | None = None) -> str | None:
    """Resolve one engine's BYO key: vault value first, then environment. `None` if neither is set.

    Pass `vault_keys` (from `read_vault_api_keys()`) to avoid re-opening the vault per engine.
    """
    source = _KEY_SOURCES.get(engine_id)
    if source is None:
        return None
    prefs_key, env_var = source
    keys = vault_keys if vault_keys is not None else read_vault_api_keys()
    value = keys.get(prefs_key)
    if value:
        return value
    env_value = os.environ.get(env_var)
    return env_value or None
