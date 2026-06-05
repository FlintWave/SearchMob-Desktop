"""Media intent: category detection, actions-row construction, and bounded promotion."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from searchmob_desktop.engines.media_intent import (
    MediaCategory,
    build_actions_row,
    detect_category,
    host_in_category,
    promote_media,
)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("1984 dystopian novel by George Orwell", MediaCategory.BOOKS),
        ("American rock band", MediaCategory.MUSIC),
        ("1999 studio album by The Roots", MediaCategory.MUSIC),
        ("1982 science fiction film", MediaCategory.FILM_TV),
        ("American animated television series", MediaCategory.FILM_TV),
        ("2011 action-adventure video game", MediaCategory.GAMES),
        ("graphic novel by Alan Moore", MediaCategory.BOOKS),
        ("English singer and songwriter", MediaCategory.MUSIC),
    ],
)
def test_detect_category_maps_entity_types(description: str, expected: MediaCategory) -> None:
    assert detect_category(description) is expected


@pytest.mark.parametrize(
    "description",
    ["American politician", "capital city of France", "chemical element", "", "a large mountain"],
)
def test_detect_category_returns_none_for_non_media(description: str) -> None:
    assert detect_category(description) is None


def test_video_game_beats_bare_game_word() -> None:
    # "game" alone is not a cue; "video game" is the cue that maps to GAMES.
    assert detect_category("2011 video game developed by Mojang") is MediaCategory.GAMES


def test_build_actions_row_leads_with_wikipedia_then_platforms() -> None:
    row = build_actions_row(
        MediaCategory.MUSIC, "The Cure", "https://en.wikipedia.org/wiki/The_Cure"
    )
    assert row.label == "Listen on"
    assert row.links[0].label == "Wikipedia"
    assert row.links[0].url == "https://en.wikipedia.org/wiki/The_Cure"
    # Free/open first: Bandcamp leads the platforms.
    assert row.links[1].label == "Bandcamp"
    # The entity name is URL-encoded into each platform's search URL.
    assert any("The+Cure" in link.url for link in row.links)
    # No tracking/affiliate params and no double Wikipedia.
    assert sum(link.label == "Wikipedia" for link in row.links) == 1


def test_build_actions_row_without_wikipedia_url() -> None:
    row = build_actions_row(MediaCategory.GAMES, "Minecraft", None)
    assert row.links[0].label == "GOG"  # no Wikipedia link -> platforms lead
    assert row.label == "Play on"


@dataclass(frozen=True)
class _R:
    url: str


def test_host_in_category_matches_subdomains() -> None:
    assert host_in_category("https://open.spotify.com/track/1", MediaCategory.MUSIC)
    assert host_in_category("https://www.imdb.com/title/tt1", MediaCategory.FILM_TV)
    assert not host_in_category("https://example.com/x", MediaCategory.MUSIC)
    # A music host is not in the games category.
    assert not host_in_category("https://bandcamp.com/x", MediaCategory.GAMES)


def test_promote_media_is_bounded_and_stable() -> None:
    # A canonical-platform result at index 5 is lifted, but by at most the bound (3).
    results = [_R(f"https://e{i}.example/x") for i in range(5)] + [_R("https://imdb.com/title/x")]
    promoted = promote_media(results, MediaCategory.FILM_TV, boost=3)
    imdb_index = next(i for i, r in enumerate(promoted) if "imdb.com" in r.url)
    assert 5 - 3 <= imdb_index < 5  # moved up, but no further than the bound
    # Non-matching results keep their relative order.
    assert [r.url for r in promoted if "imdb" not in r.url] == [r.url for r in results[:5]]


def test_promote_media_no_match_is_identity() -> None:
    results = [_R(f"https://e{i}.example/x") for i in range(4)]
    assert promote_media(results, MediaCategory.BOOKS) == results
