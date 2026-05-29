"""Best-effort owner-only permissions for config/data files written by the app.

On POSIX, config and data files are chmod'd to 0600 (and their directories to 0700) so other local
accounts cannot read the user's preferences, the wrapped-DEK metadata, or the encrypted blobs. On
platforms where chmod is meaningless (Windows) this is a harmless no-op; all errors are swallowed
so a permissions tweak can never break a save.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def restrict_file(path: Path) -> None:
    """chmod a file to 0600 (owner read/write only). Best-effort."""
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def restrict_dir(path: Path) -> None:
    """chmod a directory to 0700 (owner only). Best-effort."""
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
