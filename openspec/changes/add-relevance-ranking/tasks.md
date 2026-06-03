# Tasks: relevance-ranking

## Desktop (DONE, committed on branch `feat/search-relevance`, commit 43403be)

- [x] Add `engines/relevance.py`: `content_terms`, `_stem` (ASCII-gated), script helpers,
      `language_affinity`, `lexical_score` (head-term penalty), `blended_score` (demotion-only).
- [x] Wire the blend into `engines/aggregator.py` final sort key.
- [x] Unit tests `tests/engines/test_relevance.py` (coverage, stemming, head penalty, script
      affinity both directions, demotion-only cap, non-Latin tokenization).
- [x] ruff + mypy + engine tests green; verified empirically against live queries.

## Android (parity)

- [ ] Port to `engine/Relevance.kt` with the same constants and scoring.
- [ ] Wire into `engine/Aggregator.kt` final ordering.
- [ ] JVM unit tests mirroring the desktop cases.
- [ ] ktlint + lint + unit tests green.

## Verify + ship

- [ ] Run representative queries on both apps (this machine + the `searchmob` emulator) and confirm
      off-topic and wrong-language intrusions are demoted without regressing good results.
- [ ] Land as part of the "search relevance v1" release (relevance + engine-status visibility),
      RC bypassed per the user: local verification + CI green, then a direct GA.
