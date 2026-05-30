"""OS-keyring-backed key-encryption-key (KEK) store.

On the desktop there is no Android Keystore equivalent, so the KEK is a 32-byte random value held
in the OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service / kwallet). On
first call we generate it; on later calls we read it back. The keyring stores strings, so the
bytes are base64-encoded round-trip.

When no keyring backend is available (`NoKeyringError`, or the `fail` backend Linux ships when the
DBus session keyring is missing), we fall back to a file under the user data dir with mode 0600.
A warning is logged. The fallback is functionally weaker than a real keyring (a process running
as the same user can read the file), so it is documented as such; callers can switch to passphrase
mode at any time to get zero-knowledge protection.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import warnings
from pathlib import Path

import keyring
from keyring.errors import KeyringError, NoKeyringError

_log = logging.getLogger(__name__)

DEFAULT_SERVICE = "org.searchmob.desktop"
DEFAULT_ACCOUNT = "kek"
KEK_SIZE_BYTES = 32


class KeyringKekStore:
    """Loads (or generates + persists) the KEK from the OS keyring.

    `keyring_module` is injectable so tests can swap an in-memory backend without touching the
    user's real keyring. `fallback_file_path`, if set, is where the file-based KEK lives when no
    keyring backend can be reached; it defaults to `<user-data-dir>/keyring-fallback.kek`.
    """

    def __init__(
        self,
        service: str = DEFAULT_SERVICE,
        account: str = DEFAULT_ACCOUNT,
        keyring_module: object = keyring,
        fallback_file_path: Path | None = None,
    ) -> None:
        self._service = service
        self._account = account
        self._keyring = keyring_module
        self._fallback_path = fallback_file_path

    def load(self) -> bytes:
        """Return the KEK bytes, generating + persisting on first call.

        If the OS keyring is unreachable, fall back to a 0600 file and warn.
        """
        try:
            existing = self._keyring.get_password(self._service, self._account)  # type: ignore[attr-defined]
            if existing:
                return base64.b64decode(existing)
            fresh = secrets.token_bytes(KEK_SIZE_BYTES)
            self._keyring.set_password(  # type: ignore[attr-defined]
                self._service, self._account, base64.b64encode(fresh).decode("ascii")
            )
            return fresh
        except NoKeyringError:
            return self._load_from_fallback_file()
        except KeyringError as exc:
            _log.warning("keyring unavailable (%s); falling back to file-based KEK", exc)
            return self._load_from_fallback_file()

    def candidate_keks(self) -> list[bytes]:
        """Return every KEK that could currently decrypt a DEK we wrapped, in preference order.

        `load()` picks a single source (keyring first, file second) and may *create* one, but the
        DEK on disk could have been wrapped with the other source if keyring availability changed
        between wrap and unwrap (e.g. a vault created when the session keyring was missing, opened
        later when it is present). So unwrap must try both. This method only *reads* what already
        exists; it never generates or stores a KEK, so calling it has no side effects.
        """
        out: list[bytes] = []
        try:
            existing = self._keyring.get_password(self._service, self._account)  # type: ignore[attr-defined]
            if existing:
                out.append(base64.b64decode(existing))
        except (NoKeyringError, KeyringError):
            pass
        if self._fallback_path is not None and self._fallback_path.exists():
            try:
                out.append(self._fallback_path.read_bytes())
            except OSError:
                pass
        # Deduplicate while preserving order (the two sources can hold the same bytes).
        unique: list[bytes] = []
        for kek in out:
            if kek not in unique:
                unique.append(kek)
        return unique

    def clear(self) -> None:
        """Remove the KEK from the keyring (and the fallback file if it exists).

        Used when enabling zero-knowledge mode: the keyring wrap is no longer the wrapper of
        record, so the KEK must not linger.
        """
        try:
            self._keyring.delete_password(self._service, self._account)  # type: ignore[attr-defined]
        except (NoKeyringError, KeyringError):
            # No backend, or the entry was already gone; either way there is nothing left to clear.
            pass
        if self._fallback_path is not None and self._fallback_path.exists():
            self._fallback_path.unlink()

    def _load_from_fallback_file(self) -> bytes:
        path = self._fallback_path
        if path is None:
            raise RuntimeError(
                "OS keyring is unavailable and no fallback path was configured. "
                "Pass `fallback_file_path` to KeyringKekStore."
            )
        if path.exists():
            return path.read_bytes()
        warnings.warn(
            "OS keyring unavailable; storing the KEK in a 0600 file. A process running as the "
            "same user can read it. Switch to passphrase mode for zero-knowledge protection.",
            stacklevel=2,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = secrets.token_bytes(KEK_SIZE_BYTES)
        # Create the file with 0600 atomically: open with O_CREAT|O_EXCL and an explicit mode.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, fresh)
        finally:
            os.close(fd)
        return fresh
