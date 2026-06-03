# Tasks: result-paging

## Core

- [x] Separate pool size from reveal size: add `DEFAULT_POOL_SIZE` (engines/types.py) and raise the
      GUI, served, and CLI callers from 10 to the pool; the aggregator already returns
      `ranked[: ctx.max_results]`, now the pool.
- [x] `engines/aggregator.py`: ranks and returns the full pool (unchanged contract, larger cap).
- [ ] DEFERRED (documented, not dropped): optional page/offset on adapters that support it
      (Brave/Mojeek/Kagi). Most engines return a single page; the larger pool already removes the
      hard-10 truncation. Tracked as a follow-up; see Non-goals note below.

## Desktop UI

- [x] GUI results view: `ResultsView` holds the full ranked pool and reveals a window, growing it on
      scroll (scrollbar near-bottom) and topping up when too short to scroll.
- [x] Served page: renders the whole pool, collapses results past the first window, and reveals them
      in batches via a sentinel + inline `IntersectionObserver` script. No new request, store-nothing,
      degrades to all-visible without JS. Owner/LAN gating and the `/click` render cache unchanged
      (positions still map to the full rendered order).
- [x] CLI: `--max-results` maps to the pool size (default raised to the pool).

## Android (parity)

- [ ] `Aggregator.kt` already returns the full pool; add Compose `LazyColumn` infinite-scroll reveal
      and the served-page reveal (mirrors the desktop served approach). Done in the Android repo PR.

## Verify + ship

- [x] Desktop: ruff + mypy --strict + pytest green; live `serve` confirmed >10 results (36) with the
      collapse + reveal markup on a real query.
- [ ] Android: emulator verification (reveal grows on scroll; served page reveals).
- [ ] Ship as part of the RC feature pile (paging + engine-status + media-intent + the two new tasks);
      cut one `-rc` tag for the pile rather than a per-feature GA.

## Deferred deeper-fetch (boundary)

On-demand deeper fetch past the pool is deferred: the bigger pool fixes the "truncated" complaint, and
only a few engines paginate. If revisited, run a second fan-out for the next page on paginating engines
only, merge + re-rank into the pool, fail-soft for the rest. This is logged, not silently skipped.
