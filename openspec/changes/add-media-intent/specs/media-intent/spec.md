## ADDED Requirements

### Requirement: Media-category detection

The system SHALL detect a query's media category (Music, Film & TV, Books, or Games) primarily from
the entity's structured type in the Wikipedia/Wikidata data already fetched for entity-like queries,
and SHALL fall back to a minimal keyword cue only when no entity type is available. Detection SHALL
NOT depend on English-only cues as its primary signal.

#### Scenario: Entity type drives detection without a cue word

- **WHEN** the query names a media entity with no generic cue word (e.g. a film title)
- **THEN** the media category is detected from the entity's type rather than from query keywords

#### Scenario: No entity falls back to cues

- **WHEN** no entity type is available for the query but a recognizable media cue is present
- **THEN** the category is detected from the cue, and otherwise no media intent is applied

### Requirement: Canonical-platform promotion

The system SHALL, when a media category is detected, promote results from that category's canonical
platforms within the ranked list. Promotion SHALL be a bounded, disclosed boost that does not
override the user's explicit pin/raise/lower/block rules, and SHALL lead each category with free or
open platforms alongside mainstream ones.

#### Scenario: A canonical platform result rises

- **WHEN** a music query is detected and a result from a recognized music platform is present
- **THEN** that result is promoted within the ranking, but never above an explicitly pinned result

### Requirement: Canonical actions row

The system SHALL render an actions row of canonical destinations for the detected entity ("Listen on
/ Watch on / Read on / Play on"), built as static deep links from the entity name even when no engine
returned them. The row SHALL be transparent, fixed in order, free of tracking or affiliate
parameters, and controllable by a Settings toggle.

#### Scenario: Actions row appears for a detected entity

- **WHEN** a musician query is detected
- **THEN** an actions row offering that artist on the category's platforms is shown, and it can be
  turned off in Settings

#### Scenario: No media intent, no row

- **WHEN** a query has no detected media category
- **THEN** no actions row is shown and ranking is unchanged by this capability
