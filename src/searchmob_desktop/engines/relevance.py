"""Lexical query-match relevance signal blended into the aggregator's RRF ranking.

RRF fuses several engines' rankings, but it trusts each engine's order: with mostly single-engine
results the fused scores are nearly tied (1/60 .. 1/69), so an irrelevant result one engine happened
to rank highly slips into the top. Nothing in the pipeline asks "does this result actually match the
query?".

This module adds that missing signal: a deterministic, on-device lexical match score over the
result's title and snippet (how many of the query's content words appear, weighted toward the title,
with a small exact-phrase bonus). The aggregator multiplies each result's RRF score by a factor
derived from this lexical score, so query-match leads the ranking and engine consensus stays a
secondary signal. No corpus, model, or network: pure string work, identical in spirit to the Kotlin
port in `engine/Relevance.kt`.

The blend is deliberately bounded (a non-matching result keeps `RELEVANCE_BASE` of its RRF weight
rather than zero) so a relevant result phrased differently from the query (e.g. "artificial
intelligence" for the query term "ai") that several engines agree on is demoted, not deleted.
"""

from __future__ import annotations

import re

__all__ = [
    "RELEVANCE_BASE",
    "RELEVANCE_GAIN",
    "blended_score",
    "content_terms",
    "language_affinity",
    "lexical_score",
]

# The blend is DEMOTION-ONLY: the factor is capped at 1.0, so a well-matching result keeps its full
# RRF weight and engine consensus still decides the order among good matches (we never promote a
# keyword-stuffed title over a result several engines agree on). A poorly-matching result is sunk
# toward RELEVANCE_BASE of its RRF weight. With BASE=0.5, GAIN=1.0 a result matching half the query
# terms is already at full weight; only weaker matches are penalized. See test_relevance.py.
RELEVANCE_BASE = 0.5
RELEVANCE_GAIN = 1.0

# Conservative stopword set: function words and generic query modifiers that carry little subject
# intent. Kept short on purpose so the actual subject of a query is never stripped. If a query is
# nothing but stopwords, `content_terms` falls back to all tokens so matching still works.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "is",
        "are",
        "be",
        "do",
        "does",
        "did",
        "how",
        "what",
        "why",
        "when",
        "where",
        "who",
        "which",
        "with",
        "this",
        "that",
        "it",
        "at",
        "by",
        "from",
        "as",
        "your",
        "my",
        "i",
        "vs",
        "into",
        "about",
        "best",
        "top",
        "good",
        "vs.",
        "near",
        "me",
    }
)

# Unicode-aware word tokens (letters/digits in any script), NOT ASCII-only, so the lexical signal
# works for non-Latin queries too (Cyrillic, Greek, Arabic, ...). `\w` excludes the underscore here
# via the `[^\W_]` form. Space-less scripts (CJK) tokenize as one run; finer segmentation is left to
# the localization pass.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# Unicode ranges that count as Latin script (so accented and Vietnamese text is NOT treated as
# "foreign"): Basic Latin + Latin-1 Supplement + Extended-A/B, Latin Extended Additional, and
# Extended-C/D. A letter outside these is from another script (Cyrillic, CJK, Arabic, Greek, ...).
_LATIN_RANGES = ((0x41, 0x24F), (0x1E00, 0x1EFF), (0x2C60, 0x2C7F), (0xA720, 0xA7FF))


def _stem(word: str) -> str:
    """Very light English suffix folding so 'keyboards' matches 'keyboard', 'reviews' 'review'.

    Not a real stemmer: it just trims the commonest inflectional endings on longer words, applied to
    both the query and the document so matching is symmetric. Conservative on length so short words
    (e.g. 'ios', 'css', 'vs') are never mangled. Gated to ASCII since the suffix rules are English;
    non-ASCII words (other languages) pass through untouched, never corrupted. Per-language stemming
    is a future refinement for the localization pass.
    """
    if not word.isascii():
        return word
    if len(word) >= 5:
        if word.endswith("ies"):
            return word[:-3] + "y"
        for suffix in ("ing", "ers"):
            if word.endswith(suffix):
                return word[: -len(suffix)]
    if len(word) >= 4:
        for suffix in ("es", "ed", "er"):
            if word.endswith(suffix):
                return word[: -len(suffix)]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
    return word


def _is_latin(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _LATIN_RANGES)


