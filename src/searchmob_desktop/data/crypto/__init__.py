"""Encrypted-storage crypto primitives: AES-256-GCM, Argon2id KDF, DEK + KEK wrappers.

These mirror the Android `org.searchmob.data.crypto` package. The contract (not the syntax) is the
locked design: AES-GCM with a 12-byte random nonce prepended to the ciphertext, Argon2id with the
RFC 9106 second profile as the live default and a separate set of LEGACY constants pinned in
`bootstrap_metadata`, and a fail-soft `decrypt` that returns `None` instead of raising on tag
mismatch.
"""

from searchmob_desktop.data.crypto.aes_gcm import decrypt, encrypt
from searchmob_desktop.data.crypto.argon2_kdf import Argon2idKdf, KdfError
from searchmob_desktop.data.crypto.dek import DEK_SIZE_BYTES, random_dek
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import (
    DekWrapper,
    KeyringDekWrapper,
    PassphraseDekWrapper,
    SecretKeyDekWrapper,
)

__all__ = [
    "DEK_SIZE_BYTES",
    "Argon2idKdf",
    "DekWrapper",
    "KdfError",
    "KeyringDekWrapper",
    "KeyringKekStore",
    "PassphraseDekWrapper",
    "SecretKeyDekWrapper",
    "decrypt",
    "encrypt",
    "random_dek",
]
