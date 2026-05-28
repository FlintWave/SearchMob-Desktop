"""BootstrapMetadata JSON round-trip + legacy-defaults coverage."""

from __future__ import annotations

import json

from searchmob_desktop.data.bootstrap_metadata import (
    LEGACY_KDF_ALGORITHM,
    LEGACY_KDF_ITERATIONS,
    LEGACY_KDF_MEMORY_KIB,
    LEGACY_KDF_PARALLELISM,
    BootstrapMetadata,
    WrapMode,
)


def test_round_trip_json() -> None:
    meta = BootstrapMetadata(
        wrapped_dek_b64="d3JhcHBlZA==",
        salt_b64="c2FsdA==",
        mode=WrapMode.PASSPHRASE,
        security_level="passphrase",
        kdf_algorithm="argon2id",
        kdf_iterations=3,
        kdf_memory_kib=64 * 1024,
        kdf_parallelism=1,
    )
    decoded = BootstrapMetadata.from_json(meta.to_json())
    assert decoded == meta


def test_older_blob_missing_kdf_fields_uses_legacy_defaults() -> None:
    # An older build wrote only the pre-KDF-fields schema. The new deserializer must fill in the
    # LEGACY_* constants, not the current Argon2idKdf defaults, so the vault is still unlockable.
    blob = json.dumps(
        {
            "wrapped_dek_b64": "d3JhcHBlZA==",
            "salt_b64": "c2FsdA==",
            "mode": "PASSPHRASE",
            "security_level": "passphrase",
        }
    )
    decoded = BootstrapMetadata.from_json(blob)
    assert decoded.kdf_algorithm == LEGACY_KDF_ALGORITHM
    assert decoded.kdf_iterations == LEGACY_KDF_ITERATIONS
    assert decoded.kdf_memory_kib == LEGACY_KDF_MEMORY_KIB
    assert decoded.kdf_parallelism == LEGACY_KDF_PARALLELISM


def test_legacy_values_are_pinned_independent_of_live_defaults() -> None:
    # Sanity: the legacy constants must NOT drift toward the current Argon2idKdf defaults.
    # If a future change re-points LEGACY_* at the live defaults, this catches it.
    assert LEGACY_KDF_ITERATIONS == 4
    assert LEGACY_KDF_MEMORY_KIB == 128 * 1024
    assert LEGACY_KDF_PARALLELISM == 1
    assert LEGACY_KDF_ALGORITHM == "argon2id"
