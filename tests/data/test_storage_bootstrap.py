"""StorageBootstrap lifecycle: first-run, unlock, enable/disable zero-knowledge.

Uses `SecretKeyDekWrapper` with a fixed in-test KEK in place of the keyring wrapper so the tests
do not touch the user's real OS keyring, and Argon2id at a cheap profile so the cost is sub-100ms
per derivation.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from searchmob_desktop.data.bootstrap_metadata import WrapMode
from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore
from searchmob_desktop.data.crypto.argon2_kdf import Argon2idKdf
from searchmob_desktop.data.crypto.wrap import SecretKeyDekWrapper
from searchmob_desktop.data.storage_bootstrap import StorageBootstrap

# Cheap KDF so per-derivation cost is small enough for fast CI.
TEST_KDF = Argon2idKdf(iterations=1, memory_kib=16 * 1024, parallelism=1)


def _build(tmp_path: Path) -> tuple[StorageBootstrap, list[bool]]:
    """Build a StorageBootstrap with an in-test KEK wrapper. Returns the bootstrap + a `cleared`
    flag list the test can inspect (it captures the keyring_clearer call).
    """
    cleared: list[bool] = []
    metadata_store = BootstrapMetadataStore(tmp_path / "bootstrap.json")
    kek = secrets.token_bytes(32)
    wrapper = SecretKeyDekWrapper(kek)
    bootstrap = StorageBootstrap(
        metadata_store=metadata_store,
        keyring_wrapper=wrapper,
        kdf=TEST_KDF,
        keyring_clearer=lambda: cleared.append(True),
    )
    return bootstrap, cleared


def test_first_run_then_unlock_keyring(tmp_path: Path) -> None:
    bootstrap, _ = _build(tmp_path)
    assert bootstrap.mode is None
    bootstrap.first_run()
    assert bootstrap.is_unlocked
    assert bootstrap.mode == WrapMode.OS

    # Simulate a process restart: a fresh StorageBootstrap reading the same metadata file.
    bootstrap2, _ = _build(tmp_path)
    # The new bootstrap has its own random KEK, so it cannot unwrap. Replace its wrapper with the
    # original wrapper to model "same OS keyring, different process" instead.
    # Rebuild manually so we keep the original KEK around for the second instance.
    kek_b = bootstrap._keyring_wrapper
    metadata_store = BootstrapMetadataStore(tmp_path / "bootstrap.json")
    bootstrap2 = StorageBootstrap(
        metadata_store=metadata_store,
        keyring_wrapper=kek_b,
        kdf=TEST_KDF,
    )
    assert bootstrap2.mode == WrapMode.OS
    assert not bootstrap2.is_unlocked
    assert bootstrap2.unlock_keyring() is True
    assert bootstrap2.is_unlocked
    # The DEK on the second instance must match what `first_run` set on the first.
    assert bootstrap2.vault.dek() == bootstrap.vault.dek()


def test_enable_zero_knowledge_records_current_kdf_params(tmp_path: Path) -> None:
    bootstrap, cleared = _build(tmp_path)
    bootstrap.first_run()

    passphrase = bytearray(b"correct horse battery staple")
    bootstrap.enable_zero_knowledge(passphrase, warning_confirmed=True)

    meta = bootstrap.metadata_store.read()
    assert meta is not None
    assert meta.mode == WrapMode.PASSPHRASE
    # The current (test) KDF params, NOT the LEGACY_* defaults, must be recorded.
    assert meta.kdf_iterations == TEST_KDF.iterations
    assert meta.kdf_memory_kib == TEST_KDF.memory_kib
    assert meta.kdf_parallelism == TEST_KDF.parallelism
    assert meta.kdf_algorithm == TEST_KDF.ALGORITHM
    # The keyring clearer was called: the keyring is no longer the wrapper of record.
    assert cleared == [True]


def test_unlock_with_passphrase_uses_stored_params(tmp_path: Path) -> None:
    bootstrap, _ = _build(tmp_path)
    bootstrap.first_run()
    expected_dek = bootstrap.vault.dek()

    bootstrap.enable_zero_knowledge(bytearray(b"hunter2"), warning_confirmed=True)
    bootstrap.lock()
    assert not bootstrap.is_unlocked

    # Fresh bootstrap with a DIFFERENT live KDF (incompatible params) to prove the stored params
    # are what unlock actually uses.
    different_live_kdf = Argon2idKdf(iterations=99, memory_kib=32 * 1024, parallelism=2)
    bootstrap2 = StorageBootstrap(
        metadata_store=BootstrapMetadataStore(tmp_path / "bootstrap.json"),
        keyring_wrapper=SecretKeyDekWrapper(secrets.token_bytes(32)),
        kdf=different_live_kdf,
    )
    assert bootstrap2.unlock_with_passphrase(bytearray(b"hunter2")) is True
    assert bootstrap2.vault.dek() == expected_dek


def test_wrong_passphrase_returns_false_no_raise(tmp_path: Path) -> None:
    bootstrap, _ = _build(tmp_path)
    bootstrap.first_run()
    bootstrap.enable_zero_knowledge(bytearray(b"hunter2"), warning_confirmed=True)
    bootstrap.lock()
    assert bootstrap.unlock_with_passphrase(bytearray(b"WRONG")) is False
    assert not bootstrap.is_unlocked


def test_refuses_to_enable_without_warning_confirmed(tmp_path: Path) -> None:
    bootstrap, _ = _build(tmp_path)
    bootstrap.first_run()
    with pytest.raises(ValueError):
        bootstrap.enable_zero_knowledge(bytearray(b"hunter2"), warning_confirmed=False)


def test_disable_zero_knowledge_regenerates_keyring_wrap(tmp_path: Path) -> None:
    bootstrap, _ = _build(tmp_path)
    bootstrap.first_run()
    expected_dek = bootstrap.vault.dek()

    bootstrap.enable_zero_knowledge(bytearray(b"hunter2"), warning_confirmed=True)
    # disable_zero_knowledge needs the vault unlocked; it stays unlocked after enable.
    bootstrap.disable_zero_knowledge()
    meta = bootstrap.metadata_store.read()
    assert meta is not None
    assert meta.mode == WrapMode.OS
    # Same DEK survived the mode round-trip.
    assert bootstrap.vault.dek() == expected_dek

    # A fresh instance with the SAME keyring wrapper unlocks via the keyring path again.
    kek_wrapper = bootstrap._keyring_wrapper
    bootstrap2 = StorageBootstrap(
        metadata_store=BootstrapMetadataStore(tmp_path / "bootstrap.json"),
        keyring_wrapper=kek_wrapper,
        kdf=TEST_KDF,
    )
    assert bootstrap2.unlock_keyring() is True
    assert bootstrap2.vault.dek() == expected_dek


def test_locking_zeroes_the_dek(tmp_path: Path) -> None:
    bootstrap, _ = _build(tmp_path)
    bootstrap.first_run()
    assert bootstrap.is_unlocked
    bootstrap.lock()
    assert not bootstrap.is_unlocked
    with pytest.raises(RuntimeError):
        bootstrap.vault.dek()
