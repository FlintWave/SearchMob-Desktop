"""DuckDuckGo-style !bangs, ported from the Android `engine/bang/Bangs.kt`.

A ``!tag`` at the start or end of a query jumps straight to that site's own search for the rest
of the query (``!w privacy`` -> Wikipedia's search for "privacy").

The table is a small curated set resolved entirely on-device: SearchMob itself never sees a bang
query's terms leave through the metasearch fan-out, and no bang-resolution service is consulted.
Only an exact, known tag triggers - a token like ``!important`` simply stays part of the query -
so ordinary searches can never be hijacked. The default map/search targets prefer
privacy-respecting services; explicit big-brand tags (e.g. ``!g``, ``!yt``) exist because a bang
is the user *choosing* that destination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

__all__ = ["ALL_BANGS", "Bang", "BangRedirect", "resolve_bang"]


@dataclass(frozen=True, slots=True)
class Bang:
    """One bang: its tag (without ``!``), a human label, the search URL template (``{q}`` marks
    where the URL-encoded query goes), and the site home for a bare bang."""

    tag: str
    label: str
    search_url: str
    home_url: str


@dataclass(frozen=True, slots=True)
class BangRedirect:
    """A resolved bang redirect: the destination `url` plus the `bang` and remaining `terms`."""

    url: str
    bang: Bang
    terms: str


# fmt: off
ALL_BANGS: tuple[Bang, ...] = (
    Bang("w", "Wikipedia", "https://en.wikipedia.org/wiki/Special:Search?search={q}", "https://en.wikipedia.org"),
    Bang("wt", "Wiktionary", "https://en.wiktionary.org/wiki/Special:Search?search={q}", "https://en.wiktionary.org"),
    Bang("yt", "YouTube", "https://www.youtube.com/results?search_query={q}", "https://www.youtube.com"),
    Bang("gh", "GitHub", "https://github.com/search?q={q}", "https://github.com"),
    Bang("so", "Stack Overflow", "https://stackoverflow.com/search?q={q}", "https://stackoverflow.com"),
    Bang("r", "Reddit", "https://www.reddit.com/search/?q={q}", "https://www.reddit.com"),
    Bang("hn", "Hacker News", "https://hn.algolia.com/?q={q}", "https://news.ycombinator.com"),
    Bang("mdn", "MDN Web Docs", "https://developer.mozilla.org/en-US/search?q={q}", "https://developer.mozilla.org"),
    Bang("aw", "Arch Wiki", "https://wiki.archlinux.org/index.php?search={q}", "https://wiki.archlinux.org"),
    Bang("osm", "OpenStreetMap", "https://www.openstreetmap.org/search?query={q}", "https://www.openstreetmap.org"),
    Bang("maps", "OpenStreetMap", "https://www.openstreetmap.org/search?query={q}", "https://www.openstreetmap.org"),
    Bang("wa", "Wolfram Alpha", "https://www.wolframalpha.com/input?i={q}", "https://www.wolframalpha.com"),
    Bang("g", "Google", "https://www.google.com/search?q={q}", "https://www.google.com"),
    Bang("ddg", "DuckDuckGo", "https://duckduckgo.com/?q={q}", "https://duckduckgo.com"),
    Bang("b", "Bing", "https://www.bing.com/search?q={q}", "https://www.bing.com"),
    Bang("sp", "Startpage", "https://www.startpage.com/sp/search?query={q}", "https://www.startpage.com"),
    Bang("br", "Brave Search", "https://search.brave.com/search?q={q}", "https://search.brave.com"),
    Bang("mjk", "Mojeek", "https://www.mojeek.com/search?q={q}", "https://www.mojeek.com"),
    Bang("a", "Amazon", "https://www.amazon.com/s?k={q}", "https://www.amazon.com"),
    Bang("e", "eBay", "https://www.ebay.com/sch/i.html?_nkw={q}", "https://www.ebay.com"),
    Bang("imdb", "IMDb", "https://www.imdb.com/find/?q={q}", "https://www.imdb.com"),
    Bang("py", "Python docs", "https://docs.python.org/3/search.html?q={q}", "https://docs.python.org/3/"),
    Bang("npm", "npm", "https://www.npmjs.com/search?q={q}", "https://www.npmjs.com"),
    Bang("pypi", "PyPI", "https://pypi.org/search/?q={q}", "https://pypi.org"),
    Bang("crates", "crates.io", "https://crates.io/search?q={q}", "https://crates.io"),
    Bang("fdroid", "F-Droid", "https://search.f-droid.org/?q={q}", "https://f-droid.org"),
    Bang("cve", "NVD CVE search", "https://nvd.nist.gov/vuln/search/results?query={q}", "https://nvd.nist.gov"),
    Bang("dict", "Merriam-Webster", "https://www.merriam-webster.com/dictionary/{q}", "https://www.merriam-webster.com"),
    Bang("etym", "Etymonline", "https://www.etymonline.com/search?q={q}", "https://www.etymonline.com"),
    Bang("x", "X (Twitter)", "https://x.com/search?q={q}", "https://x.com"),
)
# fmt: on

_BY_TAG: dict[str, Bang] = {bang.tag: bang for bang in ALL_BANGS}

# Aliases so the most guessable spellings work too.
_ALIASES = {
    "wiki": "w",
    "wikipedia": "w",
    "youtube": "yt",
    "github": "gh",
    "reddit": "r",
    "stackoverflow": "so",
    "arch": "aw",
    "google": "g",
    "amazon": "a",
    "ebay": "e",
    "bing": "b",
    "startpage": "sp",
    "brave": "br",
    "mojeek": "mjk",
    "twitter": "x",
}

_WHITESPACE = re.compile(r"\s+")


def _bang_of(token: str) -> Bang | None:
    if len(token) < 2 or token[0] != "!":
        return None
    tag = token[1:].lower()
    bang = _BY_TAG.get(tag)
    if bang is not None:
        return bang
    alias = _ALIASES.get(tag)
    return _BY_TAG[alias] if alias is not None else None


def resolve_bang(query: str) -> BangRedirect | None:
    """Resolve a ``!bang`` in `query`: the first or last whitespace-separated token may be
    ``!tag`` (case-insensitive). Returns None when there is no token of that shape or the tag is
    unknown - the query then proceeds as a normal search, so ``!important css`` is never
    hijacked."""
    trimmed = query.strip()
    if "!" not in trimmed:
        return None
    tokens = _WHITESPACE.split(trimmed)
    if not tokens:
        return None

    first = _bang_of(tokens[0])
    last = _bang_of(tokens[-1]) if len(tokens) > 1 else None
    if first is not None:
        bang, terms = first, " ".join(tokens[1:])
    elif last is not None:
        bang, terms = last, " ".join(tokens[:-1])
    else:
        return None

    if not terms.strip():
        url = bang.home_url
    else:
        # Encode into a path or query slot: %20 for spaces is valid in both ('+' is not in paths).
        url = bang.search_url.replace("{q}", quote(terms, safe=""))
    return BangRedirect(url=url, bang=bang, terms=terms)
