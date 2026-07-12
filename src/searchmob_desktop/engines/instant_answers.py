"""On-device instant answers, ported from the Android `engine/instant/` package.

Given a raw query, try each local producer in priority order: percentage ("15% of 80"), unit
conversion ("10 km to miles", "72 f to c"), number-base conversion ("0xff in decimal"), and a
small safe calculator ("2+2", "sqrt(9)*3"). The winner renders as an answer card above the
results, the way commercial engines answer directly.

Everything here is pure string/number work - no network, no storage, no logging - so it is safe
to run on every search request. It returns None for the overwhelming majority of queries, which
then proceed to normal metasearch untouched. Date- and phone-shaped input ("2020-2021",
"555-1234") is guarded so the calculator never renders an absurd subtraction card for them.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

__all__ = ["InstantAnswer", "InstantAnswerKind", "instant_answer"]


class InstantAnswerKind(Enum):
    """The kind of answer, so surfaces can label or style the card ("Calculator", ...)."""

    CALCULATOR = "calculator"
    UNIT_CONVERSION = "unit_conversion"
    BASE_CONVERSION = "base_conversion"
    PERCENTAGE = "percentage"


@dataclass(frozen=True, slots=True)
class InstantAnswer:
    """A computed, on-device instant answer for a query.

    `expression` is what was computed, normalized for display (e.g. `2 + 2` or `10 km`);
    `result` is the computed value formatted for display (e.g. `4` or `6.2137 miles`).
    """

    expression: str
    result: str
    kind: InstantAnswerKind


def _format_number(value: float) -> str:
    """Format for display: integers without a decimal point, everything else trimmed to at most
    10 significant digits with trailing zeros dropped, never scientific notation for the
    magnitudes a search box realistically produces."""
    if value == 0.0:
        return "0"
    if not math.isfinite(value):
        return str(value)
    if value == math.floor(value) and abs(value) < 1e15:
        return str(int(value))
    text = f"{value:.10g}"
    if "e" in text or "E" in text:
        text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text


# ---------------------------------------------------------------------------
# Calculator: a small, safe recursive-descent arithmetic evaluator.
# ---------------------------------------------------------------------------

_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "ln": math.log,
    "log": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}

_CONSTANTS = {"pi": math.pi, "e": math.e}


def _normalize_expression(expression: str) -> str:
    """Fold the unicode/most common alternate operator spellings into the canonical ones."""
    return (
        expression.replace("**", "^")
        .replace("×", "*")  # noqa: RUF001 - the multiplication sign is exactly what users type
        .replace("÷", "/")  # division sign
        .replace("−", "-")  # noqa: RUF001 - unicode minus, pasted from formatted text
        .replace(",", "")  # thousands separators: "1,000,000 / 4"
    )


def _looks_like_math(expression: str) -> bool:
    """True when the expression contains at least one operator, function, or parenthesis, so a
    plain number or word never triggers the calculator card."""
    normalized = _normalize_expression(expression)
    if not normalized.strip():
        return False
    has_operator = any(ch in "+*/%^(" for ch in normalized)
    # A '-' only counts as an operator when it is not just a leading sign ("-5").
    interior_minus = "-" in normalized.strip()[1:]
    has_function = any(name in normalized for name in _FUNCTIONS)
    return has_operator or interior_minus or has_function


class _Parser:
    """One-pass recursive descent over a fixed grammar: numbers, ``+ - * / %``, ``^``
    (right-associative), parentheses, unary minus, the constants pi/e, and a few common
    functions. Nothing is interpreted or executed beyond this grammar, so arbitrary query text
    can be thrown at it safely; every parse method returns None on any malformed input."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def at_end(self) -> bool:
        return self._pos >= len(self._text)

    def skip_whitespace(self) -> None:
        while self._pos < len(self._text) and self._text[self._pos].isspace():
            self._pos += 1

    def _peek(self) -> str | None:
        return self._text[self._pos] if self._pos < len(self._text) else None

    # expression := term (('+' | '-') term)*
    def parse_expression(self) -> float | None:
        value = self._parse_term()
        if value is None:
            return None
        while True:
            self.skip_whitespace()
            ch = self._peek()
            if ch == "+":
                self._pos += 1
                rhs = self._parse_term()
                if rhs is None:
                    return None
                value += rhs
            elif ch == "-":
                self._pos += 1
                rhs = self._parse_term()
                if rhs is None:
                    return None
                value -= rhs
            else:
                return value

    # term := factor (('*' | '/' | '%') factor)*
    def _parse_term(self) -> float | None:
        value = self._parse_factor()
        if value is None:
            return None
        while True:
            self.skip_whitespace()
            ch = self._peek()
            if ch == "*":
                self._pos += 1
                rhs = self._parse_factor()
                if rhs is None:
                    return None
                value *= rhs
            elif ch == "/":
                self._pos += 1
                rhs = self._parse_factor()
                if rhs is None or rhs == 0.0:
                    return None
                value /= rhs
            elif ch == "%":
                self._pos += 1
                rhs = self._parse_factor()
                if rhs is None or rhs == 0.0:
                    return None
                value = math.fmod(value, rhs)
            else:
                return value

    # factor := unary ('^' factor)?   (right-associative power)
    def _parse_factor(self) -> float | None:
        base = self._parse_unary()
        if base is None:
            return None
        self.skip_whitespace()
        if self._peek() == "^":
            self._pos += 1
            exponent = self._parse_factor()
            if exponent is None:
                return None
            try:
                result = base**exponent
            except (OverflowError, ValueError, ZeroDivisionError):
                return None
            # A negative base with a fractional exponent yields a complex number in Python; the
            # answer card only deals in reals, so treat it as not-a-calculation.
            if isinstance(result, complex):
                return None
            return float(result)
        return base

    # unary := '-' unary | primary
    def _parse_unary(self) -> float | None:
        self.skip_whitespace()
        if self._peek() == "-":
            self._pos += 1
            value = self._parse_unary()
            return None if value is None else -value
        return self._parse_primary()

    # primary := number | constant | function '(' expression ')' | '(' expression ')'
    def _parse_primary(self) -> float | None:
        self.skip_whitespace()
        ch = self._peek()
        if ch is None:
            return None
        if ch == "(":
            self._pos += 1
            value = self.parse_expression()
            if value is None:
                return None
            self.skip_whitespace()
            if self._peek() != ")":
                return None
            self._pos += 1
            return value
        if ch.isdigit() or ch == ".":
            return self._parse_number()
        if ch.isalpha():
            return self._parse_word()
        return None

    def _parse_number(self) -> float | None:
        start = self._pos
        while self._pos < len(self._text) and (
            self._text[self._pos].isdigit() or self._text[self._pos] == "."
        ):
            self._pos += 1
        # Scientific notation: 1.5e3 / 2E-4 (only when digits follow the exponent marker).
        if self._pos < len(self._text) and self._text[self._pos] in "eE":
            lookahead = self._pos + 1
            if lookahead < len(self._text) and self._text[lookahead] in "+-":
                lookahead += 1
            if lookahead < len(self._text) and self._text[lookahead].isdigit():
                self._pos = lookahead
                while self._pos < len(self._text) and self._text[self._pos].isdigit():
                    self._pos += 1
        try:
            return float(self._text[start : self._pos])
        except ValueError:
            return None

    def _parse_word(self) -> float | None:
        start = self._pos
        while self._pos < len(self._text) and self._text[self._pos].isalpha():
            self._pos += 1
        word = self._text[start : self._pos].lower()
        if word in _CONSTANTS:
            return _CONSTANTS[word]
        function = _FUNCTIONS.get(word)
        if function is None:
            return None
        self.skip_whitespace()
        if self._peek() != "(":
            return None
        self._pos += 1
        argument = self.parse_expression()
        if argument is None:
            return None
        self.skip_whitespace()
        if self._peek() != ")":
            return None
        self._pos += 1
        try:
            value = float(function(argument))
        except (ValueError, OverflowError):
            return None
        return value if math.isfinite(value) else None


