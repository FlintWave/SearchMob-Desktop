"""Dictionary loader for the on-device corrector.

Reads the bundled gzipped word list (`word<TAB>weight` per line) into a `Dictionary`, optionally
augmented with the user's own search history so personal vocabulary (names, project words) becomes
correctable too. History terms are given a high fixed weight so they outrank generic words of
similar shape.

Loading is idempotent and thread-safe behind a simple lock, and history augmentation is wrapped so
a failing history source can never abort dictionary loading. No network I/O is performed.
"""

from __future__ import annotations

import gzip
import importlib.resources as resources
import threading
from collections.abc import Callable

from searchmob_desktop.engines.correct.dictionary import Dictionary

_RESOURCE_PACKAGE = "searchmob_desktop.resources.dict"
_RESOURCE_NAME = "words.txt.gz"


class AssetDictionaryLoader:
    """Builds and caches a `Dictionary` from the bundled asset plus optional history terms."""

    def __init__(
        self,
        asset_path: str | None = None,
        history_terms: Callable[[], list[str]] = lambda: [],
        history_weight: int = 15000,
    ) -> None:
        self._asset_path = asset_path
        self._history_terms = history_terms
        self._history_weight = history_weight
        self._lock = threading.Lock()
        self._cache: Dictionary | None = None

    def current(self) -> Dictionary | None:
        """Return the cached dictionary, or `None` if `load` has not run yet."""
        return self._cache

    def load(self) -> Dictionary:
        """Build (or return the cached) dictionary. Idempotent and thread-safe."""
        with self._lock:
            if self._cache is not None:
                return self._cache
            weights = self._read_weights()
            self._augment_with_history(weights)
            dictionary = Dictionary.build(weights)
            self._cache = dictionary
            return dictionary

    def _read_weights(self) -> dict[str, int]:
        raw = self._read_asset_bytes()
        text = gzip.decompress(raw).decode("utf-8")
        weights: dict[str, int] = {}
        for line in text.splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            word = parts[0]
            if not word:
                continue
            try:
                weight = int(parts[1])
            except ValueError:
                continue
            if weight <= 0:
                continue
            weights[word] = weight
        return weights

    def _read_asset_bytes(self) -> bytes:
        if self._asset_path is not None:
            with open(self._asset_path, "rb") as handle:
                return handle.read()
        resource = resources.files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_NAME)
        with resources.as_file(resource) as path:
            with open(path, "rb") as handle:
                return handle.read()

    def _augment_with_history(self, weights: dict[str, int]) -> None:
        try:
            terms = self._history_terms()
        except Exception:
            return
        for term in terms:
            for sub_term in term.lower().split():
                if len(sub_term) < 2:
                    continue
                if not all("a" <= ch <= "z" for ch in sub_term):
                    continue
                if sub_term in weights:
                    continue
                weights[sub_term] = self._history_weight
