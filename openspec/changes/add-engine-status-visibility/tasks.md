# Tasks: engine-status-visibility

## Desktop

- [x] `engines/aggregator.py`: capture per-engine outcome (contributed n / empty / failed) and return
      it alongside the merged results without breaking existing callers (`aggregate_with_status` ->
      `AggregateOutcome`; `aggregate` keeps its plain-list return). Engine labels via an `engine_id`
      attribute set by `bind_api_key`, else the `fetch_` name.
- [x] GUI: an unobtrusive "N of M engines responded" suffix on the status line, per-engine detail in
      the tooltip on hover.
- [x] Served page: render the line for the loopback owner only (`server/app.py` +
      `server/templates.py`, a native `<details>` disclosure); `()` passed for LAN clients.
- [x] CLI: print a dim per-search engine summary (responded count + which engines did not respond).
- [x] Tests: aggregator outcome (failed vs empty vs contributed); served-page owner-vs-LAN gating.

## Android (parity)

- [ ] `engine/Aggregator.kt`: same per-engine outcome.
- [ ] Results UI + served page (owner-only) show the same line.
- [ ] JVM/served tests.

## Verify + ship

- [ ] Confirm a forced engine failure shows as failed (not empty) and that LAN clients see nothing.
- [ ] Ship with "search relevance v1" (relevance + this), RC bypassed: local verify + CI, direct GA.
