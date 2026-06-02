"""Result personalization ("filter bubbles"): rules, lenses, goggles, and the ranking pass.

This package is pure: no GUI, no vault, no persistence, no network. The model
(`RankingRules`/`Lens`/`GoggleRule`/`RankRule`) round-trips to camelCase JSON matching the Android
client so profiles interop. `apply_ranking` re-buckets a relevance-ordered list of results per a
profile; `parse_goggles`/`goggle_matches` handle Brave-style goggle files.
"""

from __future__ import annotations

from searchmob_desktop.engines.rank.goggles import matches as goggle_matches
from searchmob_desktop.engines.rank.goggles import parse as parse_goggles
from searchmob_desktop.engines.rank.lenses import DEFAULT_SAMPLE_LENSES
from searchmob_desktop.engines.rank.model import GoggleRule, Lens, RankingRules, RankRule
from searchmob_desktop.engines.rank.personalize import PersonalizationModel
from searchmob_desktop.engines.rank.personalize import reorder as personalize_reorder
from searchmob_desktop.engines.rank.ranker import apply_ranking, domain_match, host_of_url

__all__ = [
    "DEFAULT_SAMPLE_LENSES",
    "GoggleRule",
    "Lens",
    "PersonalizationModel",
    "RankRule",
    "RankingRules",
    "apply_ranking",
    "domain_match",
    "goggle_matches",
    "host_of_url",
    "parse_goggles",
    "personalize_reorder",
]
