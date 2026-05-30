"""Snippet/title publication-date extraction: shapes parsed, and the false-positive guards."""

from __future__ import annotations

from datetime import UTC, datetime

from searchmob_desktop.engines.snippet_date import DatePrecision, parse_date

_NOW = int(datetime(2026, 5, 29, tzinfo=UTC).timestamp() * 1000)
_DAY = 86_400_000


def _ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def test_relative_days_ago() -> None:
    p = parse_date("3 days ago - SearchMob review", _NOW)
    assert p is not None and p.precision is DatePrecision.RELATIVE
    assert p.epoch_ms == _NOW - 3 * _DAY


def test_relative_hours_ago() -> None:
    p = parse_date("2 hours ago · breaking news", _NOW)
    assert p is not None and p.epoch_ms == _NOW - 2 * 3_600_000


def test_yesterday() -> None:
    p = parse_date("Yesterday - the latest scores", _NOW)
    assert p is not None and p.epoch_ms == _NOW - _DAY


def test_month_day_year() -> None:
    p = parse_date("May 28, 2026 - The Matrix 5 release date", _NOW)
    assert p is not None and p.precision is DatePrecision.DAY and p.epoch_ms == _ms(2026, 5, 28)


def test_day_month_year() -> None:
    p = parse_date("28 May 2026 — a profile", _NOW)
    assert p is not None and p.epoch_ms == _ms(2026, 5, 28)


def test_iso_date() -> None:
    p = parse_date("2026-05-28 release notes", _NOW)
    assert p is not None and p.epoch_ms == _ms(2026, 5, 28)


def test_near_future_absolute_is_kept() -> None:
    # A film out in a couple of days is exactly the case we must not reject.
    p = parse_date("May 31, 2026 - opening this weekend", _NOW)
    assert p is not None and p.epoch_ms == _ms(2026, 5, 31)


def test_far_future_year_is_rejected() -> None:
    # "(c) 2099" style footer junk must not register as a (very fresh) date.
    assert parse_date("Copyright 2099 Example Inc", _NOW) is None


def test_bare_year_is_weak() -> None:
    p = parse_date("A history of computing in 2019 and beyond", _NOW)
    assert p is not None and p.weak is True


def test_no_date_returns_none() -> None:
    assert parse_date("Mount Everest is Earth's highest mountain", _NOW) is None
    assert parse_date("", _NOW) is None
