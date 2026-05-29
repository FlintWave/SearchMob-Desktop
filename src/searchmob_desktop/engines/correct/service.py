"""Build a corrector whose dictionary loads in the background.

Loading the bundled dictionary parses ~60k lines and builds the phonetic index, which is too heavy
to do on a request (or on the GUI thread). `start_background_corrector` kicks the load off on a
daemon thread and hands back an `OnDeviceSpellCorrector` bound to the loader's cache: it simply
returns no suggestion until the dictionary is ready, then starts correcting. Fully fail-soft.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from searchmob_desktop.engines.correct.corrector import OnDeviceSpellCorrector, SpellCorrector
from searchmob_desktop.engines.correct.loader import AssetDictionaryLoader


def start_background_corrector(
    history_terms: Callable[[], list[str]] = lambda: [],
) -> SpellCorrector:
    """Return a corrector and begin loading its dictionary off-thread.

    `history_terms` is folded into the vocabulary so corrections improve for terms the user has
    actually searched; it is read once when the load runs and any failure is swallowed.
    """
    loader = AssetDictionaryLoader(history_terms=history_terms)

    def _load() -> None:
        try:
            loader.load()
        except Exception:
            # A missing asset or parse error just leaves the corrector quiet; never crash the load.
            pass

    threading.Thread(target=_load, name="searchmob-dict-load", daemon=True).start()
    return OnDeviceSpellCorrector(loader.current)
