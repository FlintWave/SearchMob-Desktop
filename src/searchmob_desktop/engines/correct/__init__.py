"""On-device spell / phonetic query correction (local "did you mean").

Ports the Android corrector to pure Python: phonetic + edit-distance candidate generation ranked by
similarity and frequency, backed by a bundled word list and optionally the user's own history. No
network I/O; the public API fails soft.
"""

from __future__ import annotations

from searchmob_desktop.engines.correct.corrector import (
    Correction,
    NoopSpellCorrector,
    OnDeviceSpellCorrector,
    SpellCorrector,
)
from searchmob_desktop.engines.correct.dictionary import Dictionary
from searchmob_desktop.engines.correct.loader import AssetDictionaryLoader
from searchmob_desktop.engines.correct.phonetics import phonetic_codes
from searchmob_desktop.engines.correct.service import start_background_corrector
from searchmob_desktop.engines.correct.string_metrics import jaro_winkler, osa_distance

__all__ = [
    "AssetDictionaryLoader",
    "Correction",
    "Dictionary",
    "NoopSpellCorrector",
    "OnDeviceSpellCorrector",
    "SpellCorrector",
    "jaro_winkler",
    "osa_distance",
    "phonetic_codes",
    "start_background_corrector",
]
