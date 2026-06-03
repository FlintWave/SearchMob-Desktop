# Design: engine-status-visibility

## Approach

`aggregate()` already gathers per-engine results with `return_exceptions=True`. Capture the outcome
per engine while folding: `contributed(n)` when the engine returned a non-empty list, `empty` for an
empty list, `failed` for a `BaseException`. Return this map alongside the merged results (a small
dataclass, e.g. `AggregateOutcome(results, engine_status)`), keeping the existing return shape usable
by callers that ignore status.

## Surfacing

- GUI: a muted line near the results header, "5 of 6 engines responded", expandable to per-engine
  detail. No color-only signal (accessibility).
- Served page: the same line, rendered only when `_is_owner(request)` (loopback). Never for LAN.
- CLI: a dim summary line under the results table.

## Privacy / owner / parity

- Computed from data already in hand; nothing is stored or transmitted. This is the strongest
  reinforcement of the store-nothing/no-telemetry posture: even diagnostics stay on-device.
- Owner-only on the served surface via the existing `is_loopback_host` / `_is_owner` gate.
- Parity: Android computes the same outcome in `Aggregator.kt` and shows the same owner-only line.

## Non-goals reminder

No auto-retry/disable, no remote error reporting. Purely informational.
