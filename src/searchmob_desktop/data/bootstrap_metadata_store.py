"""Read/write `BootstrapMetadata` JSON to a file under the platform user-data dir.

Path resolution uses `platformdirs.user_data_dir("SearchMob", "FlintWave")` so the file lives at
the OS-native location (e.g. `~/.local/share/SearchMob` on Linux, `~/Library/Application Support/
SearchMob` on macOS, `%APPDATA%\\SearchMob` on Windows). The file is deliberately plaintext; see
`bootstrap_metadata.py` for why that is safe.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir

from searchmob_desktop.data.bootstrap_metadata import BootstrapMetadata
from searchmob_desktop.fsperms import restrict_dir, restrict_file

FILE_NAME = "searchmob-bootstrap.json"
APP_NAME = "SearchMob"
APP_AUTHOR = "FlintWave"


def default_user_data_dir() -> Path:
    """Return the SearchMob user-data dir (created if missing)."""
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


class BootstrapMetadataStore:
    """JSON file at `<user_data_dir>/searchmob-bootstrap.json` by default."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = default_user_data_dir() / FILE_NAME
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def read(self) -> BootstrapMetadata | None:
        if not self._path.exists():
            return None
        try:
            return BootstrapMetadata.from_json(self._path.read_text(encoding="utf-8"))
        except (ValueError, KeyError):
            # Corrupt or partial; treat the same as "missing" so the caller can re-bootstrap.
            return None

    def write(self, metadata: BootstrapMetadata) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        restrict_dir(self._path.parent)
        self._path.write_text(metadata.to_json(), encoding="utf-8")
        # The metadata holds only the wrapped DEK + salt + KDF params (no plaintext key), but
        # owner-only is still the right default for vault material.
        restrict_file(self._path)

    def delete(self) -> None:
        if self._path.exists():
            self._path.unlink()
