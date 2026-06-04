## Why

SearchMob's interface is English-only. Everything the user reads — the search box and its
placeholder, the verticals, the sort and scope controls, settings, dialogs, onboarding, and the
served page chrome — is a hardcoded English literal. For the large majority of the world that does
not read English comfortably, the app is unusable as a daily search tool even though the results it
aggregates are language-neutral. There is also no way to ask the engines for results in the user's
language, so a Spanish or Arabic speaker who could read the UI would still get English-leaning
result sets.

This change makes the whole product speak ten languages: English plus the nine most-spoken world
languages (Chinese, Hindi, Spanish, Arabic, French, Bengali, Portuguese, Indonesian, Urdu). It
translates the entire UI on both surfaces (the desktop GUI and the served page), lays the right-to-
left languages out correctly, and tailors result requests to the chosen language. The user picks a
language once; the app remembers it and, on first launch, follows the operating system's language.

## What Changes

- Add a pure, dependency-free i18n core: a locale registry (the ten shipped languages, each with its
  English name, endonym, and text direction) and a gettext-style runtime catalog. `tr("English
  source")` returns the active locale's translation with English fallback; `trn` handles
  CLDR plural forms (Arabic's six categories through to English's two); `trc` disambiguates
  identical English strings by context; `N_` marks a deferred literal so the extractor still sees it.
- Wrap every user-facing string on both surfaces in the catalog, with no English literal left in a
  widget or template. The GUI drives a process-wide active locale and re-translates live on change
  (no restart); the served page resolves a locale per request and renders that request in it, so the
  GUI's language and a visitor's language never interfere.
- Lay out the right-to-left languages (Arabic, Urdu) correctly: `dir="rtl"` and logical CSS on the
  served page, `setLayoutDirection` on the GUI, with the page `lang` attribute always set.
- Add a language picker to GUI Settings and to the served page; persist the choice. The served
  endpoint also honours the visitor's `Accept-Language` when the owner has not pinned a language.
  First launch with no saved choice follows the OS locale, falling back to English.
- Tailor results to the chosen language: a non-English locale carries per-engine language/region
  parameters (DuckDuckGo `kl`; Brave `country` + `search_lang` + `ui_lang`). English and any unmapped
  locale stay region-neutral, exactly as before. Engines without such a parameter are untouched.
- Author the translations offline from the English source catalog using a local model
  (`tools/i18n_author.py`, talking to a local ollama instance), not by hand — so strings are real
  translations, not fabrications, and the catalog can be regenerated and incrementally refilled.

## Capabilities

### New Capabilities
- `language-i18n`: a ten-language UI translated through a runtime catalog with English fallback,
  plural and context support, right-to-left layout for Arabic and Urdu, a persisted per-user language
  choice that follows the OS by default, per-request locale resolution on the served page, and
  result tailoring through per-engine language/region parameters.

### Modified Capabilities
<!-- None in contract. Result ranking, scopes, theming, and the engine set keep their meanings; the
language/region parameters tailor result requests without changing how results are ranked or filtered. -->

## Non-goals

- Translating result content. SearchMob translates its own interface and asks engines for
  language-appropriate results; it does not machine-translate the pages other engines return.
- Per-string human translation review this change. Translations are model-authored from the English
  source and regenerable; a human polish pass can follow without reopening this contract.
- Region/country selection independent of language. The language choice drives the result region;
  there is no separate country control in this change.
- Android. The Android sibling app gets the same treatment as its own change in the Android repo
  (per-locale `strings.xml`, per-app language, RTL, served mirror, engine params).
- New runtime dependencies or any network/telemetry. The authoring script is an offline developer
  tool; the shipped app reads static catalog files and makes no new outbound calls.

## Impact

- New: `i18n/` package — `locales.py` (the ten-language registry + OS-locale resolution),
  `catalog.py` (`tr`/`trc`/`trn`/`N_`, active-locale and per-request-locale state, `languageChanged`
  subscription), `plurals.py` (CLDR plural categories), and `i18n/locales/*.json` +
  `*.plurals.json` per-locale data (English is the source-of-truth key set).
- New: `engines/region.py` — locale to per-engine language/region parameter lookup (`LanguageRegion`
  on the `EngineContext`).
- New: `gui/language.py` — the GUI language picker/menu wiring; `tools/i18n_author.py` — the offline
  authoring pipeline.
- Modified: every GUI widget module and `server/templates.py` (strings wrapped in the catalog; RTL
  layout); `server/app.py` (per-request locale resolution, `Accept-Language`, the `/language`
  persist route, region params threaded into the metasearch); `engines/duckduckgo.py`,
  `engines/brave_api.py`, `engines/types.py` (read the language/region params); `prefs.py` (the saved
  `language`); `gui/app.py` (apply the OS/saved locale and layout direction at startup).
- No new dependencies, no new outbound calls, no telemetry. Result ranking and scope/theme behaviour
  are unchanged; English-locale behaviour is byte-for-byte as before.
