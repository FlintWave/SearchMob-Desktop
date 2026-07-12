"""On-device instant answers: calculator, unit/base conversions, percentages, and the guards."""

from __future__ import annotations

from searchmob_desktop.engines.instant_answers import InstantAnswerKind, instant_answer


def _answer(query: str) -> str:
    result = instant_answer(query)
    assert result is not None, f"expected an instant answer for {query!r}"
    return result.result


def test_evaluates_basic_arithmetic() -> None:
    assert _answer("2+2") == "4"
    assert _answer("2 + 2") == "4"
    assert _answer("10/4") == "2.5"


def test_respects_precedence_and_parentheses() -> None:
    assert _answer("2+3*4") == "14"
    assert _answer("(2+3)*4") == "20"
    assert _answer("2^10") == "1024"
    assert _answer("2**10") == "1024"


def test_evaluates_functions_and_constants() -> None:
    assert _answer("sqrt(9)*3") == "9"
    assert _answer("abs(-5)+1") == "6"
    assert _answer("log(1000)+1") == "4"


def test_evaluates_unicode_operators_and_what_is_prefix() -> None:
    assert _answer("6×7") == "42"  # noqa: RUF001 - the real multiplication sign is the point
    assert _answer("84÷2") == "42"
    assert _answer("what is 2+2") == "4"
    assert _answer("2+2=") == "4"


def test_rejects_non_math_queries() -> None:
    assert instant_answer("kotlin coroutines") is None
    assert instant_answer("2024") is None
    assert instant_answer("-5") is None
    assert instant_answer("") is None
    assert instant_answer("x" * 300) is None


def test_rejects_dates_phones_and_year_ranges() -> None:
    assert instant_answer("2024-01-15") is None
    assert instant_answer("2020-2021") is None
    assert instant_answer("555-1234") is None
    assert instant_answer("31/12/2024") is None
    # A genuine short subtraction still computes.
    assert _answer("5-3") == "2"


def test_rejects_division_by_zero_and_malformed_input() -> None:
    assert instant_answer("1/0") is None
    assert instant_answer("2+") is None
    assert instant_answer("(2+3") is None
    assert instant_answer("sqrt(-1)") is None


def test_formats_results_cleanly() -> None:
    assert _answer("1/3+1/3+1/3") == "1"
    assert _answer("0.1+0.2") == "0.3"
    assert _answer("1,000,000/4") == "250000"


def test_computes_percent_of() -> None:
    answer = instant_answer("15% of 80")
    assert answer is not None
    assert answer.kind is InstantAnswerKind.PERCENTAGE
    assert answer.result == "12"
    assert _answer("12.5 % of 40") == "5"
    assert _answer("What is 15% of 80?") == "12"


def test_converts_between_bases() -> None:
    answer = instant_answer("0xff in decimal")
    assert answer is not None
    assert answer.kind is InstantAnswerKind.BASE_CONVERSION
    assert answer.result == "255"
    assert _answer("255 to hex") == "0xff"
    assert _answer("0b1011 in decimal") == "11"
    assert _answer("777 in binary") == "0b1100001001"


def test_decimal_to_decimal_falls_through() -> None:
    assert instant_answer("255 to decimal") is None


def test_converts_units_through_front_door() -> None:
    answer = instant_answer("10 km to miles")
    assert answer is not None
    assert answer.kind is InstantAnswerKind.UNIT_CONVERSION
    assert answer.result.endswith(" miles")
    assert answer.result.startswith("6.21")

    fahrenheit = instant_answer("72 f to c")
    assert fahrenheit is not None
    assert fahrenheit.result.startswith("22.2")
    assert fahrenheit.result.endswith("°C")

    assert instant_answer("10 km to kg") is None  # cross-dimension
    assert instant_answer("10 zz to yy") is None  # unknown units


def test_converts_data_and_time_units() -> None:
    assert _answer("100 mb in gb") == "0.1 gigabytes"
    assert _answer("90 min to hours") == "1.5 hours"
    assert _answer("1 kib to bytes") == "1024 bytes"
