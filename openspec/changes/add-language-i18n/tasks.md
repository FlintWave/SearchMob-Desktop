# Tasks: ten-language UI, RTL, and result tailoring (desktop)

## i18n core

- [x] `i18n/locales.py`: the ten-language `Locale` registry (tag, English name, endonym, RTL flag),
      `normalize_tag`/`is_supported`/`locale_for`/`is_rtl`, and `resolve_os_locale` (env-var
      precedence, fail-soft to English).
- [x] `i18n/catalog.py`: `tr`/`trc`/`trn`/`N_`, process-wide active locale + `languageChanged`
      subscription, per-request `ContextVar` override (`set_request_locale`), English-source-is-key
      with English fallback, `CONTEXT_SEP` for `trc`.
- [x] `i18n/plurals.py`: CLDR plural categories per locale (`plural_category`,
      `plural_categories`, `representative_count`).
- [x] `i18n/__init__.py`: re-export the public surface.

## Authoring pipeline

- [x] `tools/i18n_author.py`: offline ollama (`translategemma`) authoring of the nine target locales
      from the English source catalog; incremental/resumable; placeholder masking (`%s`/`%d` and
      named `{token}` -> opaque `{pN}` and back); echo detection with one insistent retry then
      English fallback; plural authoring across each locale's CLDR categories.
- [x] `i18n/locales/*.json` + `*.plurals.json`: authored data for all nine target locales, full
      English key set, zero placeholder mismatches.

## Served page

- [x] `server/templates.py`: every chrome string wrapped in the catalog; each `render_*` sets the
      request locale from its authoritative `locale=` param; `lang` always set, `dir="rtl"` for RTL
      locales; logical CSS so one stylesheet mirrors.
- [x] `server/app.py`: `_resolve_locale` precedence (pinned pref -> `Accept-Language` ->
      OS -> English) with `set_request_locale`; `POST /language` persist route; region params
      threaded into `_run_metasearch` via `language_region_for`.

## GUI

- [x] All GUI widget modules: strings wrapped; `retranslate` on `languageChanged`; live language
      switch with no restart.
- [x] `gui/language.py`: the language picker/menu wiring.
- [x] `gui/app.py`: apply the saved/OS locale and `setLayoutDirection` at startup.
- [x] `prefs.py`: persist the `language` choice (empty = follow OS).

## Result tailoring

- [x] `engines/region.py`: `LanguageRegion` + `language_region_for` (DuckDuckGo `kl`; Brave
      `search_lang`/`country`/`ui_lang`); `None` for English/unmapped.
- [x] `engines/types.py`, `engines/duckduckgo.py`, `engines/brave_api.py`: carry and read the
      language/region params off the `EngineContext`; other engines unchanged.

## Tests

- [x] `tests/i18n/`: catalog translate+fallback, `trc` context, `trn` CLDR forms, `N_` identity,
      per-request override isolation; plural categories.
- [x] `tests/engines/test_region.py`: per-locale params, `None` for English/unmapped.
- [x] `tests/server/test_language_route.py`: locale resolution precedence, `/language` persist, RTL
      markup, region params reach the metasearch.
- [x] `tests/conftest.py`: autouse reset of the per-request locale override (test isolation).
- [x] `tests/server/test_a11y_markup.py`: updated for the localized/`lang`/`dir` markup.

## Verify

- [x] `ruff check`, `ruff format --check`, `mypy`, and `pytest` green.
- [x] `openspec validate add-language-i18n --strict` passes.
- [ ] Spot-check rendering incl. Arabic RTL served page + GUI live switch (release-verification
      procedure). Ship in the RC feature pile (own PR).
- [ ] Android i18n tracked in the Android repo's `add-language-i18n` change (own PR).
