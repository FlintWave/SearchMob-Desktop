# Tasks: result-paging

## Core

- [ ] Separate pool size from reveal size in `EngineContext`/aggregator; default pool ~30-50.
- [ ] `engines/aggregator.py`: rank and return the full pool.
- [ ] Optional page/offset on adapters that support it (Brave/Mojeek/Kagi APIs first); fail-soft for
      the rest.

## Desktop UI

- [ ] GUI results view: infinite scroll growing the visible window from the pool, then deeper fetch.
- [ ] Served page: incremental reveal (progressive render / `?offset=`), store-nothing, owner/LAN
      gating unchanged.
- [ ] CLI: `--max-results` -> pool size.

## Android (parity)

- [ ] `Aggregator.kt` pool; Compose `LazyColumn` infinite scroll; served-page reveal.

## Verify + ship

- [ ] Confirm >10 ranked results, smooth scroll reveal with no surprise fetches mid-pool, deeper
      fetch only where engines support it.
- [ ] Tests: pool ranking, reveal windowing, deeper-fetch fail-soft.
- [ ] Ship after relevance v1; RC bypassed: local verify + CI, direct GA.
