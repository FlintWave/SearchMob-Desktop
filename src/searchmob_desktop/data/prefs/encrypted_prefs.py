"""AES-GCM-encrypted preferences (`dict[str, str]`).

The codec mirrors `EncryptedPreferencesCodec.kt`. It encrypts a JSON-serialized prefs map with the
DEK and writes the resulting `nonce || ciphertext+tag` blob to disk. On decode:

  - GCM auth failure (tampered byte / wrong key) -> `{}`.
  - Authenticated-but-malformed JSON -> `{}` (audit fix: the original Android codec used to leak
    a `SerializationException` here).
  - Empty file -> `{}`.

The DEK is fetched through a callable so a locked vault correctly fails (the provider raises) at
the read/write boundary rather than capturing a stale key when the codec is constructed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from searchmob_desktop.data.crypto.aes_gcm import decrypt, encrypt
from searchmob_desktop.fsperms import restrict_dir, restrict_file


class EncryptedPreferences:
    """A small encrypted key/value store backed by a single file.

    `dek_provider` is called once per read or write; it should raise while the vault is locked.
    """

    def __init__(self, file_path: Path, dek_provider: Callable[[], bytes]) -> None:
        self._path = file_path
        self._dek_provider = dek_provider

    @property
    def path(self) -> Path:
        return self._path

    def encode(self, values: dict[str, str]) -> bytes:
        """Encrypt a prefs map to its on-disk form."""
        plaintext = json.dumps(values, sort_keys=True).encode("utf-8")
        return encrypt(self._dek_provider(), plaintext)

    def decode(self, blob: bytes) -> dict[str, str]:
        """Decrypt the on-disk form back to a prefs map. Fail-soft to `{}`."""
        if not blob:
            return {}
        plaintext = decrypt(self._dek_provider(), blob)
        if plaintext is None:
            return {}
        try:
            decoded = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(decoded, dict):
            return {}
        # Coerce to dict[str, str]; drop any non-string keys/values rather than raising.
        return {
            str(k): str(v) for k, v in decoded.items() if isinstance(v, str | int | float | bool)
        }

    def read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return self.decode(self._path.read_bytes())

    def write(self, values: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        restrict_dir(self._path.parent)
        self._path.write_bytes(self.encode(values))
        restrict_file(self._path)

    def get(self, key: str) -> str | None:
        return self.read().get(key)

    def put(self, key: str, value: str) -> None:
        data = self.read()
        data[key] = value
        self.write(data)

    def remove(self, key: str) -> None:
        data = self.read()
        if key in data:
            del data[key]
            self.write(data)

    def clear(self) -> None:
        self.write({})
