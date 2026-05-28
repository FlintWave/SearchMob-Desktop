"""EncryptedPreferences round-trip + fail-soft coverage."""

from __future__ import annotations

import secrets
from pathlib import Path

from searchmob_desktop.data.crypto.aes_gcm import encrypt
from searchmob_desktop.data.prefs.encrypted_prefs import EncryptedPreferences


def test_round_trip(tmp_path: Path) -> None:
    dek = secrets.token_bytes(32)
    prefs = EncryptedPreferences(tmp_path / "prefs.enc", lambda: dek)
    prefs.write({"engine.duckduckgo.enabled": "true", "apiKey.brave": "secret"})
    assert prefs.read() == {
        "engine.duckduckgo.enabled": "true",
        "apiKey.brave": "secret",
    }


def test_tampered_byte_degrades_to_empty(tmp_path: Path) -> None:
    dek = secrets.token_bytes(32)
    prefs = EncryptedPreferences(tmp_path / "prefs.enc", lambda: dek)
    prefs.write({"k": "v"})
    blob = bytearray(prefs.path.read_bytes())
    blob[15] ^= 0x01  # flip a ciphertext byte
    prefs.path.write_bytes(bytes(blob))
    # Tag fails -> empty map; no exception escapes.
    assert prefs.read() == {}


def test_malformed_but_authenticated_json_degrades_to_empty(tmp_path: Path) -> None:
    # Encrypt non-JSON plaintext under the same DEK so the auth tag is valid but JSON parsing
    # fails. The codec must degrade to {} (this was the audit fix on Android).
    dek = secrets.token_bytes(32)
    blob = encrypt(dek, b"not valid json at all { [ ")
    path = tmp_path / "prefs.enc"
    path.write_bytes(blob)
    prefs = EncryptedPreferences(path, lambda: dek)
    assert prefs.read() == {}


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    dek = secrets.token_bytes(32)
    path = tmp_path / "prefs.enc"
    path.write_bytes(b"")
    prefs = EncryptedPreferences(path, lambda: dek)
    assert prefs.read() == {}


def test_put_get_remove_clear(tmp_path: Path) -> None:
    dek = secrets.token_bytes(32)
    prefs = EncryptedPreferences(tmp_path / "prefs.enc", lambda: dek)
    prefs.put("a", "1")
    prefs.put("b", "2")
    assert prefs.get("a") == "1"
    prefs.remove("a")
    assert prefs.get("a") is None
    assert prefs.read() == {"b": "2"}
    prefs.clear()
    assert prefs.read() == {}
