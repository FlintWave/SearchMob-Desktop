"""Media intent: detect a query's media category from the resolved entity and surface its platforms.

When a query resolves to a piece of media (a film, musician, album, song, book, or video game), the
most useful destinations are the canonical places to watch, listen, read, or play it, plus the
reference page for it. This module turns the Wikipedia/Wikidata summary the app already has into:

* a `MediaCategory` (Music / Film & TV / Books / Games), parsed from the entity's short description
  (so it needs no extra network call and is language-agnostic for the type words it keys on), and
* an `ActionsRow`: the entity's Wikipedia article followed by per-platform deep links built locally
  from the entity name. Free/open platforms lead each category; the order is fixed and disclosed,
  and the links carry no affiliate or tracking parameters.

Detection is resolved-entity-only: with no confident entity there is no category, no row, and no
ranking change. The same category also drives a bounded, positive promotion of canonical-platform
results in the ranking (the mirror of the AI-slop downrank), computed from `category_hosts`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from urllib.parse import quote_plus, urlsplit


class _HasUrl(Protocol):
    @property
    def url(self) -> str: ...


class MediaCategory(Enum):
    """The media categories the actions row supports."""

    MUSIC = "music"
    FILM_TV = "film_tv"
    BOOKS = "books"
    GAMES = "games"


# The action verb that heads each category's row. English source; localized at the call site.
ROW_LABEL: dict[MediaCategory, str] = {
    MediaCategory.MUSIC: "Listen on",
    MediaCategory.FILM_TV: "Watch on",
    MediaCategory.BOOKS: "Read on",
    MediaCategory.GAMES: "Play on",
}


@dataclass(frozen=True, slots=True)
class Platform:
    """One destination: a display name and a query-URL template with a single `{q}` placeholder."""

    name: str
    template: str
    host: str  # bare registrable host, for the ranking promotion lookup


# Per-category platforms, free/open first, then mainstream, then neutral reference. Templates are
# search/deep-link URLs; `{q}` is filled with the URL-encoded entity name. No affiliate/tracking
# params. Confirmed with the user (the entity's Wikipedia article is prepended separately).
_PLATFORMS: dict[MediaCategory, tuple[Platform, ...]] = {
    MediaCategory.MUSIC: (
        Platform("Bandcamp", "https://bandcamp.com/search?q={q}", "bandcamp.com"),
        Platform("YouTube Music", "https://music.youtube.com/search?q={q}", "youtube.com"),
        Platform("SoundCloud", "https://soundcloud.com/search?q={q}", "soundcloud.com"),
        Platform("Discogs", "https://www.discogs.com/search/?q={q}", "discogs.com"),
        Platform("Spotify", "https://open.spotify.com/search/{q}", "spotify.com"),
        Platform("Apple Music", "https://music.apple.com/us/search?term={q}", "music.apple.com"),
        Platform("Genius", "https://genius.com/search?q={q}", "genius.com"),
        Platform("Last.fm", "https://www.last.fm/search?q={q}", "last.fm"),
    ),
    MediaCategory.FILM_TV: (
        Platform("YouTube", "https://www.youtube.com/results?search_query={q}", "youtube.com"),
        Platform("JustWatch", "https://www.justwatch.com/us/search?q={q}", "justwatch.com"),
        Platform("IMDb", "https://www.imdb.com/find/?q={q}", "imdb.com"),
        Platform("TMDB", "https://www.themoviedb.org/search?query={q}", "themoviedb.org"),
        Platform("Letterboxd", "https://letterboxd.com/search/{q}/", "letterboxd.com"),
        Platform(
            "Rotten Tomatoes",
            "https://www.rottentomatoes.com/search?search={q}",
            "rottentomatoes.com",
        ),
    ),
    MediaCategory.BOOKS: (
        Platform("Open Library", "https://openlibrary.org/search?q={q}", "openlibrary.org"),
        Platform(
            "Project Gutenberg",
            "https://www.gutenberg.org/ebooks/search/?query={q}",
            "gutenberg.org",
        ),
        Platform(
            "StoryGraph",
            "https://app.thestorygraph.com/browse?search_term={q}",
            "thestorygraph.com",
        ),
        Platform("Goodreads", "https://www.goodreads.com/search?q={q}", "goodreads.com"),
        Platform("Google Books", "https://www.google.com/search?tbm=bks&q={q}", "books.google.com"),
    ),
    MediaCategory.GAMES: (
        Platform("GOG", "https://www.gog.com/games?query={q}", "gog.com"),
        Platform("Steam", "https://store.steampowered.com/search/?term={q}", "steampowered.com"),
        Platform("Metacritic", "https://www.metacritic.com/search/{q}/", "metacritic.com"),
        Platform("IGDB", "https://www.igdb.com/search?type=1&q={q}", "igdb.com"),
        Platform("Epic", "https://store.epicgames.com/en-US/browse?q={q}", "epicgames.com"),
    ),
}

# Type words (as they appear in a Wikipedia description / lead) that map to a category, ordered
# by specificity within the scan; "video game" must beat the bare "game", and "graphic novel" /
# "comic" go to Books. The scan is on a normalized, lowercased description. Kept deliberately small
# and concrete (a localization pass can extend per language); detection is secondary to the entity.
_TYPE_CUES: tuple[tuple[str, MediaCategory], ...] = (
    ("video game", MediaCategory.GAMES),
    ("studio album", MediaCategory.MUSIC),
    ("album", MediaCategory.MUSIC),
    ("song", MediaCategory.MUSIC),
    ("single by", MediaCategory.MUSIC),
    ("extended play", MediaCategory.MUSIC),
    ("rock band", MediaCategory.MUSIC),
    ("band", MediaCategory.MUSIC),
    ("musician", MediaCategory.MUSIC),
    ("singer", MediaCategory.MUSIC),
    ("rapper", MediaCategory.MUSIC),
    ("composer", MediaCategory.MUSIC),
    ("discography", MediaCategory.MUSIC),
    ("television series", MediaCategory.FILM_TV),
    ("tv series", MediaCategory.FILM_TV),
    ("miniseries", MediaCategory.FILM_TV),
    ("sitcom", MediaCategory.FILM_TV),
    ("anime", MediaCategory.FILM_TV),
    ("film", MediaCategory.FILM_TV),
    ("documentary", MediaCategory.FILM_TV),
    ("graphic novel", MediaCategory.BOOKS),
    ("novel", MediaCategory.BOOKS),
    ("novella", MediaCategory.BOOKS),
    ("memoir", MediaCategory.BOOKS),
    ("book by", MediaCategory.BOOKS),
    ("comic", MediaCategory.BOOKS),
)


def detect_category(description: str) -> MediaCategory | None:
    """Map a resolved entity's short description to a `MediaCategory`, or None when it is not media.

    Scans the (lowercased) description for the first matching type cue. "1984 dystopian novel by
    George Orwell" -> BOOKS; "American rock band" -> MUSIC; "1982 science fiction film" -> FILM_TV.
    Returns None for anything without a recognized media type (people who are not performers,
    places, concepts), so a non-media entity never gets a row or a ranking change.
    """
    if not description:
        return None
    text = re.sub(r"\s+", " ", description.lower())
    for cue, category in _TYPE_CUES:
        if cue in text:
            return category
    return None


@dataclass(frozen=True, slots=True)
class ActionLink:
    """One destination in the actions row: a display label and a ready-to-render URL."""

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class ActionsRow:
    """The media actions row for an entity: the row's verb label and its destination links."""

    category: MediaCategory
    label: str  # the English verb ("Listen on"); the renderer may localize it
    links: tuple[ActionLink, ...]


