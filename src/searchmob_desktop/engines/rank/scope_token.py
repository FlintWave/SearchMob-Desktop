"""Parse an inline ``+name`` scope token out of a search query.

Scopes (lenses) are normally a sticky, saved selection. For one-off headless and scripted searches
it is handier to name the scope in the query itself: ``mechanical keyboards +research`` runs that
one search through the scope whose name starts with "Research", without touching the saved
selection.

`parse_scope_token` is pure: it reads the defined scopes off a `RankingRules` and returns the query
with the matched token removed plus the matched scope's name (or `None`). It never resolves the
scope's filters or mutates the rules; applying the scope is left to `apply_ranking`, which keeps
this trivially testable. An unmatched ``+word`` is left in the query so ordinary ``+term`` input
still works.
"""

from __future__ import annotations

from searchmob_desktop.engines.rank.model import RankingRules


def _normalize(text: str) -> str:
    """Lowercase `text` and keep only its alphanumerics (for whole-name fallback matching)."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _match_scope(candidate: str, rules: RankingRules) -> str | None:
    """Return the name of the scope matched by `candidate`, or None.

    First-word match (the scope name's first word, case-insensitive) is tried against every scope
    before any whole-name fallback, so a first-word hit always beats a normalized full-name hit.
    """
    lowered = candidate.lower()
    for lens in rules.lenses:
        words = lens.name.split()
        if words and words[0].lower() == lowered:
            return lens.name
    normalized = _normalize(candidate)
    if normalized:
        for lens in rules.lenses:
            if _normalize(lens.name) == normalized:
                return lens.name
    return None


def parse_scope_token(query: str, rules: RankingRules) -> tuple[str, str | None]:
    """Strip the first matching ``+name`` token from `query` and return (cleaned, scope name).

    Walks whitespace-delimited tokens left to right; the first ``+<rest>`` whose ``<rest>`` matches
    a defined scope wins. That one token is removed (the rest, including any unmatched ``+word``, is
    kept) and the matched scope's exact name is returned. When nothing matches, the query is
    returned unchanged with `None`.
    """
    if "+" not in query:
        return query, None
    tokens = query.split()
    for index, token in enumerate(tokens):
        if len(token) < 2 or not token.startswith("+"):
            continue
        name = _match_scope(token[1:], rules)
        if name is not None:
            cleaned = " ".join(tokens[:index] + tokens[index + 1 :])
            return cleaned, name
    return query, None
