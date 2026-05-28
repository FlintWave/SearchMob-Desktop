"""Encrypted preferences storage.

`EncryptedPreferences` holds a `dict[str, str]` (engine config + BYO API keys + storage toggles)
AES-256-GCM-encrypted with the DEK on disk. On-disk form is always ciphertext; a tampered or
malformed-but-authenticated blob decodes to `{}` rather than raising, matching the audit-fixed
behavior on the Android side.
"""

from searchmob_desktop.data.prefs.encrypted_prefs import EncryptedPreferences

__all__ = ["EncryptedPreferences"]
