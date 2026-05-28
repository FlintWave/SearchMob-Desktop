"""Argon2id determinism + parameter sensitivity coverage.

The tests use a deliberately tiny cost profile (t=1, m=16 MiB) so CI stays fast; production
defaults are exercised end-to-end via `test_storage_bootstrap`.
"""

from __future__ import annotations

from searchmob_desktop.data.crypto.argon2_kdf import Argon2idKdf

# Cheap profile so the per-test cost is sub-100ms on commodity CI.
KDF = Argon2idKdf(iterations=1, memory_kib=16 * 1024, parallelism=1)


def test_deterministic_for_fixed_inputs() -> None:
    salt = b"\x00" * 16
    a = KDF.derive(b"hunter2", salt)
    b = KDF.derive(b"hunter2", salt)
    assert a == b
    assert len(a) == 32


def test_different_passphrase_yields_different_key() -> None:
    salt = b"\x01" * 16
    a = KDF.derive(b"hunter2", salt)
    b = KDF.derive(b"hunter3", salt)
    assert a != b


def test_different_salt_yields_different_key() -> None:
    a = KDF.derive(b"hunter2", b"\x00" * 16)
    b = KDF.derive(b"hunter2", b"\x01" * 16)
    assert a != b


def test_accepts_bytearray_passphrase() -> None:
    # The contract is that callers pass a `bytearray` they can zero. `derive` should accept it.
    passphrase = bytearray(b"hunter2")
    out = KDF.derive(passphrase, b"\x02" * 16)
    assert len(out) == 32
