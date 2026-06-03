## ADDED Requirements

### Requirement: Larger ranked result pool

The system SHALL fetch and merge a result pool larger than the previous fixed cap of 10, and SHALL
apply the full ranking pipeline (consensus fusion, relevance blend, sort, and user domain rules) to
the whole pool so that later results are ranked rather than raw. The per-engine fan-out SHALL remain
bounded.

#### Scenario: More than ten ranked results are available

- **WHEN** the configured engines return enough distinct results
- **THEN** the merged, ranked pool contains more than ten results available to the UI

### Requirement: Incremental reveal via infinite scroll

The system SHALL reveal results incrementally as the user scrolls toward the end of the list, in the
GUI, on the served page, and on Android, without issuing a new search request while unrevealed pooled
results remain.

#### Scenario: Scrolling reveals more without re-searching

- **WHEN** the user scrolls to the bottom of the visible results and pooled results remain
- **THEN** further results are shown without a new network search

### Requirement: On-demand deeper fetch where supported

The system SHALL, when the revealed pool is exhausted and an engine supports a page or offset
parameter, fetch the next page on demand. Engines without pagination SHALL contribute nothing further
and SHALL NOT cause an error.

#### Scenario: Exhausted pool fetches deeper only where possible

- **WHEN** the pool is exhausted and the user requests more
- **THEN** engines that support paging return a further page while engines that do not are skipped
  without failing the request