def _script_of(char: str) -> str:
    """Coarse script bucket for a letter. Language-agnostic: works for whatever the query is in."""
    code = ord(char)
    if _is_latin(char):
        return "latin"
    if 0x0400 <= code <= 0x052F:
        return "cyrillic"
    if 0x0370 <= code <= 0x03FF:
        return "greek"
    if 0x0590 <= code <= 0x05FF:
        return "hebrew"
    if (0x0600 <= code <= 0x06FF) or (0x0750 <= code <= 0x077F):
        return "arabic"
    if 0x0900 <= code <= 0x097F:
        return "devanagari"
    if 0x0E00 <= code <= 0x0E7F:
        return "thai"
    if (
        (0x4E00 <= code <= 0x9FFF)
        or (0x3400 <= code <= 0x4DBF)
        or (0x3040 <= code <= 0x30FF)
        or (0xAC00 <= code <= 0xD7AF)
    ):
        return "cjk"
    return "other"


def _dominant_script(text: str) -> str | None:
    """Most common letter script in `text`, or None when it has no letters (e.g. only digits)."""
    counts: dict[str, int] = {}
    for char in text:
        if char.isalpha():
            script = _script_of(char)
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda s: counts[s])


def language_affinity(query: str, title: str, snippet: str) -> float:
    """1.0 when the result is in the same script as the query, else a demotion factor.

    Script-relative on purpose so this works in any UI/query language, not just English: a result
    dominated by a different script than the query (Cyrillic results for a Latin query, or Latin
    for a CJK query, ...) is almost never what the searcher wanted and is sunk. A query with no
    letters (pure digits/symbols) or a result whose dominant script matches is never penalized.
    Distinguishing languages that share a script (e.g. English vs French) needs real language
    detection and is left to the localization pass; this catches the jarring cross-script case.
    """
    query_script = _dominant_script(query)
    if query_script is None:
        return 1.0
    result_script = _dominant_script(f"{title} {snippet}")
    if result_script is None or result_script == query_script:
        return 1.0
    return 0.4


def content_terms(query: str) -> list[str]:
    """Distinct content tokens of `query` (lowercased, length >= 2, stopwords removed, order kept).

    Falls back to all tokens when every token is a stopword, so a query like "how to" still matches
    on something rather than scoring every result zero.
    """
    tokens = [t for t in _TOKEN.findall(query.lower()) if len(t) >= 2]
    seen: dict[str, None] = {}
    for token in tokens:
        seen.setdefault(token, None)
    distinct = list(seen)
    content = [t for t in distinct if t not in _STOPWORDS]
    return content or distinct


def lexical_score(title: str, snippet: str, terms: list[str]) -> float:
    """How well `title`/`snippet` match `terms`, in [0, 1]. Higher = better query match.

    Combines whole-word coverage (fraction of query terms present anywhere), title coverage (the
    same but title-only, weighted equally because a title hit is a strong relevance signal), and a
    small bonus when the terms appear as a contiguous phrase in the title. Whole-word membership
    (not substring) avoids false hits like the term "ai" matching inside "available".
    """
    if not terms:
        return 0.0
    title_stems = {_stem(w) for w in _TOKEN.findall(title.lower())}
    snippet_stems = {_stem(w) for w in _TOKEN.findall(snippet.lower())}
    stems = [_stem(t) for t in terms]
    n = len(stems)
    in_title = sum(1 for s in stems if s in title_stems)
    in_any = sum(1 for s in stems if s in title_stems or s in snippet_stems)
    coverage = in_any / n
    title_coverage = in_title / n
    title_seq = " ".join(_stem(w) for w in _TOKEN.findall(title.lower()))
    phrase = 1.0 if n >= 2 and " ".join(stems) in title_seq else 0.0
    base = 0.5 * coverage + 0.4 * title_coverage + 0.1 * phrase
    # The head term is usually the query's subject (after stopwords: "ai" in "ai news today",
    # "mechanical" in "best mechanical keyboard"). A result missing the subject entirely is a poor
    # match even if it covers the generic remainder, so halve its score.
    head_present = stems[0] in title_stems or stems[0] in snippet_stems
    return base if head_present else base * 0.5


def blended_score(rrf_score: float, lexical: float, affinity: float = 1.0) -> float:
    """Fold the lexical match and language affinity into an RRF score (demotion-only).

    The lexical factor is capped at 1.0, so a well-matching result keeps its full RRF weight and
    engine consensus still orders the good matches (a keyword-stuffed title is never promoted over a
    result several engines agree on). A weak match is sunk toward `RELEVANCE_BASE`. The language
    `affinity` (<= 1.0 for a foreign-script result) multiplies on top, demoting wrong-language hits.
    """
    lexical_factor = min(1.0, RELEVANCE_BASE + RELEVANCE_GAIN * lexical)
    return rrf_score * lexical_factor * affinity
