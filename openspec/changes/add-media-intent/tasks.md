# Tasks: media-intent

User decisions (confirmed at build time): platform lists as proposed plus the entity's Wikipedia
article leading each row; the actions row appears for resolved entities only (no cue-only rows).

## Detection

- [x] Detect the entity type from the Wikipedia summary's short description the app already fetches
      (no extra network call); resolved-entity-only (cue-only rows dropped per the user's choice).
- [x] `engines/media_intent.py`: description -> `MediaCategory` mapping (Music/Film&TV/Books/Games).
- [x] Per-category curated platform lists (free/open first) + deep-link builders, with the entity's
      Wikipedia article leading each row.

## Promotion + injection

- [x] `promote_media`: bounded (<= 3 slots), stable promotion of category-platform hosts, applied
      after relevance/personalization and before the user's domain rules (pin/raise/lower/block win).
- [x] Actions-row card (GUI rich-text card + served row), static local deep links, tracker-free,
      `rel=noopener noreferrer`; verb label localized, brand names not translated.
- [x] Settings toggle `media_actions_enabled` (default on), GUI + served.

## Android (parity)

- [ ] Same detection, mapping, platform lists, deep-link templates, promotion, and actions row.

## Verify + ship

- [x] Tests: type->category mapping (+ non-media None), promotion bounds + stability, deep-link
      construction (Wikipedia first, URL-encoded), host-in-category, served toggle off.
- [ ] `openspec validate add-media-intent --strict`; spot-check a sample entity; ship in the RC pile.
