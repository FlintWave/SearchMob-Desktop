"""Config/data files are written owner-only (0600) on POSIX."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from searchmob_desktop.prefs import JsonPreferencesStore, UserPreferences

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")


def test_saved_prefs_are_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "prefs.json"
    JsonPreferencesStore(path=path).save(UserPreferences())
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, oct(mode)
