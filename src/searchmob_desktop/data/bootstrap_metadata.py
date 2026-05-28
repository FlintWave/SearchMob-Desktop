"""Unencrypted bootstrap metadata that lets a later run unwrap the DEK.

It contains only the *wrapped* (encrypted) DEK, the random salt, the wrap mode, the achieved
security level (informational), and the KDF parameters used when in passphrase mode. The plaintext
DEK and the user's passphrase are NEVER written here. This file is deliberately plaintext: nothing
in it reveals user data, and all of it is needed before the DEK is available.

The `LEGACY_KDF_*` constants pin the values that were live BEFORE the KDF fields were added to the
schema, so a blob written by an older build (missing the fields) deserializes with those values.
Do NOT repoint these at the current `Argon2idKdf.DEFAULT_*`: they must stay fixed so a future
tuning never bricks an existing zero-knowledge vault.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum

# The Argon2id parameters that were live before the KDF fields existed on this schema.
# Metadata missing those fields predates them, so it must unlock with these exact values.
# Pin them as fixed integers; do NOT chase the live `Argon2idKdf.DEFAULT_*`.
LEGACY_KDF_ALGORITHM = "argon2id"
LEGACY_KDF_ITERATIONS = 4
LEGACY_KDF_MEMORY_KIB = 128 * 1024
LEGACY_KDF_PARALLELISM = 1


class WrapMode(StrEnum):
    """How the DEK is wrapped."""

    OS = "OS"
    PASSPHRASE = "PASSPHRASE"


@dataclass(frozen=True)
class BootstrapMetadata:
    """Persisted JSON state needed to bootstrap the vault on a later run.

    `wrapped_dek_b64` is the base64-encoded `nonce || ciphertext+tag` of the DEK under the KEK.
    `salt_b64` is the random salt; in passphrase mode it feeds the Argon2id KDF, in OS mode it is
    written for symmetry and not used to derive a key.
    `security_level` is informational (`"os"` for the keyring wrap, `"file-fallback"` when the
    keyring backend was unavailable and a 0600 file was used, `"passphrase"` in zero-knowledge
    mode). The KDF fields are unused in OS mode.
    """

    wrapped_dek_b64: str
    salt_b64: str
    mode: WrapMode
    security_level: str = "os"
    kdf_algorithm: str = LEGACY_KDF_ALGORITHM
    kdf_iterations: int = LEGACY_KDF_ITERATIONS
    kdf_memory_kib: int = LEGACY_KDF_MEMORY_KIB
    kdf_parallelism: int = LEGACY_KDF_PARALLELISM

    def to_json(self) -> str:
        data = asdict(self)
        data["mode"] = self.mode.value
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> BootstrapMetadata:
        raw = json.loads(text)
        # Any field missing from `raw` falls back to the dataclass default, which for KDF fields
        # is the LEGACY_* constant. This is load-bearing: an older blob without the KDF fields
        # must unlock with the legacy params, not the live `Argon2idKdf.DEFAULT_*`.
        return cls(
            wrapped_dek_b64=raw["wrapped_dek_b64"],
            salt_b64=raw["salt_b64"],
            mode=WrapMode(raw["mode"]),
            security_level=raw.get("security_level", "os"),
            kdf_algorithm=raw.get("kdf_algorithm", LEGACY_KDF_ALGORITHM),
            kdf_iterations=raw.get("kdf_iterations", LEGACY_KDF_ITERATIONS),
            kdf_memory_kib=raw.get("kdf_memory_kib", LEGACY_KDF_MEMORY_KIB),
            kdf_parallelism=raw.get("kdf_parallelism", LEGACY_KDF_PARALLELISM),
        )