def _evaluate(expression: str) -> float | None:
    """Evaluate the expression; None when it is not well-formed or the result is not finite."""
    parser = _Parser(_normalize_expression(expression))
    value = parser.parse_expression()
    if value is None:
        return None
    parser.skip_whitespace()
    if not parser.at_end():
        return None
    return value if math.isfinite(value) else None


# ---------------------------------------------------------------------------
# Unit conversion: fixed local table, linear units through a per-dimension base
# unit; temperature is affine and special-cased.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Unit:
    """One recognized unit: its dimension, factor to the dimension's base unit, display names."""

    dimension: str
    to_base: float
    singular: str
    plural: str


def _units_table() -> dict[str, _Unit]:
    table: dict[str, _Unit] = {}

    def register(unit: _Unit, *aliases: str) -> None:
        for alias in aliases:
            table[alias] = unit

    def unit(dimension: str, to_base: float, singular: str, plural: str | None = None) -> _Unit:
        return _Unit(dimension, to_base, singular, plural if plural is not None else singular + "s")

    # Length (base: meter)
    register(unit("length", 0.001, "millimeter"), "mm", "millimeter", "millimeters", "millimetre")
    register(unit("length", 0.01, "centimeter"), "cm", "centimeter", "centimeters", "centimetre")
    register(unit("length", 1.0, "meter"), "m", "meter", "meters", "metre", "metres")
    register(
        unit("length", 1000.0, "kilometer"),
        "km",
        "kilometer",
        "kilometers",
        "kilometre",
        "kilometres",
    )
    register(unit("length", 0.0254, "inch", "inches"), "in", "inch", "inches")
    register(unit("length", 0.3048, "foot", "feet"), "ft", "foot", "feet")
    register(unit("length", 0.9144, "yard"), "yd", "yard", "yards")
    register(unit("length", 1609.344, "mile"), "mi", "mile", "miles")
    register(unit("length", 1852.0, "nautical mile"), "nmi")
    # Mass (base: kilogram)
    register(unit("mass", 0.000001, "milligram"), "mg", "milligram", "milligrams")
    register(unit("mass", 0.001, "gram"), "g", "gram", "grams")
    register(unit("mass", 1.0, "kilogram"), "kg", "kilogram", "kilograms", "kilo", "kilos")
    register(unit("mass", 1000.0, "tonne"), "t", "tonne", "tonnes", "ton", "tons")
    register(unit("mass", 0.028349523125, "ounce"), "oz", "ounce", "ounces")
    register(unit("mass", 0.45359237, "pound"), "lb", "lbs", "pound", "pounds")
    register(unit("mass", 6.35029318, "stone"), "st", "stone", "stones")
    # Volume (base: liter)
    register(unit("volume", 0.001, "milliliter"), "ml", "milliliter", "milliliters", "millilitre")
    register(unit("volume", 1.0, "liter"), "l", "liter", "liters", "litre", "litres")
    register(unit("volume", 3.785411784, "US gallon"), "gal", "gallon", "gallons")
    register(unit("volume", 0.946352946, "US quart"), "qt", "quart", "quarts")
    register(unit("volume", 0.473176473, "US pint"), "pt", "pint", "pints")
    register(unit("volume", 0.2365882365, "cup"), "cup", "cups")
    register(unit("volume", 0.0295735295625, "fluid ounce"), "floz")
    # Speed (base: m/s). "m/s" only - a bare "ms" means milliseconds.
    register(_Unit("speed", 1.0, "m/s", "m/s"), "m/s", "mps")
    register(_Unit("speed", 1000.0 / 3600.0, "km/h", "km/h"), "km/h", "kmh", "kph")
    register(_Unit("speed", 0.44704, "mph", "mph"), "mph")
    register(unit("speed", 1852.0 / 3600.0, "knot"), "kn", "knot", "knots")
    # Time (base: second)
    register(unit("time", 0.001, "millisecond"), "ms", "millisecond", "milliseconds")
    register(unit("time", 1.0, "second"), "s", "sec", "secs", "second", "seconds")
    register(unit("time", 60.0, "minute"), "min", "mins", "minute", "minutes")
    register(unit("time", 3600.0, "hour"), "h", "hr", "hrs", "hour", "hours")
    register(unit("time", 86400.0, "day"), "day", "days")
    register(unit("time", 604800.0, "week"), "week", "weeks")
    register(unit("time", 31557600.0, "year"), "year", "years")
    # Data (SI decimal for kb/mb/...; binary for kib/mib/...; base: byte)
    register(unit("data", 1.0, "byte"), "byte", "bytes")
    register(unit("data", 1000.0, "kilobyte"), "kb", "kilobyte", "kilobytes")
    register(unit("data", 1_000_000.0, "megabyte"), "mb", "megabyte", "megabytes")
    register(unit("data", 1_000_000_000.0, "gigabyte"), "gb", "gigabyte", "gigabytes")
    register(unit("data", 1_000_000_000_000.0, "terabyte"), "tb", "terabyte", "terabytes")
    register(unit("data", 1024.0, "kibibyte"), "kib")
    register(unit("data", 1048576.0, "mebibyte"), "mib")
    register(unit("data", 1073741824.0, "gibibyte"), "gib")
    register(unit("data", 1099511627776.0, "tebibyte"), "tib")
    # Area (base: square meter)
    register(unit("area", 1.0, "square meter"), "m2", "sqm")
    register(unit("area", 1000000.0, "square kilometer"), "km2", "sqkm")
    register(unit("area", 2589988.110336, "square mile"), "mi2", "sqmi")
    register(unit("area", 0.09290304, "square foot", "square feet"), "ft2", "sqft")
    register(unit("area", 4046.8564224, "acre"), "acre", "acres")
    register(unit("area", 10000.0, "hectare"), "ha", "hectare", "hectares")
    return table


