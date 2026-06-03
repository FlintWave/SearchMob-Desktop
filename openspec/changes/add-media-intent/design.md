# Design: media-intent

## Detection

- Primary: extend the existing Wikipedia summary fetch to also return the entity's type. Use the
  Wikidata `instance of` (P31) when available, else parse the summary description ("1984 dystopian
  film", "American rock band"). Map the type to a category: Music (artist/band/album/song), Film & TV
  (film/series/episode), Books (book/novel), Games (video game). Multilingual because Wikidata types
  are language-agnostic.
- Fallback: a minimal cue map for queries with no entity (e.g. "soundtrack", "trailer", "lyrics",
  "discography"). Kept small and treated as a localization-pass hook; never the primary path.

## Platform lists (curated, neutral, free/open first)

- Music: Bandcamp, YouTube Music, Discogs, SoundCloud, Spotify, Apple Music, Genius (lyrics), Last.fm.
- Film & TV: YouTube, IMDb, JustWatch, TMDB, Letterboxd, Rotten Tomatoes.
- Books: Open Library, Project Gutenberg (where applicable), Goodreads, Google Books, StoryGraph.
- Games: Steam, GOG, Metacritic, IGDB, Epic.

Order is fixed and disclosed; no affiliate or tracking parameters. Final lists to be confirmed with
the user before build.

## Promotion vs injection

- Promotion: a bounded positive multiplier in the ranking pass for results whose host is in the
  detected category's platform set. It is the positive mirror of the AI-slop downrank and runs in the
  same pass, after relevance and before user domain rules, so pin/raise/lower/block still win.
- Injection: an actions-row card (like the Wikipedia summary card) listing per-platform deep links
  built from the entity name (e.g. an Apple Music / Bandcamp / YouTube search URL for the artist).
  Links are constructed locally and rendered, not fetched, so no new outbound calls at search time.

## Privacy / owner / parity

- The only network call is the Wikipedia/Wikidata lookup already made for the summary; deep links are
  static. Links are tracker-stripped and carry `rel=noopener noreferrer` like all result links.
- A Settings toggle (default on) controls the whole feature. Owner/LAN gating matches other cards.
- Parity: detection, category mapping, platform lists, and deep-link builders are shared concepts
  with the Android app and must use the same names and URL templates.

## Open questions for build time

- Confirm the per-category platform lists and ordering with the user.
- Decide whether the actions row also appears for explicit cue-only detections or only for resolved
  entities (leaning: resolved entities, to avoid wrong-entity rows).