def build_actions_row(
    category: MediaCategory, entity_name: str, wikipedia_url: str | None
) -> ActionsRow:
    """Build the actions row for `entity_name` in `category`, leading with its Wikipedia article.

    Every link is constructed locally from the entity name (a per-platform search URL); nothing is
    fetched. The Wikipedia article (already resolved for the summary card) leads as a neutral
    reference when present.
    """
    q = quote_plus(entity_name)
    links: list[ActionLink] = []
    if wikipedia_url:
        links.append(ActionLink("Wikipedia", wikipedia_url))
    links.extend(ActionLink(p.name, p.template.format(q=q)) for p in _PLATFORMS[category])
    return ActionsRow(category=category, label=ROW_LABEL[category], links=tuple(links))


# How many positions a canonical-platform result may be lifted. Small and bounded on purpose: it
# nudges the right platform up without letting it leap over results several engines agree on; the
# user's domain rules (pin/raise/lower/block) run afterward and still win.
_PROMOTE_BOOST = 3


def promote_media[T: _HasUrl](
    results: list[T], category: MediaCategory, *, boost: int = _PROMOTE_BOOST
) -> list[T]:
    """Stably lift results whose host is in `category`'s platform set by at most `boost` slots.

    A positive mirror of the AI-slop downrank: it runs after relevance and before the user's domain
    rules. Bounded and order-preserving (a matched result moves up by at most `boost`; everything
    else keeps its relative order), so a canonical platform is nudged up without overriding strong
    engine consensus, and pin/raise/block still take precedence in the later rules pass. `results`
    must expose a `.url`; the order of equal keys is stable.
    """
    keyed = [
        (index - (boost if host_in_category(item.url, category) else 0), index, item)
        for index, item in enumerate(results)
    ]
    keyed.sort(key=lambda triple: (triple[0], triple[1]))
    return [item for _, _, item in keyed]


def category_hosts(category: MediaCategory) -> frozenset[str]:
    """The bare hosts for a category, used by the ranking promotion (a result on one is lifted)."""
    return frozenset(p.host for p in _PLATFORMS[category])


def host_in_category(url: str, category: MediaCategory) -> bool:
    """Whether `url`'s host is (or is a subdomain of) one of the category's platform hosts."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    host = host.lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in category_hosts(category))
