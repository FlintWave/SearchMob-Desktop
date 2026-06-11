"""The app version lives in two places that MUST agree: `src/searchmob_desktop/version.py` (the
single source of truth, read by hatchling and the in-app update check) and the `[tool.briefcase]`
`version` in `pyproject.toml` (mirrored there because Briefcase resolves a PEP 621 dynamic version
by running the build backend in an isolated env, which is wasteful in CI).

If they drift, the installers Briefcase builds carry a different version than the app reports, so a
release can ship packages labelled with the previous version and Linux package managers refuse the
upgrade. This test fails the build when that happens, so the two can never silently diverge again.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from searchmob_desktop.version import __version__

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_briefcase_version_matches_version_py() -> None:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    briefcase_version = data["tool"]["briefcase"]["version"]
    assert briefcase_version == __version__, (
        f"pyproject [tool.briefcase] version {briefcase_version!r} != "
        f"version.py {__version__!r}; bump both together at release time."
    )
