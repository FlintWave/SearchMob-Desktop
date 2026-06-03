# Tasks: engine-status-visibility

## Desktop

- [ ] `engines/aggregator.py`: capture per-engine outcome (contributed n / empty / failed) and return
      it alongside the merged results without breaking existing callers.
- [ ] GUI: show an unobtrusive "N of M engines responded" line near the results header, with
      per-engine detail on demand.
- [ ] Served page: render the same line for the loopback owner only (`server/app.py` +
      `server/templates.py`); never for LAN clients.
- [ ] CLI: print a dim per-search engine summary.
- [ ] Tests: aggregator outcome (failed vs empty vs contributed); served-page owner-vs-LAN gating.

## Android (parity)

- [ ] `engine/Aggregator.kt`: same per-engine outcome.
- [ ] Results UI + served page (owner-only) show the same line.
- [ ] JVM/served tests.

## Verify + ship

- [ ] Confirm a forced engine failure shows as failed (not empty) and that LAN clients see nothing.
- [ ] Ship with "search relevance v1" (relevance + this), RC bypassed: local verify + CI, direct GA.
