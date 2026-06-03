## Why

When a query is about a piece of media (a film, musician, album, song, book, or game), the most
useful results are the canonical places to watch, listen, read, or play it, plus the reference pages
for it. Generic web ranking buries these. The query often has no cue word ("metropolis the musical"
gives no generic signal that it is media), so detection must use what the entity actually is, not
keyword guessing, and it must work in any language ahead of the localization pass. We want to
recognize media intent and surface the right platforms, while staying neutral and transparent (a
privacy engine should not silently push only paid commercial services).

## What Changes

- Detect media type via the entity's structured type from the Wikipedia/Wikidata data the app already
  fetches for entity-like queries (instance-of: film, album, musician, band, song, book, video game,
  ...), with a small keyword-cue fallback for queries where no entity is found.
- Map the detected type to a media category: Music (artist/album/song), Film & TV, Books, Games.
- Promote canonical-platform results already in the ranked list for the detected category (a positive
  counterpart to the AI-slop downrank), so e.g. a Spotify/IMDb/Open Library result floats up.
- Inject an actions row (a knowledge-panel-style card) of canonical destinations for the entity, even
  when no engine returned them, built from the entity name: "Listen on / Watch on / Read on / Play
  on". Lead each category with free / open options (Bandcamp, YouTube, Open Library, Discogs)
  alongside the mainstream ones; keep it transparent and behind a toggle (default on, off-able).

## Capabilities

### New Capabilities
- `media-intent`: detect a query's media category from entity data (with a cue fallback) and surface
  the canonical platforms for it, by promoting matching results and injecting an actions row, neutral
  and toggleable.

### Modified Capabilities
<!-- None in contract; promotion is a new positive pass beside the existing AI-slop pass, and the
actions row is a new card beside the existing Wikipedia summary card. -->

## Non-goals

- A full knowledge graph or recommendations: only the detected entity's canonical platforms.
- Affiliate links, tracking, or sponsored ordering: never. Ordering is fixed and disclosed.
- Promoting only paid services: free/open options lead each category.
- Language-specific cue lists beyond a minimal fallback: cues are secondary to entity type and are a
  localization-pass hook.

## Impact

- New code: a media-intent module (entity-type -> category mapping, per-category curated platform
  lists, deep-link builders), promotion in the ranking pass, and an actions-row card.
- Modified: the Wikipedia summary fetch to also expose the entity type; the ranking pass (promotion);
  the GUI results view and the served page (actions row, owner-safe); Android equivalents. A Settings
  toggle. The same outbound Wikipedia/Wikidata call already made for the summary; deep links are
  rendered, not fetched (no new outbound calls at search time).
- Privacy: the actions row links are static deep links built locally; clicking one navigates the user
  out as any result link does (tracker-stripped, `rel=noopener noreferrer`). No new telemetry.
