"""Phonetic encoding used to bucket similar-sounding words.

A thin wrapper over Double Metaphone. The exact same function encodes both dictionary words (at
index time) and query terms (at lookup time), so words that sound alike land in the same bucket and
can be proposed as corrections even when their spelling differs substantially (e.g. "fone" and
"phone").
"""

from __future__ import annotations

# Double Metaphone is vendored under `_metaphone` (the upstream `metaphone` package is sdist-only,
# which Briefcase's macOS/AppImage packaging rejects). The vendored code is untyped; mypy treats it
# as `Any` via the per-module override in pyproject.
from searchmob_desktop.engines.correct._metaphone import doublemetaphone


def phonetic_codes(term: str) -> list[str]:
    """Return the Double Metaphone codes for `term`.

    The list holds the primary code (when non-empty) followed by the alternate code (when non-empty
    and different from the primary). Either or both may be absent for input that has no phonetic
    representation, in which case the list is empty.
    """
    primary, alternate = doublemetaphone(term)
    codes: list[str] = []
    if primary:
        codes.append(primary)
    if alternate and alternate != primary:
        codes.append(alternate)
    return codes
