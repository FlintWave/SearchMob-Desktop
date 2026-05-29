"""Vendored Double Metaphone (BSD), from the `metaphone` package by Andrew Collins et al.

Vendored because the upstream `metaphone` distribution is sdist-only (no wheel), which Briefcase's
macOS/AppImage packaging rejects. The code is unmodified (`metaphone.py` + `word.py`); see the
adjacent `LICENSE`. We only use `doublemetaphone`.

Upstream: https://github.com/oubiwann/metaphone
"""

from __future__ import annotations

from searchmob_desktop.engines.correct._metaphone.metaphone import doublemetaphone

__all__ = ["doublemetaphone"]
