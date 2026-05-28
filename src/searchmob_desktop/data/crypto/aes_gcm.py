"""AES-256-GCM authenticated encryption.

Output blob is `nonce (12 bytes) || ciphertext+tag (16-byte tag appended by the underlying AEAD)`.
`decrypt` returns `None` on tag mismatch / truncation / wrong key instead of raising, so callers
(prefs codec, DEK wrappers) can degrade gracefully without leaking timing or stack traces.

Mirrors `org.searchmob.data.crypto.AesGcm` from the Android module.
"""

from __future__ import annotations

import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LENGTH = 12


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Returns `nonce || ciphertext+tag`.

    A fresh 12-byte random nonce is drawn from `secrets.token_bytes` (the OS CSPRNG) for every
    call, so two encrypts of the same plaintext under the same key produce different blobs.
    """
    nonce = secrets.token_bytes(_NONCE_LENGTH)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, associated_data=None)


def decrypt(key: bytes, blob: bytes) -> bytes | None:
    """Decrypt a blob produced by `encrypt`. Returns `None` on auth failure or truncation.

    Never raises: a tampered byte, a wrong key, an empty/short blob all map to `None` so the
    caller (prefs, history suggest, DEK unwrap) can fail soft rather than crash. This matches the
    Android contract where the Kotlin `decrypt` catches `GeneralSecurityException` /
    `IndexOutOfBoundsException` and returns `null`.
    """
    if len(blob) < _NONCE_LENGTH:
        return None
    nonce = blob[:_NONCE_LENGTH]
    ciphertext = blob[_NONCE_LENGTH:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
    except InvalidTag:
        return None
    except ValueError:
        # Wrong key length or other low-level rejection; treat as auth failure for the same reason.
        return None
