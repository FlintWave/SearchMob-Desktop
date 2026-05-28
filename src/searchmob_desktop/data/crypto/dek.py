"""Data-Encryption Key generation.

The DEK is a 256-bit random value that protects every at-rest payload (prefs blob, SQLCipher
history DB). It lives only in process memory (see `Vault`); a wrapped copy in
`BootstrapMetadata` is the durable form, encrypted under the KEK.
"""

from __future__ import annotations

import secrets

DEK_SIZE_BYTES = 32


def random_dek() -> bytes:
    """Return a fresh 32-byte DEK from the OS CSPRNG."""
    return secrets.token_bytes(DEK_SIZE_BYTES)
