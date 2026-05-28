"""In-memory holder for the unwrapped DEK.

The DEK lives only here while the vault is unlocked. `zero()` wipes the bytes so a locked vault
leaves no plaintext key resident. The DEK is never written to disk in unwrapped form.

Mirrors `org.searchmob.data.crypto.DekHolder` + `org.searchmob.data.Vault` from the Android side.
We use `bytearray` (mutable) instead of `bytes` so the bytes can actually be overwritten in place.
"""

from __future__ import annotations


class Vault:
    """Unlock/lock state for the DEK.

    While unlocked, `dek()` returns the live key. After `zero()` the holder is cleared and the
    underlying buffer has been overwritten with zeros so a process memory dump cannot recover it.
    Calling `dek()` while locked raises `RuntimeError`.
    """

    def __init__(self) -> None:
        self._bytes: bytearray | None = None

    @property
    def is_unlocked(self) -> bool:
        return self._bytes is not None

    def unlock(self, dek: bytes) -> None:
        """Place the DEK in the vault. Stored as a mutable `bytearray` for in-place wiping."""
        # Copy into a bytearray we own so we can overwrite it on lock.
        self._bytes = bytearray(dek)

    def dek(self) -> bytes:
        """Return the live DEK bytes (read-only copy). Raises while locked."""
        if self._bytes is None:
            raise RuntimeError("vault is locked: DEK not present in memory")
        # Return an immutable copy so external code cannot scribble in our buffer.
        return bytes(self._bytes)

    def zero(self) -> None:
        """Overwrite the DEK bytes with zeros and drop the reference."""
        if self._bytes is not None:
            for i in range(len(self._bytes)):
                self._bytes[i] = 0
            self._bytes = None

    # Kept as an alias for the Android `Vault.lock()` naming.
    def lock(self) -> None:
        self.zero()
