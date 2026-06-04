## ADDED Requirements

### Requirement: Inline scope token selects a saved scope for one search

The system SHALL parse a search query for a whitespace-delimited token beginning with `+`. When a
token matches one of the user's defined scopes, the system SHALL apply that scope to that single
search and SHALL remove the token from the query sent to the engines. The match SHALL be
case-insensitive against the scope name's first word, falling back to a normalized (lowercased,
alphanumeric-only) match of the whole scope name when no first-word match is found. When more than
one token matches, the first matching token in the query SHALL win and exactly one scope SHALL be
applied.

#### Scenario: A matching token applies its scope

- **WHEN** the user searches `mechanical keyboards +research` and a scope whose name begins with
  "Research" exists
- **THEN** that scope filters the results for this search and the engines receive
  `mechanical keyboards` with the token removed

#### Scenario: First matching token wins

- **WHEN** the query contains two tokens that each match a different scope
- **THEN** only the scope matched by the earlier token is applied and only that token is removed

### Requirement: Unmatched tokens stay in the query

The system SHALL leave a `+word` token in the query unchanged when it does not match any defined
scope, so ordinary `+term` search input is preserved.

#### Scenario: An unknown token is treated as a search term

- **WHEN** the user searches `rust +tokio` and no scope matches "tokio"
- **THEN** no scope is applied and the engines receive `rust +tokio` unchanged

### Requirement: Inline scope is per-search and never persisted

The system SHALL apply the token-selected scope to the current search only and SHALL NOT change the
saved active scope. A later search without a token SHALL use the saved scope (or none) as before.

#### Scenario: The saved scope is untouched

- **WHEN** the user runs one search with a `+name` token and then another search with no token
- **THEN** the first search uses the token's scope, the second uses the previously saved scope, and
  the saved active scope is unchanged throughout

### Requirement: Inline scope tokens on headless and served surfaces

The system SHALL honour the inline scope token on the command-line `search` and on the served
`/search` and `/api/search` endpoints, parsing it identically across those surfaces. The system
SHALL NOT honour inline scope tokens in the agent-facing MCP search tool, which keeps its fixed
safety scope.

#### Scenario: The command line applies a token scope

- **WHEN** a `+name` token in a CLI `search` query matches a defined scope
- **THEN** the printed results are filtered through that scope and the token is not shown as part of
  the searched query

#### Scenario: The agent tool ignores tokens

- **WHEN** a query passed to the MCP search tool contains a `+name` token
- **THEN** the agent's fixed scope is applied unchanged and the token is treated as ordinary query
  text
