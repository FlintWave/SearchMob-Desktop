"""CLDR plural-category rules for the shipped locales.

Different languages split counts into different grammatical categories: English has two (`one`,
`other`), Arabic has six (`zero`, `one`, `two`, `few`, `many`, `other`), Chinese and Indonesian
have one (`other`). `plural_category` returns the CLDR category for an integer count in a locale, so
a count-bearing string (`trn`) can pick the right translated form. Only integer counts are handled
(the app never pluralizes fractions), which is the common subset of the CLDR rules.

`plural_categories` and `representative_count` support the offline authoring script: it asks the
model for each category a locale uses, using a representative integer that falls in that category.
"""

from __future__ import annotations

from searchmob_desktop.i18n.locales import normalize_tag

# CLDR plural categories in canonical order.
_ORDER = ("zero", "one", "two", "few", "many", "other")


def plural_category(locale: str | None, n: int) -> str:
    """Return the CLDR plural category ("one"/"few"/"other"/...) for integer `n` in `locale`."""
    tag = normalize_tag(locale)
    count = abs(int(n))
    if tag == "ar":
        if count == 0:
            return "zero"
        if count == 1:
            return "one"
        if count == 2:
            return "two"
        rem = count % 100
        if 3 <= rem <= 10:
            return "few"
        if 11 <= rem <= 99:
            return "many"
        return "other"
    if tag in ("zh", "id"):
        return "other"
    if tag in ("fr", "pt", "hi", "bn"):
        # one for 0 and 1, other otherwise.
        return "one" if count in (0, 1) else "other"
    # en, es, ur (and the default): one only for exactly 1.
    return "one" if count == 1 else "other"


def plural_categories(locale: str | None) -> tuple[str, ...]:
    """The CLDR categories a locale actually uses, in canonical order (for authoring all forms)."""
    seen = {plural_category(locale, n) for n in range(0, 121)}
    return tuple(cat for cat in _ORDER if cat in seen)


def representative_count(locale: str | None, category: str) -> int:
    """The smallest non-negative integer whose category is `category` in `locale` (0 if none)."""
    for n in range(0, 121):
        if plural_category(locale, n) == category:
            return n
    return 0
