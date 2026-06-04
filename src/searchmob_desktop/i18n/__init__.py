"""SearchMob UI internationalization: locale registry + runtime string catalog.

Pure, dependency-free (no Qt, no network). `tr` translates an English source string against the
active locale with English fallback; `SUPPORTED_LOCALES` is the shipped language set; the served
page passes `locale=` per request while the GUI drives the process-wide active locale and the
`languageChanged` signal.
"""

from __future__ import annotations

from searchmob_desktop.i18n.catalog import (
    CONTEXT_SEP,
    N_,
    active_locale,
    available_translation_count,
    set_active_locale,
    set_request_locale,
    subscribe,
    tr,
    trc,
    trn,
)
from searchmob_desktop.i18n.locales import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    Locale,
    is_rtl,
    is_supported,
    locale_for,
    normalize_tag,
    resolve_os_locale,
)
from searchmob_desktop.i18n.plurals import (
    plural_categories,
    plural_category,
    representative_count,
)

__all__ = [
    "CONTEXT_SEP",
    "DEFAULT_LOCALE",
    "N_",
    "SUPPORTED_LOCALES",
    "Locale",
    "active_locale",
    "available_translation_count",
    "is_rtl",
    "is_supported",
    "locale_for",
    "normalize_tag",
    "plural_categories",
    "plural_category",
    "representative_count",
    "resolve_os_locale",
    "set_active_locale",
    "set_request_locale",
    "subscribe",
    "tr",
    "trc",
    "trn",
]