_UNITS = _units_table()

_TEMPERATURE_ALIASES = {
    "c": "c",
    "°c": "c",
    "celsius": "c",
    "centigrade": "c",
    "f": "f",
    "°f": "f",
    "fahrenheit": "f",
    "k": "k",
    "kelvin": "k",
}

# "<number> <unit> to|in|as <unit>", optionally prefixed with "convert". The unit spellings allow
# letters, digits (m2), degree signs, and slashes (m/s); multi-word names ("nautical mile") are
# covered by their compact aliases instead.
_CONVERSION = re.compile(
    r"^(?:convert\s+)?(-?\d+(?:[.,]\d+)?)\s*([a-z°/][a-z0-9°/]*)\s+(?:to|in|as)\s+([a-z°/][a-z0-9°/]*)$",
    re.IGNORECASE,
)


def _unit_label(unit: _Unit, value: float) -> str:
    return unit.singular if value == 1.0 else unit.plural


def _temperature(value: float, from_raw: str, to_raw: str) -> InstantAnswer | None:
    from_symbol = _TEMPERATURE_ALIASES.get(from_raw)
    to_symbol = _TEMPERATURE_ALIASES.get(to_raw)
    if from_symbol is None or to_symbol is None or from_symbol == to_symbol:
        return None
    if from_symbol == "c":
        celsius = value
    elif from_symbol == "f":
        celsius = (value - 32.0) * 5.0 / 9.0
    else:
        celsius = value - 273.15
    if to_symbol == "c":
        converted = celsius
    elif to_symbol == "f":
        converted = celsius * 9.0 / 5.0 + 32.0
    else:
        converted = celsius + 273.15

    labels = {"c": "°C", "f": "°F", "k": "K"}
    return InstantAnswer(
        expression=f"{_format_number(value)} {labels[from_symbol]}",
        result=f"{_format_number(converted)} {labels[to_symbol]}",
        kind=InstantAnswerKind.UNIT_CONVERSION,
    )


