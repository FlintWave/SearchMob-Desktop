# Design: ten-language UI, RTL, and result tailoring

## The catalog: English-string-is-the-key

The runtime catalog (`i18n/catalog.py`) is gettext-shaped but keyed by the English source string
itself, so the code reads naturally and a missing translation degrades to readable English rather
than a `MISSING_KEY` token.

- `tr("Search the web")` returns the active locale's translation of that exact English string, or the
  English string itself when the locale has no entry. The English source is therefore both the key
  and the fallback; there is no separate `en.json` lookup on the hot path for English.
- `trc(context, source)` disambiguates two English strings that are spelled the same but translate
  differently (the noun "Date" sort label vs. a date value). It joins `context` and `source` with the
  gettext `\x04` separator (`CONTEXT_SEP`) to form the key.
- `trn(count, one, other)` selects a plural form. The authored data stores all CLDR categories the
  locale uses (`plurals.py` exposes `plural_category`/`plural_categories`); `trn` picks the category
  for `count` and substitutes the number. Languages range from English/Spanish (`one`, `other`) to
  Arabic (`zero`, `one`, `two`, `few`, `many`, `other`).
- `N_(source)` is an identity marker: it returns `source` unchanged but flags the literal for the AST
  extractor, so a string defined far from its `tr()` use-site (e.g. a table of labels translated
  later by variable) is still discovered.

The catalog is pure: no Qt, no network, no filesystem beyond loading the static per-locale JSON once.

## Two locale scopes: process-wide (GUI) vs. per-request (served)

The GUI is a single foreground application with one active language at a time; the served page can
field concurrent requests for different visitors. These need different locale state, so the catalog
carries both:

- **Active locale** (`set_active_locale`/`active_locale`) is process-global. The GUI sets it when the
  user changes language and emits `languageChanged` (via `subscribe`); every widget's `retranslate`
  runs and the UI re-renders in place, no restart. `gui/app.py` sets it once at startup from the
  saved pref or the OS locale and applies the matching `QApplication.setLayoutDirection`.
- **Request locale** (`set_request_locale`) is a `ContextVar` override that `tr()`/`trn()`/`trc()`
  consult first. The served renderers set it from the resolved per-request locale so nested bare
  `tr()` calls localize correctly without threading `locale=` through every helper. In production
  each request runs in its own asyncio task, so the override is naturally isolated. The synchronous
  test runner shares one context, so `tests/conftest.py` clears the override at each test boundary,
  reproducing that isolation.

The render functions take `locale=` as an authoritative parameter: each `render_*` sets the request
locale itself before rendering, so calling a renderer standalone with `locale="ar"` yields a fully
Arabic, RTL page — not an RTL shell around English text.

## Locale resolution on the served page

`server/app.py._resolve_locale(request)` decides one request's language, in precedence order:
1. The owner's pinned `language` pref, when set and supported.
2. The visitor's `Accept-Language` (first supported entry; the browser already orders them best-first,
   q-values ignored).
3. The server's OS locale, else English.

It then calls `set_request_locale` so the whole render is in that language. `POST /language` persists
the owner's choice (`normalize_tag(chosen)`, or empty to follow the OS/visitor); unknown tags are
ignored. `normalize_tag` reduces any BCP-47-ish tag to a shipped primary subtag (`es-MX`→`es`,
`zh-Hans-CN`→`zh`, `pt_BR`→`pt`), so headers and prefs from the wild always resolve to a usable
locale.

## Right-to-left

`is_rtl(tag)` is the single source of truth (Arabic, Urdu). On the served page the shell renders
`<html lang="…" dir="rtl">` and the stylesheet uses logical properties so the same CSS mirrors
correctly. In the GUI, `setLayoutDirection(RightToLeft)` flips the whole widget tree; switching
languages live re-applies the direction. The page `lang` attribute is always set (every locale),
which also helps the browser and assistive tech.

## Result tailoring (`engines/region.py`)

A non-English locale should bias result requests toward that language without changing how results
are ranked. `language_region_for(tag)` returns a `LanguageRegion` carrier (or `None` for English /
unmapped) that rides on the `EngineContext`:
- DuckDuckGo reads `ddg_kl` (its region-language code, e.g. `es-es`; empty where DDG has no region for
  the locale, e.g. Bengali/Urdu).
- Brave reads `brave_search_lang` (ISO-639-1) + `brave_country` (ISO-3166 alpha-2) + `brave_ui_lang`
  (BCP-47).
- Engines with no documented language parameter (Mojeek, Marginalia, Mwmbl) are untouched.
- English yields `None`, so result requests are byte-for-byte region-neutral as before — this change
  cannot regress English-locale results.

The parameters tailor the *request*; ranking, scopes, and domain rules are unchanged.

## Authoring the translations offline (`tools/i18n_author.py`)

Translations are model-authored, never hand-typed, so they are real and regenerable rather than
fabricated. The script is an offline developer tool (not shipped, no runtime dependency) that talks
to a local ollama instance (`translategemma`) over `http://localhost:11434`. It is incremental and
resumable: it only fills entries missing from a locale, so re-running after adding English strings
tops up the catalog without re-translating what is already there.

Two correctness measures matter because the model is imperfect:
- **Placeholder masking.** Before translating, every format placeholder — printf `%s`/`%d` and named
  `{token}` — is replaced with an opaque `{pN}` token and restored afterward. Without this the model
  echoes whole sentences that contain a bare `%s`, and *translates the name* of a semantic
  placeholder (`{version}`→`{संस्करण}`), breaking the format string. Masking makes placeholders
  survive untouched.
- **Echo detection.** A model that returns the input unchanged has failed to translate. The script
  retries once with an insistent prompt, then falls back to English; it does not accept an echo as a
  translation. Plural authoring accepts genuinely digit-less forms (Arabic's `one` omits the numeral)
  rather than requiring an `{n}` to appear, but still rejects a wholesale echo.

A handful of strings legitimately stay identical to English (loanwords like French "Web"/"Mode"); a
single string the model could only mangle is dropped from a locale so it falls back to English.

## Testing

- Catalog: `tr` translate-and-fallback; `trc` context disambiguation; `trn` uses the authored CLDR
  forms per locale; `N_` is identity; per-request override isolates from the active locale.
- Plurals: `plural_category` matches CLDR for representative counts across the locales.
- Locales: `normalize_tag`/`is_supported`/`resolve_os_locale` precedence and fallback.
- Region: `language_region_for` returns the documented params per locale, `None` for English/unmapped.
- Served: a non-English `?`/pref/`Accept-Language` renders that language with the right `lang`/`dir`;
  `/language` persists and is honoured; RTL markup present for Arabic; the metasearch receives the
  region params for a non-English locale and none for English.
- GUI: language switch retranslates widgets live and flips layout direction; startup applies the
  saved/OS locale.
- Data integrity: every locale has the full English key set (minus the deliberately dropped string);
  every plural file has all the locale's CLDR categories; placeholder tokens match between source and
  every translation (zero mismatches).
