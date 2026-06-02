## Why

SearchMob's ranking is entirely static: results come back as engine-consensus order (RRF) plus
whatever raise/lower/pin/block rules the user authored by hand. Nothing improves on its own. We want
ranking that gets better the more the user searches, by quietly learning from the results they
actually click, without breaking the store-nothing, owner-safe privacy posture or parity with the
Android app.

## What Changes

- Add an on-device learning layer that adjusts ranking from implicit click feedback. It learns a
  per-domain and per-(query-term x domain) click preference and applies a bounded boost as a new
  pass between `sort_results` and `apply_ranking`.
- Use the position-bias-resistant "click greater-than skip-above" signal: the clicked result's host
  gains a positive count; hosts shown above it that were skipped gain a negative count.
- Feed the layer from two owner-only sources: native GUI clicks, and clicks on the served browser
  page through a new owner-only `/click` redirect endpoint. Network/LAN clients never train it and
  are never personalized.
- Persist the learned model encrypted in the vault under key `ranking.personalization`, alongside
  ranking rules. It survives reboots and updates and is absent (graceful) under a locked or
  zero-knowledge vault.
- Make it opt-in: a recommended step in the first-run wizard and a Settings toggle. Add
  Export / Import / Reset actions sharing a portable JSON model (`beta_bernoulli_v1`) with the
  Android app, so the learned state moves between devices for backup.
- Bound the effect for safety: boost clamped to [0.5, 2.0], epsilon-greedy exploration, cold-start
  gates, time decay, and size caps with least-observed eviction.

## Capabilities

### New Capabilities
- `result-personalization`: learn a bounded ranking adjustment from the owner's implicit click
  feedback, stored encrypted, owner-only, portable across devices, opt-in and resettable.

### Modified Capabilities
<!-- None. The desktop spec set is being established with this change; no existing requirements change. -->

## Impact

- New code: `engines/rank/personalize.py` (pure model + apply), `data/personalization_store.py`
  (vault persistence).
- Modified: `prefs.py` (a `personalization_enabled` flag), the GUI and server search choke points
  (`gui/main_window.py` `_apply_ranking_and_show`, `server/app.py` `_run_metasearch`), the GUI
  result click path (`gui/results_view.py`), the first-run wizard, `gui/settings_dialog.py`
  (toggle + export/import/reset), and `server/app.py` + `server/templates.py` (owner-only `/click`).
- Unchanged: the MCP agent-safety scope records nothing and is never personalized.
- No new third-party dependencies, no new outbound network calls, no new LAN-facing surface beyond
  the loopback-gated `/click` route.
