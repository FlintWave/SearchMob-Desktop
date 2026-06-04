"""The set of UI languages SearchMob ships, plus OS-locale resolution.

The app translates its whole interface into the ten most-spoken world languages (English plus nine
authored locales). Each `Locale` carries its BCP-47 tag, an English name, the language's own
endonym (shown in the picker so a speaker recognizes it), and whether it is written right-to-left.

This module is pure and dependency-free so the GUI, the served page, and the offline authoring
script all share one source of truth for what is supported and how a tag maps to a language.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_LOCALE = "en"


@dataclass(frozen=True)
class Locale:
    """One shippable UI language."""

    tag: str
    english_name: str
    native_name: str
    rtl: bool = False


# The ten languages, ordered by global speaker count (English is the source-of-truth locale). `zh`
# is Simplified Chinese; Arabic and Urdu are right-to-left. Native names are the language endonyms.
SUPPORTED_LOCALES: tuple[Locale, ...] = (
    Locale("en", "English", "English"),
    Locale("zh", "Chinese (Simplified)", "简体中文"),
    Locale("hi", "Hindi", "हिन्दी"),
    Locale("es", "Spanish", "Español"),
    Locale("ar", "Arabic", "العربية", rtl=True),
    Locale("fr", "French", "Français"),
    Locale("bn", "Bengali", "বাংলা"),
    Locale("pt", "Portuguese", "Português"),
    Locale("id", "Indonesian", "Indonesia"),
    Locale("ur", "Urdu", "اردو", rtl=True),
)

_BY_TAG: dict[str, Locale] = {loc.tag: loc for loc in SUPPORTED_LOCALES}


def normalize_tag(tag: str | None) -> str:
    """Reduce a BCP-47-ish tag to a supported primary subtag, or `en`.

    Lowercases, splits on `-`/`_`, and maps the primary subtag to a shipped locale (so `es-MX`,
    `pt_BR`, `zh-Hans-CN`, and `ar-EG` all resolve to `es`/`pt`/`zh`/`ar`). Anything unrecognized
    falls back to the default locale, so callers always get a usable tag.
    """
    if not tag:
        return DEFAULT_LOCALE
    primary = tag.strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in _BY_TAG else DEFAULT_LOCALE


def is_supported(tag: str | None) -> bool:
    """Return True if `tag`'s primary subtag is one of the shipped locales."""
    if not tag:
        return False
    return tag.strip().lower().replace("_", "-").split("-", 1)[0] in _BY_TAG


def locale_for(tag: str | None) -> Locale:
    """Return the `Locale` for `tag` (normalized), defaulting to English."""
    return _BY_TAG[normalize_tag(tag)]


def is_rtl(tag: str | None) -> bool:
    """Return True if the (normalized) locale is written right-to-left (Arabic, Urdu)."""
    return locale_for(tag).rtl


def resolve_os_locale() -> str:
    """Best-effort detect the OS UI language, mapped to a shipped locale (else English).

    Reads the standard locale environment variables in precedence order. Fail-soft: any unset or
    unrecognized value yields the default locale, so first launch on an unsupported system is en.
    """
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        raw = os.environ.get(var)
        if raw:
            # LANGUAGE may be a colon-separated priority list; take the first entry.
            first = raw.split(":", 1)[0].split(".", 1)[0]
            if is_supported(first):
                return normalize_tag(first)
    return DEFAULT_LOCALE
