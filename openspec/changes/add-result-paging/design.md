# Design: result-paging

## Pool vs reveal

Split today's single `max_results=10` into two notions: a POOL size (how many merged results to rank
and hold, target ~30-50) and a REVEAL size (how many to show before the user scrolls, ~10). The
aggregator returns the ranked pool; the UI reveals a window of it and grows the window on scroll. No
new request happens until the pool is exhausted.

## Deeper fetch

Engine adapters gain an optional page/offset. When the pool is exhausted and the user wants more, run
a second fan-out for the next page on engines that support it (Brave/Mojeek/Kagi APIs do; several
HTML adapters do not). Merge and re-rank into the pool. Engines without paging are skipped, fail-soft.

## Surfaces

- GUI: the results list grows its model on reaching the end (QAbstractItemView scroll signal).
- Served page: incremental reveal via a small `?offset=`-style continuation or progressive rendering;
  no per-client server session (store-nothing). Owner/LAN gating unchanged.
- Android: Compose `LazyColumn` with an end-reached trigger.
- CLI: `--max-results` maps to the pool size.

## Privacy / owner / parity

- Nothing is cached or persisted across searches; a continuation re-derives from the query.
- LAN clients get the same incremental reveal but no stored session; owner-only controls unchanged.
- Parity: pool/reveal sizing and the deeper-fetch contract match the Android implementation.

## Ordering with the relevance + media-intent passes

Paging operates on the output of the full pipeline, so the relevance blend and (later) media-intent
promotion apply to the whole pool before it is revealed. Keep this ordering when both land.
