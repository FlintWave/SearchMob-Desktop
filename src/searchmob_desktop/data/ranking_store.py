"""Persist the result-ranking rules as one JSON blob in the encrypted vault.

The rules (per-domain actions, lenses, imported goggles) are private personalization, so they live
in the same encrypted store as the BYO API keys rather than in the plaintext `prefs.json`. Reads
and writes are fail-soft: with no vault (or a locked one) `load_ranking_rules` returns empty rules
and `save_ranking_rules` reports failure, so the search path always has a usable rule set.
"""

from __future__ import annotations

from dataclasses import replace

from searchmob_desktop.data.vault_access import open_encrypted_prefs
from searchmob_desktop.engines.rank import DEFAULT_SAMPLE_LENSES, RankingRules

# Encrypted-prefs key holding the serialized RankingRules JSON.
RANKING_KEY = "ranking.rules"


def _with_default_lenses(rules: RankingRules) -> RankingRules:
    """Seed the built-in sample scopes when the profile has none, so they are available by default.

    The sample lenses are the starting scope set (no "add them" step): a fresh or never-customized
    profile gets them, so the scope selector is useful in the app and the served UI before any
    search and before the user creates their own. Once the profile has at least one lens (the user
    kept, edited, or added some), we return it as-is, so the samples are individually editable and
    only re-appear if the user removes every lens.
    """
    if rules.lenses:
        return rules
    return replace(rules, lenses=DEFAULT_SAMPLE_LENSES)


def load_ranking_rules() -> RankingRules:
    """Read the saved rules from the vault, seeding the sample scopes when the profile has none."""
    prefs = open_encrypted_prefs()
    if prefs is None:
        return _with_default_lenses(RankingRules())
    try:
        blob = prefs.get(RANKING_KEY)
    except Exception:
        return _with_default_lenses(RankingRules())
    if not blob:
        return _with_default_lenses(RankingRules())
    return _with_default_lenses(RankingRules.from_json(blob))


def save_ranking_rules(rules: RankingRules) -> bool:
    """Persist the rules to the vault. `True` on success, `False` if the vault is unavailable."""
    prefs = open_encrypted_prefs()
    if prefs is None:
        return False
    try:
        prefs.put(RANKING_KEY, rules.to_json())
    except Exception:
        return False
    return True
