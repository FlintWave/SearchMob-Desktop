# Design: inline scope token

## Parser (`engines/rank/scope_token.py`)

A pure, dependency-free function:

```
parse_scope_token(query: str, rules: RankingRules) -> tuple[str, str | None]
```

Returns `(cleaned_query, lens_name)`. `lens_name` is `None` when nothing matched (and
`cleaned_query == query` in that case).

Algorithm:
- Split the query on whitespace. Walk tokens left to right.
- A candidate is a token of the form `+<rest>` with a non-empty `<rest>`.
- Match precedence, across all defined scopes:
  1. **First-word**: `lens.name.split()[0].lower() == rest.lower()`.
  2. **Fallback**: normalized full name == normalized `rest`, where normalize lowercases and keeps
     only alphanumerics. First-word is tried for every candidate before any fallback so a first-word
     hit always beats a whole-name hit.
- The first candidate that matches wins: drop that one token, rejoin the rest with single spaces, and
  return the matched scope's exact name. Unmatched candidates are left in place.
- Fast path: if there is no `+` in the query, return `(query, None)` untouched.

The parser only *reads* `rules.lenses`; it never mutates rules and never resolves the scope's
filters itself. Application is left to `apply_ranking`, keeping the parser trivially testable.

## Wiring

### CLI `search` (`cli.py`)
Today the command runs `aggregate(...)` and prints the raw pool — it applies no scopes, domain
rules, or goggles. To honour `+name` without otherwise changing that raw behaviour, the command:
1. Loads scopes via `load_ranking_rules()` (fail-soft; always at least the sample scopes).
2. Parses the query: `cleaned, lens_name = parse_scope_token(query, rules)`.
3. Searches with `cleaned`.
4. If `lens_name` is set, applies *only* that one scope as a filter via `apply_ranking` with a
   minimal `RankingRules(lenses=(matched,), active_lens=lens_name)` — no domain rules, goggles, or
   slop filter — so the CLI stays otherwise-raw but respects the token. The table title shows the
   cleaned query and a note names the applied scope.

### Served `/search` + `/api/search` (`server/app.py`)
Both endpoints already load rules and run `apply_ranking`. The token is layered transiently:
1. `cleaned, lens_name = parse_scope_token(raw_q, rules_provider())`.
2. `_run_metasearch` takes an `active_lens` override; when set it applies
   `rules_provider().with_active_lens(name)` for that request only (the saved active scope and the
   persisted `/scope` selection are untouched).
3. The engines, contextual summary, and "did you mean" correction use `cleaned`; the search box and
   the echoed JSON `query` keep the original text so the token round-trips and re-running re-applies
   the scope.

### Android served `/search` (`SearchServer.kt`)
Mirrors the desktop served path: parse the query against `RankingRules.lenses`, apply the matched
scope transiently for that request, search on the cleaned query, echo the original in the box.

### MCP (excluded)
`mcp_server.run_web_search` keeps `_agent_scope`; it does not call the parser. A token in an agent
query is ordinary text.

## Testing

- Parser truth table: first-word match; case-insensitivity; normalized full-name fallback; unmatched
  token preserved; multiple tokens (first wins); token mid-query; no-`+` fast path; empty/whitespace.
- CLI: a matching token filters the printed pool and is stripped; an unmatched token is searched
  verbatim and no scope is applied.
- Served: `/search` and `/api/search` apply the matched scope and search the cleaned query while
  echoing the original; a non-matching token changes nothing; the saved active scope is not written.
- Parity: the Android served behaviour matches (same first-word + fallback rules).
