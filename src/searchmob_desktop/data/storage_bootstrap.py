"""DEK lifecycle: first-run, unlock, and zero-knowledge enable/disable.

Mirrors `org.searchmob.data.StorageBootstrap`. The contract:
- First run: generate a 32-byte DEK, wrap it with the OS-keyring KEK, persist the wrapped DEK
  + a random salt + the wrap mode in `BootstrapMetadata`. Unlock the vault.
- Later run, OS mode: unwrap the DEK with the keyring KEK (no prompt). Unlock the vault.
- Later run, passphrase mode: stay locked until `unlock_with_passphrase(passphrase)`. The Argon2id
  params come from the STORED metadata so a future tuning never bricks this vault.
- Enable zero-knowledge: re-wrap the SAME DEK with a passphrase-derived KEK. No data is
  re-encrypted (history DB + prefs blob keep using the same DEK). Requires `warning_confirmed=True`
  because losing the passphrase is unrecoverable by design. Drops the keyring KEK on success.
- Disable zero-knowledge: re-wrap the SAME DEK under a fresh keyring KEK. Requires the vault to
  be unlocked (the user just typed the passphrase to unlock).
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Callable

from searchmob_desktop.data.bootstrap_metadata import BootstrapMetadata, WrapMode
from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore
from searchmob_desktop.data.crypto.argon2_kdf import Argon2idKdf
from searchmob_desktop.data.crypto.dek import random_dek
from searchmob_desktop.data.crypto.wrap import DekWrapper, PassphraseDekWrapper
from searchmob_desktop.data.vault import Vault

ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING = (
    "Zero-knowledge mode encrypts your data with a passphrase only you know. "
    "If you forget this passphrase, your settings, saved API keys, and search history become "
    "PERMANENTLY UNRECOVERABLE. There is no reset, recovery, or backup. "
    "Your data is also unreadable until you unlock with the passphrase each session."
)

DEFAULT_SALT_SIZE = 16


class StorageBootstrap:
    """Owns the DEK lifecycle.

    `keyring_wrapper` is the OS-keyring `DekWrapper` (production: `KeyringDekWrapper`); injectable
    so tests can use `SecretKeyDekWrapper` with a fixed KEK. `kdf` is the live Argon2id profile;
    the same instance is used to record params into metadata when enabling zero-knowledge. On
    unlock, the params come from the metadata (not `kdf`), so a re-tuned `kdf` does not break old
    vaults.
    """

    def __init__(
        self,
        metadata_store: BootstrapMetadataStore,
        keyring_wrapper: DekWrapper,
        vault: Vault | None = None,
        kdf: Argon2idKdf | None = None,
        salt_size: int = DEFAULT_SALT_SIZE,
        security_level_provider: Callable[[], str] | None = None,
        keyring_clearer: Callable[[], None] | None = None,
    ) -> None:
        self._metadata_store = metadata_store
        self._keyring_wrapper = keyring_wrapper
        self._vault = vault if vault is not None else Vault()
        self._kdf = kdf if kdf is not None else Argon2idKdf()
        self._salt_size = salt_size
        self._security_level_provider = security_level_provider or (lambda: "os")
        self._keyring_clearer = keyring_clearer or (lambda: None)

    @property
    def is_unlocked(self) -> bool:
        return self._vault.is_unlocked

    @property
    def mode(self) -> WrapMode | None:
        meta = self._metadata_store.read()
        return meta.mode if meta is not None else None

    @property
    def vault(self) -> Vault:
        return self._vault

    @property
    def metadata_store(self) -> BootstrapMetadataStore:
        return self._metadata_store

    def first_run(self) -> None:
        """Generate a DEK, wrap with the keyring KEK, persist metadata, unlock the vault.

        No-op if metadata already exists; use `unlock_keyring` or `unlock_with_passphrase`.
        """
        if self._metadata_store.exists():
            return
        dek = random_dek()
        wrapped = self._keyring_wrapper.wrap(dek)
        self._metadata_store.write(
            BootstrapMetadata(
                wrapped_dek_b64=_b64(wrapped),
                salt_b64=_b64(self._random_salt()),
                mode=WrapMode.OS,
                security_level=self._security_level_provider(),
            )
        )
        self._vault.unlock(dek)

    def unlock_keyring(self) -> bool:
        """In OS mode, unwrap the DEK with the keyring KEK and unlock the vault.

        Returns `True` on success; `False` if metadata is missing, the mode is wrong, or the
        keyring unwrap fails (e.g. someone wiped the keyring entry).
        """
        meta = self._metadata_store.read()
        if meta is None or meta.mode != WrapMode.OS:
            return False
        dek = self._keyring_wrapper.unwrap(_b64d(meta.wrapped_dek_b64))
        if dek is None:
            return False
        self._vault.unlock(dek)
        return True

    def unlock_with_passphrase(self, passphrase: bytearray) -> bool:
        """In PASSPHRASE mode, derive the KEK from the STORED KDF params and unlock.

        Returns `True` on success; `False` for missing metadata, wrong mode, or wrong passphrase
        (GCM auth failure). Never raises on a wrong passphrase, so callers can avoid a
        timing-revealing exception path. The passphrase buffer is the caller's; we read it and do
        not zero it ourselves so the caller can manage its lifetime.
        """
        meta = self._metadata_store.read()
        if meta is None or meta.mode != WrapMode.PASSPHRASE:
            return False
        kdf = Argon2idKdf(
            iterations=meta.kdf_iterations,
            memory_kib=meta.kdf_memory_kib,
            parallelism=meta.kdf_parallelism,
        )
        wrapper = PassphraseDekWrapper(kdf, bytes(passphrase), _b64d(meta.salt_b64))
        dek = wrapper.unwrap(_b64d(meta.wrapped_dek_b64))
        if dek is None:
            return False
        self._vault.unlock(dek)
        return True

    def enable_zero_knowledge(
        self,
        passphrase: bytearray,
        *,
        warning_confirmed: bool,
    ) -> None:
        """Re-wrap the SAME unlocked DEK with a passphrase-derived KEK.

        Requires `warning_confirmed=True` (normative; the caller must have surfaced
        `ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING` to the user). Requires the vault to be unlocked.
        Records the CURRENT KDF params into metadata so a later tuning never bricks this vault.
        Clears the keyring KEK on success: the keyring is no longer the wrapper of record.
        """
        if not warning_confirmed:
            raise ValueError(
                "Zero-knowledge mode requires explicit confirmation of the "
                "unrecoverable-data warning."
            )
        if not self._vault.is_unlocked:
            raise RuntimeError("Cannot enable zero-knowledge mode while locked.")
        dek = self._vault.dek()
        salt = self._random_salt()
        wrapper = PassphraseDekWrapper(self._kdf, bytes(passphrase), salt)
        wrapped = wrapper.wrap(dek)
        self._metadata_store.write(
            BootstrapMetadata(
                wrapped_dek_b64=_b64(wrapped),
                salt_b64=_b64(salt),
                mode=WrapMode.PASSPHRASE,
                security_level="passphrase",
                kdf_algorithm=self._kdf.ALGORITHM,
                kdf_iterations=self._kdf.iterations,
                kdf_memory_kib=self._kdf.memory_kib,
                kdf_parallelism=self._kdf.parallelism,
            )
        )
        # Drop the keyring KEK; it is no longer the wrapper of record.
        try:
            self._keyring_clearer()
        except Exception:
            pass

    def disable_zero_knowledge(self) -> None:
        """Re-wrap the SAME unlocked DEK under a fresh keyring KEK.

        Requires the vault to be unlocked (the user just typed the passphrase). The keyring KEK is
        regenerated implicitly: `keyring_wrapper.wrap(dek)` will repopulate the keyring entry that
        `enable_zero_knowledge` cleared.
        """
        if not self._vault.is_unlocked:
            raise RuntimeError("Cannot disable zero-knowledge mode while locked.")
        dek = self._vault.dek()
        wrapped = self._keyring_wrapper.wrap(dek)
        self._metadata_store.write(
            BootstrapMetadata(
                wrapped_dek_b64=_b64(wrapped),
                salt_b64=_b64(self._random_salt()),
                mode=WrapMode.OS,
                security_level=self._security_level_provider(),
            )
        )

    def lock(self) -> None:
        self._vault.lock()

    def dek_provider(self) -> Callable[[], bytes]:
        """A late-binding accessor for the DEK; raises while locked."""
        return self._vault.dek

    def _random_salt(self) -> bytes:
        return secrets.token_bytes(self._salt_size)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s)