def _unit_conversion(query: str) -> InstantAnswer | None:
    """Convert per the query shape above, or None when not a recognizable conversion."""
    match = _CONVERSION.match(query.strip().lower())
    if match is None:
        return None
    raw_value, from_raw, to_raw = match.groups()
    try:
        value = float(raw_value.replace(",", "."))
    except ValueError:
        return None

    answer = _temperature(value, from_raw, to_raw)
    if answer is not None:
        return answer

    from_unit = _UNITS.get(from_raw)
    to_unit = _UNITS.get(to_raw)
    if from_unit is None or to_unit is None:
        return None
    if from_unit.dimension != to_unit.dimension or from_unit == to_unit:
        return None
    converted = value * from_unit.to_base / to_unit.to_base
    return InstantAnswer(
        expression=f"{_format_number(value)} {_unit_label(from_unit, value)}",
        result=f"{_format_number(converted)} {_unit_label(to_unit, converted)}",
        kind=InstantAnswerKind.UNIT_CONVERSION,
    )


# ---------------------------------------------------------------------------
# The front door.
# ---------------------------------------------------------------------------

# "15% of 80", "12.5 % of 40"
_PERCENT_OF = re.compile(
    r"^(?:what\s+is\s+)?(-?\d+(?:\.\d+)?)\s*%\s*of\s*(-?\d+(?:[.,]\d+)?)\??$",
    re.IGNORECASE,
)

