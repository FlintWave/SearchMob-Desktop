"""On-device spell / phonetic query corrector.

Port of the Android `OnDeviceSpellCorrector`: a fully local "did you mean" for search queries. For
each whitespace token it generates candidates two ways -- words that sound alike (Double Metaphone)
and words within a small edit distance of the same length -- then ranks survivors by a blend of
Jaro-Winkler similarity and log frequency weight. Tokens already in the dictionary, too short, or
not plain lowercase ASCII are left untouched, so numbers, punctuation, and other scripts pass
through unchanged.

The public `suggest` entry point never raises: any failure (including a missing dictionary)
collapses to `None`, meaning "no suggestion".
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from math import log
from typing import Protocol

from searchmob_desktop.engines.correct.dictionary import Dictionary
from searchmob_desktop.engines.correct.phonetics import phonetic_codes
from searchmob_desktop.engines.correct.string_metrics import jaro_winkler, osa_distance

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Correction:
    """A suggested rewrite of a query and the confidence in it (lowest token similarity)."""

    corrected: str
    confidence: float


class SpellCorrector(Protocol):
    """Anything that can offer a correction for a query, or `None` for "looks fine"."""

    def suggest(self, query: str) -> Correction | None: ...


class NoopSpellCorrector:
    """A corrector that never suggests anything (used when correction is disabled)."""

    def suggest(self, query: str) -> Correction | None:
        """Always return `None`."""
        return None


class OnDeviceSpellCorrector:
    """Local spell corrector backed by a lazily-resolved `Dictionary`."""

    def __init__(
        self,
        dictionary: Callable[[], Dictionary | None],
        min_term_length: int = 3,
        max_edits: int = 2,
        similarity_threshold: float = 0.86,
    ) -> None:
        self._dictionary = dictionary
        self._min_term_length = min_term_length
        self._max_edits = max_edits
        self._similarity_threshold = similarity_threshold

    def suggest(self, query: str) -> Correction | None:
        """Suggest a corrected query, or `None` if nothing is worth changing. Never raises."""
        try:
            return self._correct(query)
        except Exception:
            return None

    def _correct(self, query: str) -> Correction | None:
        dictionary = self._dictionary()
        if dictionary is None:
            return None

        trimmed = query.strip()
        if not trimmed:
            return None

        tokens = _WHITESPACE.split(trimmed)
        changed = False
        min_confidence = 1.0
        rebuilt: list[str] = []

        for token in tokens:
            best = self._best_candidate(token.lower(), dictionary)
            if best is None:
                rebuilt.append(token)
            else:
                word, similarity = best
                changed = True
                min_confidence = min(min_confidence, similarity)
                rebuilt.append(word)

        if not changed:
            return None

        corrected = " ".join(rebuilt)
        if corrected.lower() == trimmed.lower():
            return None

        return Correction(corrected, min_confidence)

    def _best_candidate(self, token: str, dictionary: Dictionary) -> tuple[str, float] | None:
        if len(token) < self._min_term_length:
            return None
        if not all("a" <= ch <= "z" for ch in token):
            return None
        if dictionary.contains(token):
            return None

        candidates: set[str] = set()
        for code in phonetic_codes(token):
            candidates.update(dictionary.phonetic(code))
        for word in dictionary.near_length(len(token), self._max_edits):
            if (
                word
                and word[0] == token[0]
                and osa_distance(token, word, self._max_edits) <= self._max_edits
            ):
                candidates.add(word)

        if not candidates:
            return None

        best: str | None = None
        best_score = 0.0
        best_similarity = 0.0
        for candidate in candidates:
            if candidate == token:
                continue
            similarity = jaro_winkler(token, candidate)
            if similarity < self._similarity_threshold:
                continue
            score = similarity * log(max(dictionary.weight(candidate), 1) + 1.0)
            if score > best_score:
                best_score = score
                best = candidate
                best_similarity = similarity

        if best is None:
            return None
        return best, best_similarity
