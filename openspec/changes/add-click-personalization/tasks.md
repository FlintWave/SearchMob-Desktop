## 1. Core model (PR D1)

- [x] 1.1 Add `engines/rank/personalize.py`: `PersonalizationModel` dataclass + config defaults, key construction (`dom:`/`qt:` with NFC + lowercase + `www.` strip), `to_json`/`from_json` (`beta_bernoulli_v1`, 6-dp floats, integer epoch-days), fail-soft like `model.py`.
- [x] 1.2 Implement learning: `update_from_click(model, ordered_hosts, clicked_pos, query_terms, now)` applying the click-greater-than-skip-above counts for `dom:` and `qt:` keys, with caps + least-observed eviction.
- [x] 1.3 Implement scoring: `boost(model, host, query_terms, now)` with read-time decay and prior-neutral `global_mu`, clamped to [0.5, 2.0] and gated by cold-start thresholds.
- [x] 1.4 Implement `reorder(items, host_of, text_of, query, model, now, *, epsilon_rng)`: rank-based weight, stable sort, epsilon-greedy bypass, fail-soft to input.

## 2. Persistence and flag (PR D1)

- [x] 2.1 Add `data/personalization_store.py`: `load_personalization()` / `save_personalization()` over `open_encrypted_prefs()`, key `ranking.personalization`, fail-soft to empty model.
- [x] 2.2 Add `personalization_enabled: bool = False` to `UserPreferences` in `prefs.py` (+ `_from_dict`).

## 3. Apply pass and native click training (PR D1)

- [x] 3.1 Insert `reorder(...)` between `sort_results` and `apply_ranking` in `gui/main_window.py` `_apply_ranking_and_show` (only when enabled and the vault opens).
- [x] 3.2 Insert `reorder(...)` in `server/app.py` `_run_metasearch`, applied only for the owner (`_is_owner`); leave the MCP path untouched.
- [x] 3.3 Record native clicks: in `gui/results_view.py` `_on_activated`, call back with ordered displayed hosts + clicked row + current query; the controller updates and saves the model when enabled.

## 4. Opt-in UI (PR D1)

- [x] 4.1 Add a recommended first-run wizard step with the honest safety blurb wiring the toggle.
- [x] 4.2 Add the Settings toggle in `gui/settings_dialog.py` plus Export / Import / Reset personalization actions sharing the portable JSON.

## 5. Tests and gate (PR D1)

- [x] 5.1 Pure-helper tests: update math, skip-above, decay, caps/eviction, boost clamping, cold-start no-op, epsilon bypass, JSON round-trip, cross-key parity inputs.
- [x] 5.2 Settings/wizard persistence tests and an apply-pass test (learned domain rises within bounds, stays behind explicit pins).
- [x] 5.3 `ruff check` + `mypy` + `pytest` green (GUI tests with `QT_QPA_PLATFORM=offscreen`); bump version + CHANGELOG; open PR D1.

## 6. Served-page learning (PR D2)

- [x] 6.1 Add owner-only `/click` route in `server/app.py` with a bounded in-memory `rid -> ordered (url, host)` map; record the skip-above update and 302 to the recorded destination for `rid+pos`; 404 non-owner callers; add `/click` to the owner-gated paths.
- [x] 6.2 Render result links as `/click?...` only for owner/loopback requests in `server/templates.py`; LAN clients keep bare `<a href>` and are never tracked or personalized.
- [ ] 6.3 Tests: owner click records and redirects correctly; LAN client gets no tracking link and cannot forge `rid`/poison the model; bad `rid`/`pos` fail safe. Gate green; open PR D2.

## 7. Android parity (separate PRs A1/A2, mobile repo)

- [ ] 7.1 Port the identical model + schema + constants to Kotlin; persist under `ranking.personalization`; wire into `MetaSearchResultProvider.aggregateRanked` + the `onOpen` click path; add wizard/settings/export-import-reset; add the owner-only `/click` route in `SearchServer.kt`.
- [ ] 7.2 Cross-platform fixture tests asserting byte-identical `to_json` and identical boosts; extend the mobile `result-personalization` OpenSpec spec.
