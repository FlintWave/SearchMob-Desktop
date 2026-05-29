"""Brave-style "goggles" parsing and host matching.

Port of the Android goggle parser. A goggle file is a list of rules, one per line, that boost,
down-rank, or discard results from matching sites. Lines starting with ``!`` are comments and
metadata lines (``name:``, ``description:``, ...) are ignored. Each rule combines a site pattern
with an action; ``matches`` decides whether a host satisfies a pattern, with ``*`` as a wildcard.

Parsing is fail-soft per line: a line that cannot be parsed is skipped, never raised.
"""

from __future__ import annotations

import re

from searchmob_desktop.engines.rank.model import GoggleRule, RankRule

_METADATA_PREFIXES: tuple[str, ...] = (
    "name:",
    "description:",
    "public:",
    "author:",
    "homepage:",
    "issues:",
    "avatar:",
    "license:",
)


def parse(text: str) -> list[GoggleRule]:
    """Parse goggle source `text` into a list of rules, skipping comments/metadata/bad lines."""
    rules: list[GoggleRule] = []
    for raw_line in text.splitlines():
        try:
            rule = _parse_line(raw_line)
        except Exception:
            continue
        if rule is not None:
            rules.append(rule)
    return rules


def _parse_line(raw_line: str) -> GoggleRule | None:
    line = raw_line.strip()
    if not line or line.startswith("!"):
        return None
    lowered = line.lower()
    if any(lowered.startswith(prefix) for prefix in _METADATA_PREFIXES):
        return None

    site: str | None = None
    action: RankRule | None = None
    for raw_part in line.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if part.startswith("site="):
            candidate = part[5:].strip()
            site = candidate or None
        elif part.startswith("$boost"):
            action = RankRule.RAISE
        elif part.startswith("$downrank"):
            action = RankRule.LOWER
        elif part == "$discard":
            action = RankRule.BLOCK
        elif not part.startswith("$") and site is None:
            site = part

    if site and action is not None:
        return GoggleRule(site=site, action=action)
    return None


def matches(pattern: str, host: str) -> bool:
    """Return True if `host` matches goggle `pattern`.

    The match is ``*``-wildcard, www-, and case-insensitive.
    """
    p = pattern.lower().removeprefix("www.")
    h = host.lower().removeprefix("www.")
    if "*" not in p:
        return h == p or h.endswith("." + p)
    try:
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in p)
        return bool(re.fullmatch(regex, h))
    except re.error:
        return False
