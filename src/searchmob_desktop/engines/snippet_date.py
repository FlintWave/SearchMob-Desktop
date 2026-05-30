"""Best-effort publication-date extraction from a result's snippet/title.

General web engines rarely return a structured date, so the workhorse is parsing the leading date
that engines prefix onto snippets: "3 days ago - ...", "May 28, 2026 - ...", "28 May 2026", an ISO
date, or a bare year. Returns epoch milliseconds plus a precision/confidence so the sorter can
discount vague dates. Everything is fail-soft: anything unrecognized yields `None`.

Guards (so a stray number never masquerades as a real date):
* Only a date at the start of the text (within the first few tokens, or immediately followed by a
  separator) is trusted; a date buried mid-snippet is ignored.
* Absolute dates far in the future (> ~400 days) are rejected as template/footer junk ("(c) 2027");
  near-future absolute dates are kept - a "release date May 31" for an upcoming film is the point.
* A bare year on its own is `weak`: it contributes only a coarse ordering hint, never a real date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

_DAY_MS = 86_400_000
_RELATIVE_UNIT_MS: dict[str, int] = {
    "second": 1_000,
    "minute": 60_000,
    "hour": 3_600_000,
    "day": _DAY_MS,
    "week": 7 * _DAY_MS,
    "month": 2_629_800_000,  # 30.44 days
    "year": 31_557_600_000,  # 365.25 days
}
_MONTHS: dict[str, int] = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
# How far past `now` an absolute date may be before it is treated as junk.
_MAX_FUTURE_MS = 400 * _DAY_MS
# A leading match must begin within this many characters to be trusted.
_LEADING_WINDOW = 24

_RELATIVE_RE = re.compile(
    r"(\d{1,3})\s+(second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE
)
_YESTERDAY_RE = re.compile(r"\byesterday\b", re.IGNORECASE)
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_MDY_RE = re.compile(rf"\b{_MON}\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE)  # May 28, 2026
_DMY_RE = re.compile(rf"\b(\d{{1,2}})\s+{_MON}\s+(\d{{4}})\b", re.IGNORECASE)  # 28 May 2026
_MY_RE = re.compile(rf"\b{_MON}\s+(\d{{4}})\b", re.IGNORECASE)  # May 2026
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")  # 2026-05-28
_NUMERIC_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")  # 5/28/2026 (assume M/D/Y)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


class DatePrecision(Enum):
    """How precise/confident a parsed date is; the sorter discounts vaguer dates."""

    EXACT = "exact"
    DAY = "day"
    MONTH = "month"
    RELATIVE = "relative"


@dataclass(frozen=True, slots=True)
class ParsedDate:
    epoch_ms: int
    precision: DatePrecision
    weak: bool = False


def _ymd_to_ms(year: int, month: int, day: int) -> int | None:
    try:
        return int(datetime(year, month, day, tzinfo=UTC).timestamp() * 1000)
    except ValueError:
        return None


def _is_leading(match: re.Match[str], text: str) -> bool:
    """True when the match is at the start of the text or right before a separator."""
    if match.start() <= _LEADING_WINDOW:
        return True
    after = text[match.end() : match.end() + 2].lstrip()
    separators = {"-", "—", "–", "·", ".", "|"}  # noqa: RUF001 (dash variants engines emit)
    return bool(after[:1] in separators)


def parse_date(text: str, now_ms: int) -> ParsedDate | None:
    """Return the leading publication date in `text`, or `None` if none is confidently found."""
    if not text:
        return None
    snippet = text.strip()

    rel = _RELATIVE_RE.search(snippet)
    if rel and rel.start() <= _LEADING_WINDOW:
        amount = int(rel.group(1))
        unit_ms = _RELATIVE_UNIT_MS[rel.group(2).lower()]
        return ParsedDate(now_ms - amount * unit_ms, DatePrecision.RELATIVE)

    ymatch = _YESTERDAY_RE.search(snippet)
    if ymatch and ymatch.start() <= _LEADING_WINDOW:
        return ParsedDate(now_ms - _DAY_MS, DatePrecision.RELATIVE)

    # Absolute day-precision forms.
    for regex, order in (
        (_MDY_RE, "mdy"),
        (_DMY_RE, "dmy"),
        (_ISO_RE, "iso"),
        (_NUMERIC_RE, "num"),
    ):
        m = regex.search(snippet)
        if not m or not _is_leading(m, snippet):
            continue
        if order == "mdy":
            month, day, year = (
                _MONTHS.get(m.group(1).lower()[:3], 0),
                int(m.group(2)),
                int(m.group(3)),
            )
        elif order == "dmy":
            day, month, year = (
                int(m.group(1)),
                _MONTHS.get(m.group(2).lower()[:3], 0),
                int(m.group(3)),
            )
        elif order == "iso":
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if month == 0:
            continue
        ms = _ymd_to_ms(year, month, day)
        if ms is not None and ms <= now_ms + _MAX_FUTURE_MS:
            return ParsedDate(ms, DatePrecision.DAY)

    # Month + year ("May 2026").
    my = _MY_RE.search(snippet)
    if my and _is_leading(my, snippet):
        month, year = _MONTHS.get(my.group(1).lower()[:3], 0), int(my.group(2))
        ms = _ymd_to_ms(year, month, 15) if month else None
        if ms is not None and ms <= now_ms + _MAX_FUTURE_MS:
            return ParsedDate(ms, DatePrecision.MONTH)

    # Bare year - weak ordering hint only.
    yr = _YEAR_RE.search(snippet)
    if yr:
        ms = _ymd_to_ms(int(yr.group(1)), 7, 1)  # mid-year
        if ms is not None and ms <= now_ms + _MAX_FUTURE_MS:
            return ParsedDate(ms, DatePrecision.MONTH, weak=True)
    return None
