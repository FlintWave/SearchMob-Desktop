"""Map a UI locale to the per-engine language/region parameters that tailor results to it.

When the interface is switched to a language, results should follow: DuckDuckGo takes a `kl`
region-language code, and the Brave API takes `country` + `search_lang` + `ui_lang`. This module
holds the small, sourced lookup from a shipped locale tag to those values, plus a `LanguageRegion`
carrier the engines read off the `EngineContext`. English (and any unmapped tag) yields `None`, so
the engines fall back to their default (region-neutral) behaviour exactly as before.

Only engines that document a language/region parameter use this (DuckDuckGo, Brave). Mojeek,
Marginalia, and Mwmbl have no such parameter and are left unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LanguageRegion:
    """Per-engine language/region parameters for one UI locale.

    `ddg_kl` is DuckDuckGo's region-language code (e.g. `es-es`). `brave_search_lang` (ISO-639-1),
    `brave_country` (ISO-3166 alpha-2), and `brave_ui_lang` (BCP-47) are the Brave API parameters.
    Any field may be empty when an engine has no good code for that locale; the adapter omits it.
    """

    ddg_kl: str = ""
    brave_search_lang: str = ""
    brave_country: str = ""
    brave_ui_lang: str = ""


# Locale tag -> engine parameters. English is intentionally absent (region-neutral default). DDG
# `kl` uses its region-language form; some locales have no DDG region (left empty). Brave
# search_lang/country/ui_lang are filled per the Brave API's documented codes.
_REGIONS: dict[str, LanguageRegion] = {
    "zh": LanguageRegion("cn-zh", "zh-hans", "CN", "zh-CN"),
    "hi": LanguageRegion("in-en", "hi", "IN", "hi-IN"),
    "es": LanguageRegion("es-es", "es", "ES", "es-ES"),
    "ar": LanguageRegion("xa-ar", "ar", "SA", "ar-SA"),
    "fr": LanguageRegion("fr-fr", "fr", "FR", "fr-FR"),
    "bn": LanguageRegion("", "bn", "IN", "bn-IN"),
    "pt": LanguageRegion("br-pt", "pt", "BR", "pt-BR"),
    "id": LanguageRegion("id-id", "id", "ID", "id-ID"),
    "ur": LanguageRegion("", "ur", "PK", "ur-PK"),
}


def language_region_for(tag: str | None) -> LanguageRegion | None:
    """Return the engine language/region params for a locale `tag`, or None (English / unmapped)."""
    if not tag:
        return None
    primary = tag.strip().lower().replace("_", "-").split("-", 1)[0]
    return _REGIONS.get(primary)
