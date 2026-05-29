"""Data model for result personalization ("filter bubbles").

Port of the Android `RankingRules` / `Lens` / `Goggle` model. A `RankingRules` is the user's whole
personalization profile: per-domain rules (block / down-rank / up-rank / pin), a set of named
"lenses" (include/exclude filters, one of which may be active), and a list of Brave-style "goggle"
rules. The JSON shape is camelCase to mirror the Android kotlinx.serialization output so exports
interop between the two clients.

Everything here is pure and immutable: frozen dataclasses, tuples instead of lists, and `Mapping`
for the domain rules. Parsing and serialization are fail-soft and never raise; malformed JSON
yields an empty `RankingRules()`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar


class RankRule(str, Enum):  # noqa: UP042
    """What to do with a result whose host matches a rule.

    The value equals the name (e.g. ``RankRule.BLOCK.value == "BLOCK"``) so JSON uses the names,
    matching the Android enum serialization. We use ``(str, Enum)`` rather than ``StrEnum`` to keep
    the model interoperable with the Android port's contract.
    """

    BLOCK = "BLOCK"
    LOWER = "LOWER"
    NORMAL = "NORMAL"
    RAISE = "RAISE"
    PIN = "PIN"


@dataclass(frozen=True)
class Lens:
    """A named include/exclude filter over results.

    A lens passes a result when it satisfies all of its constraints: if `include_domains` is
    non-empty the host must match one of them; the host must match none of `exclude_domains`; if
    `include_keywords` is non-empty the text must contain one of them; the text must contain none of
    `exclude_keywords`. Tuples are used so the lens is hashable and immutable.
    """

    name: str
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoggleRule:
    """One Brave-style goggle rule: a site pattern and the action to apply to it."""

    site: str
    action: RankRule


@dataclass(frozen=True)
class RankingRules:
    """The user's whole personalization profile.

    `domain_rules` maps a domain to its rule (NORMAL entries are dropped on update). `lenses` is the
    set of saved lenses; `active_lens` is the name of the one currently applied (or None). `goggles`
    is the list of goggle rules. `EMPTY` is the canonical empty profile, equal to `RankingRules()`.
    """

    domain_rules: Mapping[str, RankRule] = field(default_factory=dict)
    lenses: tuple[Lens, ...] = ()
    active_lens: str | None = None
    goggles: tuple[GoggleRule, ...] = ()

    EMPTY: ClassVar[RankingRules]

    @property
    def active(self) -> Lens | None:
        """Return the lens whose name equals `active_lens`, or None if none is active/found."""
        if self.active_lens is None:
            return None
        for lens in self.lenses:
            if lens.name == self.active_lens:
                return lens
        return None

    def with_domain_rule(self, domain: str, rule: RankRule) -> RankingRules:
        """Return a copy with `domain` set to `rule`. A NORMAL rule removes the entry instead."""
        if rule is RankRule.NORMAL:
            return self.without_domain_rule(domain)
        updated = dict(self.domain_rules)
        updated[domain] = rule
        return RankingRules(
            domain_rules=updated,
            lenses=self.lenses,
            active_lens=self.active_lens,
            goggles=self.goggles,
        )

    def without_domain_rule(self, domain: str) -> RankingRules:
        """Return a copy with any rule for `domain` removed."""
        if domain not in self.domain_rules:
            return self
        updated = dict(self.domain_rules)
        updated.pop(domain, None)
        return RankingRules(
            domain_rules=updated,
            lenses=self.lenses,
            active_lens=self.active_lens,
            goggles=self.goggles,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the camelCase dict mirroring the Android serialization."""
        return {
            "domainRules": {domain: rule.value for domain, rule in self.domain_rules.items()},
            "lenses": [
                {
                    "name": lens.name,
                    "includeDomains": list(lens.include_domains),
                    "excludeDomains": list(lens.exclude_domains),
                    "includeKeywords": list(lens.include_keywords),
                    "excludeKeywords": list(lens.exclude_keywords),
                }
                for lens in self.lenses
            ],
            "activeLens": self.active_lens,
            "goggles": [{"site": g.site, "action": g.action.value} for g in self.goggles],
        }

    def to_json(self) -> str:
        """Serialize to a JSON string. Fail-soft: returns ``"{}"`` if serialization fails."""
        try:
            return json.dumps(self.to_dict(), ensure_ascii=False)
        except (TypeError, ValueError):
            return "{}"

    @classmethod
    def from_dict(cls, data: Any) -> RankingRules:
        """Build from a parsed dict. Fail-soft: anything unexpected yields empty rules."""
        if not isinstance(data, Mapping):
            return RankingRules()
        try:
            return RankingRules(
                domain_rules=_parse_domain_rules(data.get("domainRules")),
                lenses=_parse_lenses(data.get("lenses")),
                active_lens=_parse_active_lens(data.get("activeLens")),
                goggles=_parse_goggles_field(data.get("goggles")),
            )
        except Exception:
            return RankingRules()

    @classmethod
    def from_json(cls, text: str) -> RankingRules:
        """Parse from a JSON string. Fail-soft: malformed/mistyped JSON yields empty rules."""
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return RankingRules()
        return cls.from_dict(data)


RankingRules.EMPTY = RankingRules()


def _coerce_rule(value: Any) -> RankRule | None:
    """Return the RankRule for `value`, or None if it is not a known rule name."""
    if isinstance(value, str):
        try:
            return RankRule(value)
        except ValueError:
            return None
    return None


def _parse_domain_rules(raw: Any) -> dict[str, RankRule]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, RankRule] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        rule = _coerce_rule(value)
        if rule is not None:
            out[key] = rule
    return out


def _str_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def _parse_lenses(raw: Any) -> tuple[Lens, ...]:
    if not isinstance(raw, list):
        return ()
    lenses: list[Lens] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        lenses.append(
            Lens(
                name=name,
                include_domains=_str_tuple(entry.get("includeDomains")),
                exclude_domains=_str_tuple(entry.get("excludeDomains")),
                include_keywords=_str_tuple(entry.get("includeKeywords")),
                exclude_keywords=_str_tuple(entry.get("excludeKeywords")),
            )
        )
    return tuple(lenses)


def _parse_active_lens(raw: Any) -> str | None:
    return raw if isinstance(raw, str) else None


def _parse_goggles_field(raw: Any) -> tuple[GoggleRule, ...]:
    if not isinstance(raw, list):
        return ()
    goggles: list[GoggleRule] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        site = entry.get("site")
        action = _coerce_rule(entry.get("action"))
        if isinstance(site, str) and action is not None:
            goggles.append(GoggleRule(site=site, action=action))
    return tuple(goggles)