# "0xff in decimal", "255 to hex", "0b1011 in decimal", "777 in binary"
_BASE_CONVERSION = re.compile(
    r"^(?:convert\s+)?(0x[0-9a-f]+|0b[01]+|0o[0-7]+|\d+)\s+(?:to|in|as)\s+"
    r"(hex|hexadecimal|binary|bin|octal|oct|decimal|dec)$",
    re.IGNORECASE,
)

# Digit runs joined only by '-' or '/': a date ("2024-01-15"), a year range ("2020-2021"), or a
# phone-ish number ("555-1234"). Evaluating those as subtraction/division would be an absurd
# answer card, so they are excluded from the calculator; a genuine "5-3" (short operands) is kept.
_DATE_OR_PHONE_LIKE = re.compile(r"^\d{1,4}([-/]\d{1,4}){2,}$|^\d{3,}\s*-\s*\d{3,}$")


def _percentage(query: str) -> InstantAnswer | None:
    match = _PERCENT_OF.match(query)
    if match is None:
        return None
    try:
        percent = float(match.group(1))
        of = float(match.group(2).replace(",", ""))
    except ValueError:
        return None
    return InstantAnswer(
        expression=f"{_format_number(percent)}% of {_format_number(of)}",
        result=_format_number(percent / 100.0 * of),
        kind=InstantAnswerKind.PERCENTAGE,
    )


def _base_conversion(query: str) -> InstantAnswer | None:
    match = _BASE_CONVERSION.match(query)
    if match is None:
        return None
    raw = match.group(1).lower()
    target = match.group(2).lower()
    try:
        if raw.startswith("0x"):
            value = int(raw[2:], 16)
        elif raw.startswith("0b"):
            value = int(raw[2:], 2)
        elif raw.startswith("0o"):
            value = int(raw[2:], 8)
        else:
            value = int(raw, 10)
    except ValueError:
        return None
    if target in ("hex", "hexadecimal"):
        result = "0x" + format(value, "x")
    elif target in ("binary", "bin"):
        result = "0b" + format(value, "b")
    elif target in ("octal", "oct"):
        result = "0o" + format(value, "o")
    else:
        result = str(value)
    # Converting a plain decimal to decimal answers nothing; skip so it falls through to search.
    if result == raw:
        return None
    return InstantAnswer(expression=raw, result=result, kind=InstantAnswerKind.BASE_CONVERSION)


def _calculation(query: str) -> InstantAnswer | None:
    # Guard before evaluating: a plain number, a date, or a word must never render a calculator
    # card. "what is 2+2" works; operator-free text does not reach the parser at all.
    expression = query
    for prefix in ("what is ", "What is "):
        expression = expression.removeprefix(prefix)
    expression = expression.removesuffix("=").strip()
    if _DATE_OR_PHONE_LIKE.match(expression):
        return None
    if not _looks_like_math(expression):
        return None
    value = _evaluate(expression)
    if value is None:
        return None
    return InstantAnswer(
        expression=expression,
        result=_format_number(value),
        kind=InstantAnswerKind.CALCULATOR,
    )


def instant_answer(query: str) -> InstantAnswer | None:
    """The instant answer for `query`, or None when no producer recognizes it."""
    trimmed = query.strip()
    if not trimmed or len(trimmed) > 256:
        return None
    return (
        _percentage(trimmed)
        or _unit_conversion(trimmed)
        or _base_conversion(trimmed)
        or _calculation(trimmed)
    )
