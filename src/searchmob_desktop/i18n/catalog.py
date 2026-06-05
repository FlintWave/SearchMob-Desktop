"""Runtime string catalog: translate UI text against the active locale, with English fallback.

SearchMob uses the gettext model where the English source string *is* the key: code wraps a literal
in `tr("Search the web")`, and the catalog returns the active locale's translation or the English
source if there is none. Per-locale catalogs are authored offline (see the i18n authoring script)
and shipped as JSON files (`source -> translation`) under `locales/`.

The catalog is process-global and pure (no Qt): a single active locale plus a set of subscribers
notified when it changes. The GUI wraps it in a `QObject` that re-emits a `languageChanged` signal
so widgets re-translate live; the served page reads `tr(..., locale=tag)` per request without
touching the global. Loading is fail-soft: a missing or malformed catalog file yields English.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextvars import ContextVar
from functools import cache
from pathlib import Path

from searchmob_desktop.i18n.locales import DEFAULT_LOCALE, normalize_tag
from searchmob_desktop.i18n.plurals import plural_category

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"

# Separator joining a disambiguation context to its source into one catalog key, so the same English
# word can have different translations per context (gettext's `msgctxt`, which uses this same U+0004
# byte). `trc("sort order", "Date")` and `trc("calendar", "Date")` key separately.
CONTEXT_SEP = "\x04"

# Subscribers invoked (with the new tag) after the active locale changes. Used by the GUI to fan a
# Qt `languageChanged` signal out to widgets; kept as plain callables so this module stays Qt-free.
_subscribers: list[Callable[[str], None]] = []
_active_locale: str = DEFAULT_LOCALE

# A per-task locale override. The served page sets this at the start of each request so all the
# render helpers can call bare `tr(...)` and get the visitor's language, without threading `locale=`
# through every function and without disturbing the process-wide active locale (and so the GUI's
# `languageChanged` subscribers). Each Starlette request runs in its own asyncio task, so the
# ContextVar is naturally isolated per request; the GUI thread never sets it and uses the global.
_request_locale: ContextVar[str | None] = ContextVar("sm_request_locale", default=None)


@cache
def _load_catalog(tag: str) -> dict[str, str]:
    """Load + cache the `key -> translation` map for `tag` (empty for English / on any error).

    Keys are either a bare source string or a `context\x04source` composite (see `CONTEXT_SEP`).
    """
    if tag == DEFAULT_LOCALE:
        return {}
    path = _LOCALES_DIR / f"{tag}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v}


@cache
def _load_plural_catalog(tag: str) -> dict[str, dict[str, str]]:
    """Load + cache the `key -> {category: translation}` plural map for `tag` (empty for en)."""
    if tag == DEFAULT_LOCALE:
        return {}
    path = _LOCALES_DIR / f"{tag}.plurals.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, forms in data.items():
        if isinstance(forms, dict):
            out[str(key)] = {str(c): str(s) for c, s in forms.items() if isinstance(s, str) and s}
    return out


def _resolve_tag(locale: str | None) -> str:
    if locale is not None:
        return normalize_tag(locale)
    override = _request_locale.get()
    return override if override is not None else _active_locale


def _format(text: str, fmt: dict[str, object]) -> str:
    if not fmt:
        return text
    try:
        return text.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return text


def tr(
    source: str, /, *, context: str | None = None, locale: str | None = None, **fmt: object
) -> str:
    """Translate `source` for `locale` (or the active locale), falling back to the English source.

    `context` disambiguates a source that means different things in different places (e.g. "Date" as
    a sort order vs a calendar date); it must match the context used when the translation was
    authored. `fmt` keyword arguments are applied with `str.format`, so call sites use named
    placeholders (`tr("{count} results", count=n)`) which survive translation regardless of word
    order. A formatting error falls back to the unformatted string rather than raising.
    """
    tag = _resolve_tag(locale)
    if tag == DEFAULT_LOCALE:
        return _format(source, fmt)
    key = f"{context}{CONTEXT_SEP}{source}" if context else source
    catalog = _load_catalog(tag)
    return _format(catalog.get(key, source), fmt)


def trc(context: str, source: str, /, *, locale: str | None = None, **fmt: object) -> str:
    """Translate `source` under a disambiguation `context` (gettext `pgettext`). See `tr`."""
    return tr(source, context=context, locale=locale, **fmt)


def N_(source: str, *, context: str | None = None) -> str:
    """Mark a string literal for translation without translating it now (gettext's `N_`).

    Used where the actual `tr(...)`/`trc(...)` call only ever sees a variable — a label stored in a
    module-level options table, then looked up in a loop. Wrapping the literal in `N_(...)` at the
    definition site lets the offline extractor find it (with the same optional `context` the
    use-site `trc(context, label)` will pass), while the use-site call does the real lookup. `N_`
    itself is the identity function; `context` is ignored at runtime and only read by the extractor.
    """
    return source


def trn(
    count: int,
    one: str,
    other: str,
    /,
    *,
    context: str | None = None,
    locale: str | None = None,
    **fmt: object,
) -> str:
    """Translate a count-bearing string, picking the locale's CLDR plural form for `count`.

    `one`/`other` are the two English forms (use `{n}` for the number, e.g.
    `trn(k, "{n} result", "{n} results")`). The active locale's authored forms (which may be up to
    six: zero/one/two/few/many/other) are looked up by the English `other` form (plus `context`);
    the CLDR category for `count` is chosen, falling back to `other` then the English forms.
    `count` is exposed to formatting as `{n}`, alongside any extra `fmt`.
    """
    tag = _resolve_tag(locale)
    fmt_all: dict[str, object] = {"n": count, **fmt}
    if tag != DEFAULT_LOCALE:
        key = f"{context}{CONTEXT_SEP}{other}" if context else other
        forms = _load_plural_catalog(tag).get(key)
        if forms:
            category = plural_category(tag, count)
            template = forms.get(category) or forms.get("other")
            if template:
                return _format(template, fmt_all)
    english = one if plural_category(DEFAULT_LOCALE, count) == "one" else other
    return _format(english, fmt_all)


def set_active_locale(tag: str | None) -> str:
    """Set the process-wide active locale (normalized), notify subscribers, return the new tag."""
    global _active_locale
    new_tag = normalize_tag(tag)
    if new_tag == _active_locale:
        return new_tag
    _active_locale = new_tag
    for callback in tuple(_subscribers):
        try:
            callback(new_tag)
        except Exception:
            # A misbehaving subscriber must never break a language switch for the others.
            pass
    return new_tag


def active_locale() -> str:
    """Return the current process-wide active locale tag."""
    return _active_locale


def set_request_locale(tag: str | None) -> None:
    """Set the per-task (per-request) locale override read by `tr()` absent an explicit locale.

    Isolated to the calling asyncio task (each served request), so it never affects the GUI's
    process-wide active locale. Pass None to clear the override and fall back to the global.
    """
    _request_locale.set(normalize_tag(tag) if tag is not None else None)


def subscribe(callback: Callable[[str], None]) -> Callable[[], None]:
    """Register `callback` (called with the new tag) on locale change; return an unsubscribe fn."""
    _subscribers.append(callback)

    def _unsubscribe() -> None:
        try:
            _subscribers.remove(callback)
        except ValueError:
            pass

    return _unsubscribe


def available_translation_count(tag: str) -> int:
    """Number of translated strings shipped for `tag` (0 for English). Used by tests/diagnostics."""
    return len(_load_catalog(normalize_tag(tag)))
