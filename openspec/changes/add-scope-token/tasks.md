# Tasks: inline scope token (desktop)

## Parser

- [x] `engines/rank/scope_token.py`: pure `parse_scope_token(query, rules) -> (cleaned, lens_name)`
      with first-word match (case-insensitive), normalized full-name fallback, first-token-wins, and
      a no-`+` fast path. Export it from `engines/rank/__init__.py`.

## CLI

- [x] `cli.py` `search`: load scopes, parse the query, search the cleaned query, and apply only the
      matched scope via `apply_ranking` (minimal one-scope rules; no domain/goggle/slop). Show the
      cleaned query in the table title and note the applied scope.

## Served

- [x] `server/app.py`: add an `active_lens` override to `_run_metasearch`; in `/search` and
      `/api/search` parse the query, pass the override (transient, non-persistent), search the
      cleaned query for engines/summary/correction, and echo the original text.

## Tests

- [x] `tests/engines/rank/test_scope_token.py`: parser truth table.
- [x] CLI + served tests: token applies + strips; unmatched preserved; saved active scope untouched.

## Verify

- [x] `ruff check`, `mypy`, and `pytest` green.
- [x] `openspec validate add-scope-token --strict` passes.
- [ ] Ship in the RC feature pile (own PR); Android served mirror tracked in the Android repo's
      `add-scope-token` change.
