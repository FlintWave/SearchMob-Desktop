## Why

The results list is hard-capped at 10 (`max_results = 10` everywhere; the aggregator returns
`ranked[: max_results]` and each engine fetches only up to that). There is no way to load more, so
the list feels truncated and the result a user wants can be just past the cap with no way to reach
it. We want more results and a smooth "keep going" experience, without extra requests on every search
or breaking the store-nothing posture.

## What Changes

- Fetch and merge a larger pool per search (target ~30-50 merged results) instead of 10, keeping the
  per-engine fan-out bounded.
- Add infinite scroll: reveal results incrementally from the already-fetched pool as the user scrolls
  to the bottom, in the GUI, on the served page, and on Android. No new request while pool remains.
- When the pool is exhausted and engines support a page/offset parameter, fetch the next page on
  demand; engines without pagination simply contribute nothing further (fail-soft).
- Apply the full ranking pipeline (RRF + relevance blend + sort + domain rules) to the larger pool so
  later results are ranked, not raw.

## Capabilities

### New Capabilities
- `result-paging`: a larger merged result pool revealed incrementally via infinite scroll, with
  on-demand deeper fetches where engines support pagination, ranked by the normal pipeline.

### Modified Capabilities
<!-- None in contract; `max_results` semantics widen to a pool size plus an incremental reveal, but
the ranking passes are unchanged. -->

## Non-goals

- Deep cross-engine pagination beyond what each engine natively supports: engines that cannot
  paginate just stop contributing past their first page.
- Persisting or caching result pages across searches: nothing is stored (store-nothing).
- Server-side cursor state for LAN clients: paging is computed per request; no per-client session.

## Impact

- Modified: `EngineContext`/`max_results` usage to separate "pool size" from "page reveal size";
  `engines/aggregator.py` (return the ranked pool); the GUI results view (infinite scroll);
  `server/app.py` + `server/templates.py` (served-page incremental reveal / `?offset=`); the CLI
  `--max-results`. Engine adapters that support a page param gain optional deeper fetch. Mirrored on
  Android (`Aggregator.kt`, the Compose results `LazyColumn`, the served page).
- Slightly larger per-search work (bigger pool); bounded by the pool cap. No new dependencies, no new
  stored data. Privacy proxy and owner/LAN gating unchanged.
