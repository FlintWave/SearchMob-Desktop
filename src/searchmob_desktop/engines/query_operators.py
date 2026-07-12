"""Google-style search operator parsing, ported from the Android `QueryOperators.kt`.

A raw query is parsed once into a `ParsedQuery`: `engine_query` is what actually goes upstream
(operators the engines themselves understand, `site:`, quoted phrases, `-exclusions`, `OR`/`|`,
are forwarded verbatim so the engine's own index does the heavy lifting; operators no public
engine implements consistently, `intitle:`, `inurl:`, `before:`, `after:`, are either turned into
a plain recall hint or dropped, and the actual constraint is enforced locally by `matches` over
the aggregated results). `clean_text` is the query with every operator stripped to plain words,
for anything that reasons about "what is the user asking about" rather than "how do I fetch it"
(on-device relevance, spelling correction, the contextual-summary lookup).

Pure and deterministic: no I/O, no locale/clock dependence beyond UTC date math, so the same
input always parses the same way. The server truncates queries at 512 characters before they ever
reach here, so this has to tolerate garbage (an unterminated quote, a bare `-`, an empty `site:`)
without raising, never silently dropping a token it does not understand; anything it cannot make
sense of falls back to being treated as ordinary query text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from searchmob_desktop.engines.rank.ranker import host_of_url

__all__ = ["ParsedQuery", "parse_query_operators"]

# Operator names this parser recognizes left of a `:`; anything else stays ordinary text.
_RECOGNIZED_OPS = frozenset({"site", "intitle", "inurl", "filetype", "ext", "before", "after"})

_YEAR = re.compile(r"^(\d{4})$")
# Month/day accept one or two digits: rejecting `after:2024-3-1` outright would keep the whole
# token as literal upstream query text (see `_apply_operator`), actively harming results.
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")
_FULL_DASH = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_FULL_SLASH = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")

# Maximal letter/digit runs (unicode-aware, underscore excluded), for whole-word exclusion
# matching. Same token shape as the relevance module's tokenizer.
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ParsedQuery:
    """A query parsed into its Google-style operators plus the leftover free text.

    See the module docstring for what `engine_query` and `clean_text` are for. The remaining
    fields are the structural filters `matches` enforces locally over the merged results.
    `after_ms`/`before_ms` are UTC epoch milliseconds at the start of the named day.
    """

    raw: str
    clean_text: str
    engine_query: str
    phrases: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    excluded_phrases: tuple[str, ...] = ()
    include_sites: tuple[str, ...] = ()
    exclude_sites: tuple[str, ...] = ()
    in_title: tuple[str, ...] = ()
    not_in_title: tuple[str, ...] = ()
    in_url: tuple[str, ...] = ()
    not_in_url: tuple[str, ...] = ()
    file_types: tuple[str, ...] = ()
    after_ms: int | None = None
    before_ms: int | None = None

    @property
    def has_filters(self) -> bool:
        """True when any operator is enforced locally by `matches` (everything but plain
        terms/phrases/OR)."""
        return bool(
            self.excluded_terms
            or self.excluded_phrases
            or self.include_sites
            or self.exclude_sites
            or self.in_title
            or self.not_in_title
            or self.in_url
            or self.not_in_url
            or self.file_types
            or self.after_ms is not None
            or self.before_ms is not None
        )

    @property
    def has_operators(self) -> bool:
        """True when the query carried any operator syntax at all.

        Used to skip the on-device spell corrector, which reasons about word spelling, not query
        syntax: an operator-laden query would just get its operators mangled.
        """
        return self.engine_query != self.clean_text or self.has_filters

    def matches(self, title: str, url: str, snippet: str, published: int | None) -> bool:
        """True when an aggregated result survives every locally-enforced operator in this query.

        Positive `phrases` and plain terms are deliberately NOT checked here: they were already
        sent upstream in `engine_query` and drive lexical relevance. A snippet is a partial
        excerpt of the page, so demanding the phrase appear in the title/snippet would reject
        results whose full body matches but whose short excerpt happens not to quote it; the
        engines and the relevance ranker are trusted to have already done that job.

        A date-window bound (`after_ms`/`before_ms`) excludes a result with no known `published`,
        deliberately: the user explicitly asked for a window, so an undated result cannot be
        confirmed to be in it and is treated as a miss rather than let through.
        """
        host = host_of_url(url)
        if self.include_sites and (
            host is None or not any(_site_matches(entry, host) for entry in self.include_sites)
        ):
            return False
        if (
            self.exclude_sites
            and host is not None
            and any(_site_matches(entry, host) for entry in self.exclude_sites)
        ):
            return False
        title_lower = title.lower()
        if any(needle.lower() not in title_lower for needle in self.in_title):
            return False
        if any(needle.lower() in title_lower for needle in self.not_in_title):
            return False
        url_lower = url.lower()
        if any(needle.lower() not in url_lower for needle in self.in_url):
            return False
        if any(needle.lower() in url_lower for needle in self.not_in_url):
            return False
        if self.file_types:
            extension = _extension_of(url)
            if extension is None or extension not in self.file_types:
                return False
        if self.after_ms is not None or self.before_ms is not None:
            if published is None:
                return False
            if self.after_ms is not None and published < self.after_ms:
                return False
            if self.before_ms is not None and published >= self.before_ms:
                return False
        if self.excluded_terms:
            words = _words_of(f"{title} {snippet} {host or ''}")
            if any(term.lower() in words for term in self.excluded_terms):
                return False
        haystack = f"{title} {snippet}".lower()
        if any(phrase.lower() in haystack for phrase in self.excluded_phrases):
            return False
        return True


def _site_matches(entry: str, host: str) -> bool:
    """Whether `entry` (a normalized `site:`/`-site:` value) covers `host`.

    An entry starting with `.` (a bare TLD like `.edu`) matches any host ending in it; otherwise
    the entry must equal the host or be one of its parent domains (`example.com` covers
    `docs.example.com` but not `notexample.com`).
    """
    if entry.startswith("."):
        return host.endswith(entry)
    return host == entry or host.endswith(f".{entry}")


def _extension_of(url: str) -> str | None:
    """The lowercased extension of `url`'s last path segment (query string and fragment ignored).

    None when the path has no segment or that segment has no dot. Parsed via `urlsplit` rather
    than naive string-splitting so a bare `https://example.com` never misreads its TLD (the
    `.com` in the host) as a file extension.
    """
    try:
        path = urlsplit(url.strip()).path
    except ValueError:
        return None
    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return None
    extension = last_segment.rsplit(".", 1)[-1].lower()
    return extension or None


def _words_of(text: str) -> set[str]:
    """Lowercased maximal letter/digit runs in `text`, for whole-word exclusion matching."""
    return {w.lower() for w in _WORD.findall(text)}


@dataclass(slots=True)
class _Accumulator:
    """The mutable lists `parse_query_operators` fills as it walks the tokens, in token order."""

    clean_parts: list[str] = field(default_factory=list)
    engine_parts: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)
    excluded_phrases: list[str] = field(default_factory=list)
    include_sites: list[str] = field(default_factory=list)
    exclude_sites: list[str] = field(default_factory=list)
    in_title: list[str] = field(default_factory=list)
    not_in_title: list[str] = field(default_factory=list)
    in_url: list[str] = field(default_factory=list)
    not_in_url: list[str] = field(default_factory=list)
    file_types: list[str] = field(default_factory=list)
    after_ms: int | None = None
    before_ms: int | None = None


def parse_query_operators(raw: str) -> ParsedQuery:
    """Parse Google-style search operators out of `raw` into a `ParsedQuery`.

    Recognizes `"exact phrase"`, `-term`, `site:`/`-site:`, `intitle:`, `inurl:`,
    `filetype:`/`ext:`, `before:`/`after:` dates (year, year-month, or full date), and `OR`/`|`.
    Total and fail-soft: malformed input is kept as ordinary query text, never dropped or raised
    on. `+word` is not special here (the server's scope-token pass runs before this parser).
    """
    acc = _Accumulator()
    for token in _tokenize(raw):
        if token in ("OR", "|"):
            acc.engine_parts.append(token)
            continue

        negated = len(token) > 1 and token.startswith("-")
        body = token[1:] if negated else token

        if body.startswith('"'):
            # A blank phrase (a stray `"` or `-"`) is dropped entirely: an empty excluded phrase
            # would match every result (`"" in text` is always True) and filter everything out.
            phrase = _unquote(body)
            if not phrase.strip():
                continue
            if negated:
                acc.excluded_phrases.append(phrase)
                acc.engine_parts.append(f'-"{phrase}"')
            else:
                acc.phrases.append(phrase)
                acc.clean_parts.append(phrase)
                acc.engine_parts.append(f'"{phrase}"')
            continue

        colon_index = body.find(":")
        op_name = body[:colon_index].lower() if colon_index > 0 else None
        if op_name is not None and op_name in _RECOGNIZED_OPS:
            value_raw = body[colon_index + 1 :]
            if _apply_operator(op_name, negated, token, value_raw, acc):
                continue

        if negated:
            acc.excluded_terms.append(body)
            acc.engine_parts.append(token)
        else:
            acc.clean_parts.append(token)
            acc.engine_parts.append(token)

    return ParsedQuery(
        raw=raw,
        clean_text=" ".join(acc.clean_parts),
        engine_query=" ".join(acc.engine_parts),
        phrases=tuple(acc.phrases),
        excluded_terms=tuple(acc.excluded_terms),
        excluded_phrases=tuple(acc.excluded_phrases),
        include_sites=tuple(acc.include_sites),
        exclude_sites=tuple(acc.exclude_sites),
        in_title=tuple(acc.in_title),
        not_in_title=tuple(acc.not_in_title),
        in_url=tuple(acc.in_url),
        not_in_url=tuple(acc.not_in_url),
        file_types=tuple(acc.file_types),
        after_ms=acc.after_ms,
        before_ms=acc.before_ms,
    )


def _apply_operator(
    op_name: str, negated: bool, token: str, value_raw: str, acc: _Accumulator
) -> bool:
    """Handle one `op:value` token, mutating `acc` for the recognized operators.

    Returns False to signal that the token was NOT actually consumed as an operator (a `-`
    negated `filetype:`/`ext:`/`before:`/`after:` has no defined negated meaning), so the caller
    falls back to treating it as a plain `-word` exclusion.
    """
    if op_name == "site":
        value = _normalize_site(_unquote_or_raw(value_raw))
        if not value:
            return True  # an empty operator is dropped entirely
        if negated:
            acc.exclude_sites.append(value)
            acc.engine_parts.append(f"-site:{value}")
        else:
            acc.include_sites.append(value)
            acc.engine_parts.append(f"site:{value}")
    elif op_name in ("filetype", "ext"):
        if negated:
            return False  # no defined negated meaning; caller treats it as -word
        value = _normalize_file_type(_unquote_or_raw(value_raw))
        if not value:
            return True
        acc.file_types.append(value)
        acc.engine_parts.append(f"filetype:{value}")
    elif op_name in ("intitle", "inurl"):
        value = _unquote_or_raw(value_raw)
        if not value:
            return True
        if negated:
            # -intitle:/-inurl: are locally-enforced only; dropped from the upstream query.
            (acc.not_in_title if op_name == "intitle" else acc.not_in_url).append(value)
        else:
            (acc.in_title if op_name == "intitle" else acc.in_url).append(value)
            acc.clean_parts.append(value)
            acc.engine_parts.append(value)
    elif op_name in ("before", "after"):
        if negated:
            return False  # no defined negated meaning; caller treats it as -word
        value = _unquote_or_raw(value_raw)
        if not value:
            return True
        millis = _parse_date(value)
        if millis is None:
            # Never silently drop something we could not parse: keep the whole token as text.
            acc.clean_parts.append(token)
            acc.engine_parts.append(token)
        elif op_name == "after":
            acc.after_ms = millis
        else:
            # before:/after: are locally-enforced only; dropped from the upstream query.
            acc.before_ms = millis
    return True


def _tokenize(raw: str) -> list[str]:
    """Split `raw` on whitespace, except inside `"..."`; an unterminated quote runs to the end."""
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    for ch in raw:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current.clear()
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _unquote(text: str) -> str:
    """Strip the surrounding quotes off `text` (which starts with `"`); an unterminated one runs
    to the end."""
    closing = text.find('"', 1)
    return text[1:closing] if closing >= 0 else text[1:]


def _unquote_or_raw(text: str) -> str:
    return _unquote(text) if text.startswith('"') else text


def _normalize_site(value: str) -> str:
    """`*.example.com` / `example.com.` -> `example.com`."""
    v = value.strip()
    if v.startswith("*."):
        v = v[2:]
    return v.rstrip(".").lower()


def _normalize_file_type(value: str) -> str:
    """`.PDF` / `PDF` -> `pdf`."""
    return value.strip().lower().removeprefix(".")


def _parse_date(value: str) -> int | None:
    """`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or `YYYY/MM/DD` -> UTC epoch millis at the start of that
    day (year/month default to day 1 / January 1). None for anything that does not match one of
    those shapes or names an impossible calendar date (e.g. month 13).
    """
    if _YEAR.match(value):
        parts = (int(value), 1, 1)
    elif match := _YEAR_MONTH.match(value):
        parts = (int(match.group(1)), int(match.group(2)), 1)
    elif match := _FULL_DASH.match(value) or _FULL_SLASH.match(value):
        parts = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    else:
        return None
    try:
        moment = datetime(parts[0], parts[1], parts[2], tzinfo=UTC)
    except ValueError:
        return None
    return int(moment.timestamp() * 1000)
