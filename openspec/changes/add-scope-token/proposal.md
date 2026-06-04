## Why

Scopes (lenses) already exist as a saved, sticky personalization control: the user picks one in the
GUI or the served scope selector and it filters results until they change it. But headless and
scripted callers — the CLI `search` command and the served HTTP endpoints driven from a browser
address bar or a script — have no ergonomic way to say "run *this one* search through a scope"
without first flipping the persistent selector. For one-off, query-by-query use, the natural place to
put the scope is in the query itself.

This adds an inline, additive scope token: appending a `+name` word to a query applies the matching
scope to that single search only, without changing the saved selection. It mirrors the familiar
`+term` / `-term` operator feel users already expect from search boxes, and it stays out of the way:
an unmatched `+word` is left in the query as an ordinary term.

## What Changes

- Parse a search query for a whitespace-delimited `+token`. Match the token (case-insensitively)
  against the user's defined scopes by the scope name's first word, falling back to a normalized
  full-name match. The first matching token wins and is stripped from the query; the matched scope is
  applied to that search only and is never persisted.
- An unmatched `+word` is left untouched in the query so ordinary `+must-have` style terms keep
  working.
- Wire the parser into the surfaces that lack an interactive selector: the desktop CLI `search`
  command (which previously applied no scope at all) and the desktop served `/search` + `/api/search`
  endpoints. The Android served `/search` endpoint mirrors the same behaviour.
- Deliberately exclude the MCP `web_search` tool: the agent keeps its dedicated safety exclude-scope
  untouched, so a model cannot widen its own scope through query text.

## Capabilities

### New Capabilities
- `scope-token`: an inline `+name` query token that applies a matching saved scope to a single
  search, parsed identically across the CLI and the served endpoints, additive and non-persistent,
  and leaving unmatched tokens in the query.

### Modified Capabilities
<!-- None in contract. The saved scope selector (result-personalization) keeps its meaning; the
inline token is a transient, per-search overlay that does not touch the persisted active scope. -->

## Non-goals

- Changing the persisted scope: the token never writes the active scope. The sticky selector in the
  GUI and served UI is unaffected.
- Inventing scopes from a token: a token only ever selects an already-defined scope; an unknown
  token stays a search term.
- MCP exposure: the agent tool keeps its fixed safety scope and does not honour inline tokens.
- Operator syntax beyond a single leading-`+` word per match (no `scope:`-style keys, no quoted
  multi-word tokens this change).

## Impact

- New: `engines/rank/scope_token.py` — the pure `parse_scope_token(query, rules)` parser.
- Modified: `cli.py` (`search` now loads scopes, parses the query, and applies the matched scope to
  the result pool — previously it applied none); `server/app.py` (`/search` + `/api/search` parse the
  query and apply the matched scope transiently for that request, using the cleaned query for the
  engines/summary/correction while echoing the original text in the box).
- No new dependencies, no new outbound calls, no telemetry. Scope definitions are read from the
  existing local ranking store; the token only chooses among them for one search.
