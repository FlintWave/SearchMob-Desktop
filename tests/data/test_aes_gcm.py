"""AES-256-GCM round-trip + fail-soft + nonce-uniqueness coverage."""

from __future__ import annotations

import secrets

import pytest

from searchmob_desktop.data.crypto.aes_gcm import decrypt, encrypt


def test_round_trip() -> None:
    key = secrets.token_bytes(32)
    plaintext = b"hello searchmob"
    blob = encrypt(key, plaintext)
    assert decrypt(key, blob) == plaintext


def test_flipped_byte_returns_none() -> None:
    key = secrets.token_bytes(32)
    blob = bytearray(encrypt(key, b"payload"))
    # Flip a byte in the ciphertext region (after the 12-byte nonce). GCM must reject the tag.
    blob[20] ^= 0x01
    assert decrypt(key, bytes(blob)) is None


def test_truncated_returns_none() -> None:
    key = secrets.token_bytes(32)
    blob = encrypt(key, b"payload")
    # Cut the tag off the end: GCM must reject.
    assert decrypt(key, blob[:-2]) is None
    # And totally short blob: must not raise.
    assert decrypt(key, b"") is None
    assert decrypt(key, b"abc") is None


def test_wrong_key_returns_none() -> None:
    blob = encrypt(secrets.token_bytes(32), b"payload")
    assert decrypt(secrets.token_bytes(32), blob) is None


def test_nonce_uniqueness_across_many_encrypts() -> None:
    key = secrets.token_bytes(32)
    nonces = {encrypt(key, b"same plaintext")[:12] for _ in range(200)}
    # 200 distinct 12-byte random nonces; the probability of any collision is ~2^-67.
    assert len(nonces) == 200


@pytest.mark.parametrize("plaintext", [b"", b"x", b"a" * 1024])
def test_round_trip_various_sizes(plaintext: bytes) -> None:
    key = secrets.token_bytes(32)
    assert decrypt(key, encrypt(key, plaintext)) == plaintext
