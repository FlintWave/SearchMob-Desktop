## Why

When an engine raises, times out, or returns nothing, the aggregator silently treats it as an empty
list (the fail-soft `EngineResult.Failure` equivalent). That is correct for resilience but invisible:
if a strong engine (e.g. DuckDuckGo) is rate-limiting or blocking one user's network, that user's
results quietly degrade with no signal, which reads as "the engine is bad" rather than "an engine is
down for me". We want the per-engine outcome to be visible to the owner so a degraded search is
diagnosable, without adding any telemetry or weakening the privacy posture.

## What Changes

- Have the aggregator report a per-engine outcome for each search: contributed (with a result count),
  returned empty, or failed (error/timeout). This is computed locally and never leaves the device.
- Surface it to the owner: a compact, unobtrusive status affordance in the GUI (e.g. "5 of 6 engines
  responded"), the same on the served page for the loopback owner only, and a line in the CLI.
- Keep it owner-only and store-nothing: network/LAN clients do not see engine status; nothing is
  persisted or sent anywhere.

## Capabilities

### New Capabilities
- `engine-status-visibility`: report and display, to the owner only, which engines contributed,
  returned nothing, or failed for a given search, computed locally with no telemetry.

### Modified Capabilities
<!-- None. The aggregator keeps its fail-soft behavior; this only exposes the per-engine outcome it
already computes internally. -->

## Non-goals

- Retrying, reordering, or disabling engines automatically based on failures: out of scope.
- Any remote reporting, analytics, or error upload: explicitly never.
- Showing engine status to LAN clients: owner-only.

## Impact

- Modified: `engines/aggregator.py` (return a per-engine outcome alongside the merged results, or via
  a side channel), the GUI results header (`gui/main_window.py`), `server/app.py` +
  `server/templates.py` (owner-only status line), and the CLI search command. Mirrored on Android
  (`engine/Aggregator.kt`, the results UI, the served page).
- No new dependencies, no new outbound calls, no stored data, no LAN-facing surface.
