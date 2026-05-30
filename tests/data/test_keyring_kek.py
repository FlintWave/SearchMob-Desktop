"""KeyringKekStore tests with an in-memory keyring + a file-fallback path.

The real OS keyring is not safe to touch in a test (it would write to the user's session
keyring), so we inject a fake `keyring` module that just holds an in-memory dict.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from keyring.errors import NoKeyringError

from searchmob_desktop.data.crypto.keyring_kek import KEK_SIZE_BYTES, KeyringKekStore


class _FakeKeyring:
    """Minimal in-memory keyring stand-in."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        self.store[(service, account)] = password

    def delete_password(self, service: str, account: str) -> None:
        self.store.pop((service, account), None)


class _FailingKeyring:
    """Raises `NoKeyringError` like the `fail` backend does when no daemon is reachable."""

    def get_password(self, service: str, account: str) -> str | None:
        raise NoKeyringError("no backend available")

    def set_password(self, service: str, account: str, password: str) -> None:
        raise NoKeyringError("no backend available")

    def delete_password(self, service: str, account: str) -> None:
        raise NoKeyringError("no backend available")


def test_generate_on_first_call_and_persist() -> None:
    fake = _FakeKeyring()
    store = KeyringKekStore(keyring_module=fake)
    kek1 = store.load()
    kek2 = store.load()
    assert kek1 == kek2
    assert len(kek1) == KEK_SIZE_BYTES
    # Persisted under (service, account).
    assert ("org.searchmob.desktop", "kek") in fake.store


def test_clear_removes_entry() -> None:
    fake = _FakeKeyring()
    store = KeyringKekStore(keyring_module=fake)
    store.load()
    store.clear()
    assert ("org.searchmob.desktop", "kek") not in fake.store
    # Loading again must regenerate.
    kek = store.load()
    assert len(kek) == KEK_SIZE_BYTES


def test_no_keyring_falls_back_to_file(tmp_path: Path) -> None:
    fallback = tmp_path / "kek.bin"
    store = KeyringKekStore(keyring_module=_FailingKeyring(), fallback_file_path=fallback)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        kek1 = store.load()
        assert any("OS keyring unavailable" in str(w.message) for w in caught)
    assert fallback.exists()
    # 0600 mode (owner-only) for the fallback file.
    assert (fallback.stat().st_mode & 0o777) == 0o600
    kek2 = store.load()
    assert kek1 == kek2


def test_candidate_keks_returns_keyring_and_file(tmp_path: Path) -> None:
    fake = _FakeKeyring()
    fb = tmp_path / "fallback.kek"
    store = KeyringKekStore(keyring_module=fake, fallback_file_path=fb)
    # Seed a keyring KEK and a (different) fallback file KEK.
    import base64

    fake.store[("org.searchmob.desktop", "kek")] = base64.b64encode(b"K" * 32).decode("ascii")
    fb.write_bytes(b"F" * 32)
    cands = store.candidate_keks()
    assert b"K" * 32 in cands
    assert b"F" * 32 in cands


def test_unwrap_recovers_dek_wrapped_with_file_kek_after_keyring_flip(tmp_path: Path) -> None:
    """A DEK wrapped with the fallback-file KEK must still unwrap once the keyring holds a different
    KEK (the real-world bug: keyring availability changed between wrap and unwrap)."""
    import base64

    from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper

    fb = tmp_path / "fallback.kek"

    # Wrap while the keyring is UNavailable: load() falls back to the file, generating the file KEK.
    wrap_store = KeyringKekStore(keyring_module=_FailingKeyring(), fallback_file_path=fb)
    dek = b"D" * 32
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        blob = KeyringDekWrapper(wrap_store).wrap(dek)
    file_kek = fb.read_bytes()

    # Later run: keyring is back with a DIFFERENT KEK, so load() would prefer the wrong one.
    fake = _FakeKeyring()
    fake.store[("org.searchmob.desktop", "kek")] = base64.b64encode(b"K" * 32).decode("ascii")
    unlock_store = KeyringKekStore(keyring_module=fake, fallback_file_path=fb)
    assert unlock_store.load() != file_kek  # load() now prefers the keyring KEK

    # Unwrap must still succeed by also trying the file KEK among the candidates.
    assert KeyringDekWrapper(unlock_store).unwrap(blob) == dek
