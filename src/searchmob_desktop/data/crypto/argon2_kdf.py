"""Argon2id key-derivation for the zero-knowledge passphrase mode.

Uses `argon2-cffi`'s low-level `hash_secret_raw`. The live defaults follow the hardened Android
profile (t=3, m=64 MiB, p=1, 32-byte output) and are recorded into bootstrap metadata so a future
tuning never bricks an existing vault: unlocks always re-derive with the STORED params.

The passphrase is taken as `bytes` (typically a `bytearray` from `getpass`); callers should pass a
mutable buffer they then zero. We deliberately do NOT keep a reference past `derive` so the only
copy left is the one the caller owns.
"""

from __future__ import annotations

from argon2 import exceptions as argon2_exceptions
from argon2.low_level import Type, hash_secret_raw


class KdfError(Exception):
    """Raised when key derivation cannot complete (e.g. native OOM allocating the memory cost).

    Surfaced as a clean domain error so a memory-constrained machine does not crash the process
    mid-unlock. Never includes the passphrase or its bytes in the message.
    """


class Argon2idKdf:
    """Argon2id with caller-tunable cost parameters. RFC 9106 second profile by default.

    The cost is paid only on explicit unlock / passphrase-set, never in the hot search path.
    """

    ALGORITHM = "argon2id"
    DEFAULT_ITERATIONS = 3
    DEFAULT_MEMORY_KIB = 64 * 1024
    DEFAULT_PARALLELISM = 1

    def __init__(
        self,
        iterations: int = DEFAULT_ITERATIONS,
        memory_kib: int = DEFAULT_MEMORY_KIB,
        parallelism: int = DEFAULT_PARALLELISM,
    ) -> None:
        self.iterations = iterations
        self.memory_kib = memory_kib
        self.parallelism = parallelism

    def derive(self, passphrase: bytes | bytearray, salt: bytes, length: int = 32) -> bytes:
        """Derive a `length`-byte key from `passphrase` + `salt`.

        `passphrase` should be the UTF-8 bytes of the user's passphrase. Pass a `bytearray` so you
        can zero it after this call returns.
        """
        try:
            return hash_secret_raw(
                secret=bytes(passphrase),
                salt=salt,
                time_cost=self.iterations,
                memory_cost=self.memory_kib,
                parallelism=self.parallelism,
                hash_len=length,
                type=Type.ID,
            )
        except argon2_exceptions.HashingError as exc:
            # argon2-cffi wraps native OOM / parameter-rejection as HashingError. Surface a clean
            # domain failure; never include the passphrase or salt in the message.
            raise KdfError("argon2id key derivation failed") from exc
        except MemoryError as exc:
            raise KdfError("argon2id key derivation failed: insufficient memory") from exc
