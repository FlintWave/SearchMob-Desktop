## Context

The ranking pipeline today is `aggregate (RRF + dedup)` then `sort_results` then `apply_ranking`
(user domain rules / lenses / goggles / slop blocklist). It is stateless and static. We want a
learning layer that improves ranking from the owner's own clicks while honoring the locked
decisions: store-nothing-by-default, vault-encrypted personal state, owner-vs-network isolation, and
JSON wire-format parity with the Android app. Desktop ships first; Android mirrors it.

## Goals / Non-Goals

**Goals:**
- Ranking that improves the more the owner searches, from implicit click feedback, fully on-device.
- Encrypted, persistent, exportable, resettable; identical math and JSON across desktop and Android.
- Bounded and safe: cannot collapse diversity, cannot be poisoned by LAN clients, opt-in.

**Non-Goals:**
- Dwell-time / satisfied-click modeling (deferred; the desktop GUI opens results in an external
  browser, so dwell is awkward to observe consistently across platforms).
- A learned multi-feature model (FTRL) in v1; the closed-form counting model is the right
  effort/payoff for a small client and is trivially identical in two languages.
- Any server-side state for LAN clients, any new outbound calls, any new dependency.

## Decisions

**Beta-Bernoulli per-key counting model over a learned linear model.** Each key (`dom:<host>` and
`qt:<term>:<host>`) holds `{alpha, beta, lastSeenEpochDays}` with prior `Beta(2, 18)` (mean 0.10).
Update is one addition; no gradients, no matrix math, byte-identical in Python and Kotlin.
Alternative considered: FTRL-Proximal logistic regression. Rejected for v1 (feature hashing and
float determinism across languages add cross-platform risk for little gain at this scale); it can be
added later as a second tier.

**Click greater-than skip-above signal over raw CTR.** On a click at displayed position p, the
clicked host gets `alpha += 1` and each distinct host above p gets `beta += 1`; hosts below p are
ignored. This is the most position-bias-resistant signal available without a propensity pipeline and
needs only the in-memory result list plus the click, so no raw click log is stored on disk.

**Rank-based re-sort, not internal-score scaling.** The desktop `SearchResult` carries no score out
of the aggregator. To keep math identical across platforms, the apply pass computes
`weight = base(rank) * boost(dom) * boost(qt-terms)` with `base(rank) = 1/(rank+1)` and stable-sorts
by weight. `boost = clip(mu/global_mu, 0.5, 2.0)` with `global_mu` = prior mean, so an at-prior or
unseen key is exactly neutral (boost 1.0). This avoids exposing each platform's private RRF scale
and guarantees parity. The pass runs between `sort_results` and `apply_ranking` so explicit pin/raise
/lower/block rules, which re-bucket afterward, always win.

**Persist only the aggregate model, encrypted.** Store the serialized model JSON under encrypted-prefs
key `ranking.personalization`, mirroring `data/ranking_store.py`. No per-event log. Fail-soft to an
empty model when the vault is unavailable or locked (same behavior ranking rules already have under
zero-knowledge mode headlessly).

**Owner-only, two sources.** Native GUI clicks are inherently owner. Served-page learning uses a new
`/click` route gated to loopback; the server keeps a small bounded in-memory `rid -> ordered
(url, host)` map and redirects only to the recorded destination for `rid+pos` (no caller-supplied
URL), so it cannot be an open redirect and a LAN client cannot forge it. LAN clients keep bare
`<a href>` links, are never tracked, and are served the un-personalized order. The MCP scope is never
personalized and records nothing.

**Safety guardrails (defaults).** `EPSILON=0.10` (skip personalization entirely on 10% of queries),
cold-start gates (`MIN_SIGNAL_QUERIES=5`, `MIN_DOMAIN_IMPRESSIONS=3`, `MIN_QT_IMPRESSIONS=10`),
read-time time decay (`HALF_LIFE_DAYS=60`, pulling excess-over-prior toward the prior), and size caps
(`MAX_DOMAINS=2000`, `MAX_QT_PAIRS=10000`) evicting the lowest `alpha+beta`.

**Portable JSON `beta_bernoulli_v1`.** Config block (priors, global_mu, caps, epsilon, half_life)
plus `domains{}` and `qtPairs{}` of `{alpha, beta, lastSeenEpochDays}`. Floats rounded to 6 dp; days
as integer `epoch/86400`; keys lowercased, NFC, `www.` stripped, `:`-joined. The Android port asserts
byte-identical `to_json` against desktop fixtures.

## Risks / Trade-offs

- [Personalization narrows results into a filter bubble] -> bounded boost [0.5, 2.0], epsilon
  exploration, and time decay keep engine consensus primary and let unseen domains keep surfacing.
- [LAN client poisons or reads the owner's model] -> training and personalization are loopback-only;
  the `/click` endpoint redirects only to server-recorded destinations and 404s non-owner callers.
- [Zero-knowledge / locked vault cannot persist the model headlessly] -> personalization is simply
  absent in that context, with no error, matching how ranking rules already behave.
- [Cross-language drift in keys or floats breaks portability] -> fixed key-construction rules,
  6-dp float rounding, integer epoch-days, and a cross-platform fixture test in the Android phase.
- [Privacy: the model encodes the owner's interests] -> stored encrypted under the vault DEK, never
  transmitted, opt-in, resettable; the wizard copy states the residual local-device risk honestly.

## Migration Plan

Additive and off by default, so no data migration. Existing profiles are unaffected until the owner
opts in. Rollback is removing the apply pass and the toggle; the stored `ranking.personalization`
blob is ignored when the feature is absent. Ship desktop PR D1 (model + native learning + opt-in UI)
then D2 (served-page learning), then the Android parity PRs.

## Open Questions

- None blocking. Dwell-time weighting and an FTRL second tier are intentionally deferred and can be
  proposed as follow-up changes if the counting model proves insufficient.
