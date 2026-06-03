# Tasks: media-intent

## Detection

- [ ] Extend the Wikipedia summary fetch to expose the entity type (Wikidata P31 / description parse).
- [ ] Media-intent module: type -> category mapping; minimal cue fallback.
- [ ] Per-category curated platform lists + deep-link builders (confirm lists with the user first).

## Promotion + injection

- [ ] Ranking pass: bounded, disclosed promotion of category-platform hosts, after relevance and
      before user domain rules (pin/raise/lower/block still win).
- [ ] Actions-row card (GUI + served page), built from static local deep links, tracker-free,
      `rel=noopener noreferrer`; owner-safe like the summary card.
- [ ] Settings toggle (default on).

## Android (parity)

- [ ] Same detection, mapping, platform lists, deep-link templates, promotion, and actions row.

## Verify + ship

- [ ] Confirm detection for sample entities (film/musician/album/book/game) and correct platforms;
      confirm no row and unchanged ranking for non-media queries; confirm the toggle and that pins
      still win.
- [ ] Tests: type->category mapping, promotion bounds vs domain rules, deep-link construction,
      toggle off.
- [ ] Ship after relevance v1 and paging; RC bypassed: local verify + CI, direct GA.
